# Tiny image for the serverless Cloud Run Jobs (capture + lab-cycle).
# Just Python + deps + the entrypoint; the entrypoint clones the repo fresh at
# runtime (always latest code + data) and commits results back. No server.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir requests websockets cryptography

COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["bash", "/entrypoint.sh"]
CMD ["capture"]
