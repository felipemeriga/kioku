FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:0.9-python3.10-bookworm-slim AS builder

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache --no-install-project

COPY . .

FROM --platform=linux/amd64 python:3.10-slim-bookworm

# Fix for "At least one invalid signature was encountered" error in Debian Bookworm
RUN echo "APT::Sandbox::User \"root\";" > /etc/apt/apt.conf.d/99-sandbox-disable && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl git openssh-client \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 libx11-6 \
        libgomp1 libjpeg62-turbo libtiff6 libwebp7 libfreetype6 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only venv (deps) and source code, skip build cache
COPY --from=builder /app/.venv .venv
COPY --from=builder /app .

ENV PATH="/app/.venv/bin:$PATH"
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
