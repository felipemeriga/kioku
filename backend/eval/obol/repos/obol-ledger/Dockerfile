FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY obol_ledger ./obol_ledger

RUN pip install --upgrade pip && pip install -e .

EXPOSE 8081

CMD ["uvicorn", "obol_ledger.main:app", "--host", "0.0.0.0", "--port", "8081"]
