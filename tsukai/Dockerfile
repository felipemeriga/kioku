# Native binary is installed only during image build, never on service startup.
FROM debian:bookworm-slim AS claude
ARG CLAUDE_VERSION=2.1.318
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl bash \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://claude.ai/install.sh | bash -s -- "${CLAUDE_VERSION}" \
    && cp -L /root/.local/bin/claude /usr/local/bin/claude \
    && /usr/local/bin/claude --version | grep -F "${CLAUDE_VERSION}"

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home runner \
    && mkdir -p /state/claude /data/workspaces /app \
    && chown -R runner:runner /state /data \
    && chmod 0700 /state /state/claude /data /data/workspaces
COPY --from=claude /usr/local/bin/claude /usr/local/bin/claude
WORKDIR /app
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=0 UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable && rm -rf /root/.cache/uv
ENV HOME=/home/runner CLAUDE_CONFIG_DIR=/state/claude \
    TSUKAI_WORKSPACE_DIR=/data/workspaces PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
USER 1000:1000
EXPOSE 8788
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8788/health/live', timeout=2).close()"]
CMD ["uvicorn", "tsukai.app:app", "--host", "0.0.0.0", "--port", "8788", "--timeout-graceful-shutdown", "130"]
