"""End-to-end API tests via FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from obol_ledger.main import create_app
from obol_ledger import sample_data


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["service"] == "obol-ledger"


def test_consume_settlement_and_read_balance(client):
    env = sample_data.settled_envelope("evt_api_1").model_dump(mode="json")
    resp = client.post("/internal/events", json=env)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "posted"

    # Duplicate delivery is idempotent.
    dup = client.post("/internal/events", json=env)
    assert dup.json()["status"] == "duplicate"

    bal = client.get("/v1/accounts/seller_payable:sell_atelier/balance")
    assert bal.status_code == 200
    data = bal.json()
    assert data["balance"]["amount_minor"] == 11447
    assert data["balance"]["currency"] == "EUR"


def test_statement_endpoint(client):
    env = sample_data.settled_envelope("evt_api_2").model_dump(mode="json")
    client.post("/internal/events", json=env)

    resp = client.get("/v1/accounts/platform_revenue/statement")
    assert resp.status_code == 200
    body = resp.json()
    assert body["closing_balance"]["amount_minor"] == 348
    assert len(body["entries"]) == 1


def test_unknown_account_404(client):
    resp = client.get("/v1/accounts/nonsense_account/balance")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "account_not_found"
