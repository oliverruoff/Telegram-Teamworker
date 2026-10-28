FROM node:22.21.1-bookworm-slim AS node
FROM python:3.12-slim-bookworm

COPY --from=node /usr/local/ /usr/local/
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PI_CODING_AGENT_DIR=/workspace/data/pi-agent \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git gh openssh-client tini \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g @earendil-works/pi-coding-agent@1.4.0

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium
COPY teamworker ./teamworker
COPY entrypoint.sh ./

WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--", "/bin/sh", "/app/entrypoint.sh"]
CMD ["python", "-m", "teamworker"]
ENV PYTHONPATH=/app
