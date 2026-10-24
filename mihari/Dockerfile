# syntax=docker/dockerfile:1
# Context: repository root. Builds the CLI from source, independent of npm releases.
FROM node:20-bookworm-slim AS cli-builder
WORKDIR /build
COPY cli/package.json cli/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts --no-audit --no-fund
COPY cli/tsconfig.json ./
COPY cli/src ./src
RUN npm run build && npm prune --omit=dev --ignore-scripts && \
    find dist -name '*.test.js' -delete

FROM python:3.11-slim-bookworm AS python-builder
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/opt/tool-bin
RUN --mount=type=cache,target=/root/.cache/uv \
    uv tool install --python /usr/local/bin/python graphifyy==0.9.94 && \
    uv venv /opt/mihari-venv && \
    uv pip install --python /opt/mihari-venv/bin/python requests cryptography boto3

FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=cli-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=cli-builder /build /opt/kioku-cli
COPY --from=python-builder /opt/uv-tools /opt/uv-tools
COPY --from=python-builder /opt/tool-bin /opt/tool-bin
COPY --from=python-builder /opt/mihari-venv /opt/mihari-venv
RUN ln -s /opt/kioku-cli/dist/index.js /usr/local/bin/kioku && \
    chmod +x /opt/kioku-cli/dist/index.js && kioku --version && \
    /opt/tool-bin/graphify --help >/dev/null && \
    /opt/mihari-venv/bin/python -c "import requests, cryptography, boto3"
ENV PATH="/opt/tool-bin:$PATH" PYTHONDONTWRITEBYTECODE=1
COPY mihari/mihari.py /app/mihari.py
VOLUME /data
CMD ["/opt/mihari-venv/bin/python", "/app/mihari.py"]
