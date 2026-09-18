.PHONY: install dev test run lint fmt clean docker

install:
	uv pip install -e ".[dev]" || pip install -e ".[dev]"

dev: install

test:
	pytest

run:
	uvicorn obol_ledger.main:app --reload --host 0.0.0.0 --port 8081

lint:
	ruff check obol_ledger tests

fmt:
	ruff format obol_ledger tests

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ *.egg-info build dist

docker:
	docker build -t obol-ledger:latest .
