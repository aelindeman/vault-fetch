#!/usr/bin/env python3.7
'''vault-fetch fetches secrets from Vault and writes them to files.'''

from datetime import datetime
import json
import logging
import os
from string import Template
import sys

import hvac


class VaultFetch:
  '''main class that does all the stuff'''

  config = {}
  log = None
  vault = None
  vault_token = None
  secrets_written = 0
  files_written = []

  def __init__(self):
    self.log = logging.getLogger(self.__class__.__name__)
    self.log.debug('activated logger %s', self.__class__.__name__)

  def with_config(self, config=None, filename=None, loader='json'):
    '''with_config loads the configuration file from a json or yaml file'''
    if filename and not config:
      import toml
      import yaml
      loaders = {
        'json': json.load,
        'toml': toml.load,
        'yaml': yaml.safe_load
      }
      if loader not in loaders:
        raise ValueError('config of type %s is not supported; '
                         'type must be one of %s' %
                         (loader, list(loaders.keys())))
      with open(filename, 'r') as f:
        config = loaders[loader](f)

    # if there's multiple documents (yaml), use the first
    try:
      _ = iter(config)
      config = config[0]
    except (KeyError, TypeError):
      pass

    self.validate_config(config)
    self.config = config

  @staticmethod
  def validate_config(config):
    '''validate_config validates a configuration dict'''
    if not config:
      raise ValueError('config is empty')
    if not ('secrets' in config and isinstance(config['secrets'], list)):
      raise TypeError('config .secrets must be a list')
    for index, entry in enumerate(config['secrets']):
      for key in ['path', 'filename']:
        if not (key in entry and isinstance(entry[key], str)):
          raise TypeError('.secrets[%i].%s must be a string' % (index, key))
        if not entry[key]:
          raise ValueError('.secrets[%i].%s is empty' % (index, key))
      if 'field' in entry and not isinstance(entry['field'], (list, str)):
        raise TypeError('.secrets[%i].field must be a string, list, or None'
                        % index)
      for key in ['template', 'template_file']:
        if key in entry and not isinstance(entry[key], str):
          raise TypeError('.secrets[%i].%s must be a string or None'
                          % (index, key))
      if 'template' in entry and 'template_file' in entry:
        raise ValueError('.secrets[%i] cannot contain both template and '
                         'template_file keys' % index)
      if 'critical' in entry and not isinstance(entry['critical'], bool):
        raise ValueError('.secrets[%i].critical must be a bool'
                         % index)

  def with_vault_token(self, token=None, filename=None):
    '''
    with_vault_token reads a Vault token from :filename or sets one from the
    :token parameter
    '''
    if filename and not token:
      token_path = os.getenv('VAULT_TOKEN_PATH', filename)
      if os.path.exists(token_path):
        with open(token_path, 'r') as token_file:
          token = token_file.read()
      else:
        raise RuntimeError('Vault token is not loaded '
                           '(is VAULT_TOKEN or VAULT_TOKEN_PATH set?)')
    self.vault_token = token

  def connect_to_vault(self, hvac_args=None):
    '''opens a connection with Vault'''
    if not hvac_args:
      hvac_args = {
        'token': self.vault_token,
        'url': os.environ.get('VAULT_ADDR', 'https://127.0.0.1:8200'),
        'verify': os.environ.get('VAULT_CACERT',
                                 '/opt/vault-fetch/vault-ca.pem')
      }
    vault = hvac.Client(**hvac_args)
    assert vault.is_authenticated()
    self.vault = vault

  @staticmethod
  def format_secret(data, field=None, template=None):
    '''
    format_secret prepares the data from Vault for output

    :data is any secret data from Vault as a dict

    :field is optional, and when set will output only that field within the
    Vault secret as-is

    if no :field is given, the entire secret is formatted as JSON

    :field may also be a list of multiple fields, which will get written to
    lines in the same file in the order in which they're specified

    specifing :template changes the output to any string with matching field
    placeholders, parsed using `strings.Template.safe_substitute`
    '''
    if template:
      tpl = Template(template)
      tpl.idpattern = '(?a:.+)'
      if not field:
        output = tpl.safe_substitute(data)
      elif isinstance(field, str):
        output = tpl.safe_substitute({field: data[field]})
      elif isinstance(field, list):
        output = tpl.safe_substitute({i: data[i] for i in field})
      else:
        raise TypeError('not sure what to do with fieldspec of type %s'
                        % type(field))
    else:
      if not field:
        output = json.dumps(data)
      elif isinstance(field, str):
        output = data[field]
      elif isinstance(field, list):
        output = '\n'.join(data[i] for i in field)
      else:
        raise TypeError('not sure what to do with fieldspec of type %s'
                        % type(field))
    return output

  def write_secret(self, kwargs):
    '''
    write_secret writes the vault secret at :path to :filename, using a
    :template string (passed directly) or a :template_file (path to a file
    containing a template)
    '''
    filedir = os.path.dirname(kwargs['filename'])
    if not os.path.exists(filedir):
      os.makedirs(filedir)
      self.log.debug('created parent folder %s', filedir)

    secret = self.vault.read(kwargs['path'])
    if not (isinstance(secret, dict) and 'data' in secret):
      raise ValueError('Vault responded with an unexpected value of type %s'
                       % type(secret).__name__)

    template = kwargs.get('template', None)
    if not template and 'template_file' in kwargs:
      with open(kwargs['template_file'], 'r') as t:
        template = t.read()
        self.log.debug('read template file %s (%i bytes)',
                       kwargs['template_file'],
                       os.path.getsize(kwargs['template_file']))

    output = self.format_secret(secret['data'],
                                kwargs.get('field', None),
                                template)
    with open(kwargs['filename'], 'w') as f:
      f.write(output)

    self.secrets_written += 1
    if kwargs['filename'] not in self.files_written:
      self.files_written.append(kwargs['filename'])

    self.log.debug('finished writing%s secret to %s (%i bytes)',
                   ' critical' if kwargs.get('critical', False) else '',
                   kwargs['filename'], os.path.getsize(kwargs['filename']))

  def main(self):
    '''
    main runs through all secrets in config.json and attempts to write each
    '''
    def errfmt(error):
      '''include the error's fully-qualified class name in error messages'''
      return '%s (%s)' % (error,
                          type(error).__module__ + '.' + type(error).__name__)

    start_time = datetime.now()
    exited_on_critical = False

    try:
      config_file = os.getenv('VAULT_FETCH_CONFIG', 'config/vault-fetch.json')
      config_file_ext = config_file.split('.')[-1]
      self.with_config(filename=config_file, loader=config_file_ext)
      self.log.info('loaded config %s with %d secrets',
                    config_file, len(self.config['secrets']))
    except (OSError, RuntimeError) as err:
      self.log.critical('could not load config: %s', errfmt(err))
      sys.exit(1)
    except (KeyError, TypeError, ValueError) as err:
      self.log.critical('config file cannot be used: %s', errfmt(err))
      sys.exit(1)

    try:
      self.with_vault_token(token=os.getenv('VAULT_TOKEN'))
      if not self.vault_token:
        token_path = os.getenv('VAULT_TOKEN_PATH',
                               '/var/run/secrets/vault-volume/token')
        self.with_vault_token(filename=token_path)
      self.connect_to_vault()
    except (OSError, RuntimeError) as err:
      self.log.critical('could not read Vault token: %s', errfmt(err))
      sys.exit(1)
    except (AssertionError, ValueError, hvac.exceptions.VaultError) as err:
      self.log.critical('could not talk to Vault: %s', errfmt(err))
      sys.exit(1)

    secrets = self.config['secrets']
    for index, entry in enumerate(secrets):
      try:
        self.write_secret(entry)
        self.log.debug('successfully wrote .secrets[%i]', index)
      except (OSError, KeyError, TypeError, ValueError,
              hvac.exceptions.VaultError) as err:
        self.log.error('could not write .secrets[%i]: %s', index, errfmt(err))
        if 'critical' in entry and entry['critical']:
          self.log.error('stopping on failed critical secret .secrets[%i]',
                         index)
          exited_on_critical = True
          break

    success = len(secrets) == self.secrets_written
    log = {
      'fn': self.log.info if success else self.log.warning,
      'spl': '' if len(secrets) == 1 else 's',
      'fpl': '' if len(self.files_written) == 1 else 's',
      'duration': u'%i\u03BCs' % (datetime.now() - start_time).microseconds
    }

    log['fn']('wrote %i/%i secret%s to %i file%s in %s',
              self.secrets_written, len(secrets), log['spl'],
              len(self.files_written), log['fpl'], log['duration'])

    if exited_on_critical:
      sys.exit(1)


if __name__ == '__main__':
  DEBUG = bool(os.getenv('DEBUG'))
  logging.basicConfig(format='%(asctime)-15s [%(levelname)s] %(message)s',
                      level=logging.DEBUG if DEBUG else logging.INFO,
                      stream=sys.stdout,
                      style='%')
  VaultFetch().main()
  logging.shutdown()
