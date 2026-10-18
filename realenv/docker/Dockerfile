# Device image for the QUINTET real-environment campaign: coordinators and workers.
# The repository is bind-mounted read-only at /app at run time.
FROM python:3.12-slim
COPY ca*.crt /usr/local/share/ca-certificates/
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt
RUN (update-ca-certificates || true) && pip install --no-cache-dir numpy==2.1.3
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
