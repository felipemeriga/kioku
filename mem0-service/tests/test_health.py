from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_requires_token():
    assert client.get("/health").status_code == 401


def test_health_ok_with_token():
    r = client.get("/health", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200 and r.json()["ok"] is True
