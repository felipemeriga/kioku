from unittest.mock import patch


def test_staging_can_disable_notion_scheduler_without_changing_default(monkeypatch):
    from main import notion_scheduler_enabled

    monkeypatch.delenv("KIOKU_NOTION_SCHEDULER_ENABLED", raising=False)
    assert notion_scheduler_enabled()
    for disabled in ("false", "0", "no"):
        monkeypatch.setenv("KIOKU_NOTION_SCHEDULER_ENABLED", disabled)
        assert not notion_scheduler_enabled()


def test_disabled_scheduler_is_not_started_by_backend_lifespan(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setenv("KIOKU_NOTION_SCHEDULER_ENABLED", "false")
    monkeypatch.delenv("TSUKAI_URL", raising=False)
    with patch("main.sync_loop") as scheduler:
        with TestClient(main.app) as client:
            assert client.get("/api/health").status_code == 200
    scheduler.assert_not_called()
