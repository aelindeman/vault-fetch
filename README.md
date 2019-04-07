# vault-fetch

vault-fetch reads secrets from [Hashicorp Vault](https://vaultproject.io) and writes them to files where an application can read them.

vault-fetch is best used as an InitContainer in Kubernetes, as a shim for setting up deployments for applications and microservices whose source is not under your control. **The best way to read from Vault will always be the app doing it natively** – vault-fetch is a fallback for when that isn't an option.

## Usage

1. Your application will need to have a Vault token that it can share with vault-fetch. Typically, this is done with another InitContainer, running before vault-fetch, which gets a token from [Vault's Kubernetes authentication backend](https://www.vaultproject.io/docs/auth/kubernetes.html) (e.g. [sethvargo/vault-kubernetes-authenticator](https://github.com/sethvargo/vault-kubernetes-authenticator)).

2. Provide vault-fetch with the `VAULT_ADDR` environment variable so it knows how to reach Vault, and `VAULT_TOKEN_PATH` to tell it where to find the Vault token. (You can also use `VAULT_TOKEN` to pass a token directly.)

3. Attach a few volumes to vault-fetch:

    - the volume containing the Vault token, probably generated from a previous InitContainer
    - the ConfigMap containing the [vault-fetch configuration](#configuration)
    - if necessary, the in-memory EmptyDir where you will be writing secrets (you can use the first volume if you've mounted it read-write)
    - if necessary, the volume or Secret containing Vault's CA certificates

4. Mount the Vault token and secrets volume to your deployment's containers, and read secrets from Vault as real files!

## Configuration

vault-fetch can read its configuration as JSON, TOML, or YAML. By default it will try to read JSON from `/opt/vault-fetch/config/vault-fetch.json`; you can change the configuration path by setting the `VAULT_FETCH_CONFIG` environment variable.

#### Informal schema

- `secrets` is an array of objects with `path` and `filename` keys:
    - `path` *(required, string)* is the secret's path in Vault.
    - `filename` *(required, string)* is where to put it the secret's contents.
        - Start your filenames with the same path as your Kubernetes authentication Vault token's volume's path (e.g. `/var/run/secrets/vaultproject.io`) to use them later in your deployment containers without needing to define another volume.
        - Write to an in-memory volume rather than to disk, so that secrets are not persisted if the Pod errors.
    - `field`, `template`, and `template_file` *(all optional, default: unspecified)* control how your secret is written to file:
        - `field` *(string or array of strings)* is the name of the secret's field(s) whose contents you want put into `filename` and available to the output template.
        - `template` *(string)* is a string containing field name placeholders (e.g. `${field}`) that can render the secret in place within a file.
        - `template_file` *(filename)* is a path to a file containing a template.
        - `template` and `template_file` may not be used simultaneously.
        - When `template` or `template_file` is not set:
            - If `field` is not specified, **all** of the secret's fields are put into `filename` as JSON.
            - Setting `field` to a string will dump that field to the file.
            - Setting `field` to an array of strings will dump each field to the file, in the order in which they are set in the array, separated by newlines.
        - When `template` or `template_file` is set:
            - If `field` is not specified, all of the secret's fields are available to the template.
            - Setting `field` to a string or array of strings will allow only that/those secret(s) to be replaced in the template.
    - `critical` *(optional, boolean, default: false)* controls whether vault-fetch exits if an error occurs while writing a particular secret. The default behavior (`false`) will cause it to be skipped but continue trying to write the remaining secrets.

You can also validate your config against [the schema file](schema.json).

#### Example config file

```json
{
  "secrets": [
    {
      "path": "secret/my-team/foo-app/some-secret",
      "filename": "/var/run/secrets/vaultproject.io/foo-app/secret",
      "field": "foo"
    },
    {
      "path": "secret/my-team/bar-app/secret-config",
      "filename": "/var/run/secrets/vaultproject.io/bar-app/config.json",
      "critical": true
    },
    {
      "path": "secret/my-team/baz-app/fancy-secret",
      "filename": "/var/run/secrets/vaultproject.io/baz-app/fancy",
      "template": "some_setting = '${field}'"
    }
  ]
}
```

Secrets are written one at a time in the order they are specified. You can abuse this functionality to write multiple Vault paths to a single file by writing secrets to a temporary `filename` and using the same value as a `template_file` for subsequent secrets. **This behavior is not guaranteed, and may change in a future release.**

#### Example Kubernetes configs

Deployment:

```yaml
initContainers:
  - name: vault-auth
    image: my-registry/vault-auth:latest
    env:
      - name: VAULT_ADDR
        value: https://vault.example.com:8200
      - name: VAULT_ROLE
        value: my-app-kubernetes-auth-role
    volumeMounts:
      - name: vault-volume
        mountPath: /var/run/secrets/vaultproject.io
  - name: vault-fetch
    image: aelindeman/vault-fetch:latest
    env:
      - name: VAULT_ADDR
        value: https://vault.example.com:8200
    volumeMounts:
      - name: vault-volume
        mountPath: /var/run/secrets/vaultproject.io
      - name: vault-fetch-config
        mountPath: /opt/vault-fetch/config
volumes:
  - name: vault-volume
    emptyDir:
      medium: Memory
  - name: vault-fetch-config
    configMap:
      name: my-app-vault-fetch-config
```

vault-fetch-config ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-app-vault-fetch-config
data:
  vault-fetch.json: |-
    {
      "secrets": [
        ...
      ]
    }
```

## Troubleshooting

- The `DEBUG` environment variable enables verbose logging. **This will print URLs of all Vault HTTP traffic to the console, which may include your Vault paths and fields, and may be picked up by a log collector. Use this option with caution.** You can enable verbose logging by adding `-e DEBUG=1` in Docker, or by setting adding an `env` into the vault-fetch container's Kubernetes config:

  ```yaml
  env:
    - name: DEBUG
      value: "1"
  ```

- Check that your application's Vault policy allows reading from any values you've configured in your `vault-fetch.json`, and that those secrets exist in Vault.
- Remove any `field` and `template` settings and see what fields get written as JSON.

## Authors

- [Alex Lindeman](https://github.com/aelindeman)
