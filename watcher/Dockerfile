# kioku-watcher — polls watched repos twice a day (host cron runs the
# container), re-indexing graph + code chunks when the principal branch moves.
# Build context is the REPO ROOT (the CLI is built from source, so the watcher
# never depends on the npm registry being current):
#   docker build -f watcher/Dockerfile -t felipemeriga1/kioku-watcher:latest .
FROM node:20-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git openssh-client python3 python3-pip python3-venv curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# graphify (AST extractor) via uv tools
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"
RUN uv tool install graphifyy

# kioku CLI from source
COPY cli /tmp/kioku-cli
RUN cd /tmp/kioku-cli && npm ci && npm run build && npm install -g . && \
    rm -rf /tmp/kioku-cli

# watcher runtime deps in a venv (PEP 668-safe)
RUN python3 -m venv /opt/watcher-venv && \
    /opt/watcher-venv/bin/pip install --no-cache-dir requests cryptography

COPY watcher/watcher.py /app/watcher.py

VOLUME /data
CMD ["/opt/watcher-venv/bin/python", "/app/watcher.py"]
