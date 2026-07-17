from fastapi.testclient import TestClient

import app.main as main


def test_health_requires_token():
    client = TestClient(main.app)
    assert client.get("/health").status_code == 401


def test_health_ok_with_token(monkeypatch):
    class _FakePingStore:
        def ping(self):
            return True, None

    monkeypatch.setattr(main, "store", _FakePingStore())
    client = TestClient(main.app)
    r = client.get("/health", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200 and r.json()["ok"] is True
