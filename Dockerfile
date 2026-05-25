# Tiny image for the serverless Cloud Run Jobs (capture + lab-cycle).
# Python + deps + a stable bootstrap that clones the repo fresh at runtime and
# hands off to deploy/run_job.sh in the repo — so job logic deploys via `git push`
# with no rebuild. No server, scales to zero.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir requests websockets cryptography

COPY deploy/bootstrap.sh /bootstrap.sh
RUN chmod +x /bootstrap.sh
ENTRYPOINT ["bash", "/bootstrap.sh"]
CMD ["capture"]
