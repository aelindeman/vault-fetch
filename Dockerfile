FROM python:3.7 AS builder
WORKDIR /opt/vault-fetch
COPY requirements.txt __init__.py ./
RUN pip install --no-cache-dir -r requirements.txt pyinstaller && \
    pyinstaller --onefile -n vault-fetch __init__.py

FROM scratch AS release
ENV VAULT_ADDR='https://127.0.0.1:8200' \
    VAULT_CACERT='/opt/vault-fetch/vault-ca.pem' \
    VAULT_TOKEN=''
COPY --from=builder /opt/vault-fetch/dist/vault-fetch \
                    /opt/vault-fetch/vault-fetch
CMD ["/opt/vault-fetch/vault-fetch"]
