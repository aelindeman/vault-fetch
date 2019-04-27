FROM python:3.7-alpine
LABEL org.label-schema.name='vault-fetch' \
      org.label-schema.description='Read Hashicorp Vault secrets as if they were files' \
      org.label-schema.url='https://github.com/aelindeman/vault-fetch'
ENV VAULT_ADDR='https://127.0.0.1:8200' \
    VAULT_CACERT='/opt/vault-fetch/vault-ca.pem' \
    VAULT_TOKEN=''
WORKDIR /opt/vault-fetch
COPY requirements.txt __init__.py ./
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "/opt/vault-fetch/__init__.py"]
