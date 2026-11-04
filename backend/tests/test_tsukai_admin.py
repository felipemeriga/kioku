from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

from routes.usage import active_native_sessions
from services.ai.scope import ExecutionScope, sign_capability


def test_active_sessions_requires_current_server_verified_admin_before_runtime_access():
    sb = MagicMock()
    sb.auth.admin.get_user_by_id.return_value.user.email = "other@example.com"
    with (
        patch("routes.usage.get_supabase", return_value=sb),
        patch("services.ai.facade.client_for") as runtime,
    ):
        with pytest.raises(HTTPException) as caught:
            active_native_sessions(user_id="unprivileged")
    assert caught.value.status_code == 403
    runtime.assert_not_called()


def test_active_sessions_uses_non_admission_privileged_capability(monkeypatch):
    monkeypatch.setenv("TSUKAI_URL", "http://runner")
    sb, client = MagicMock(), MagicMock()
    sb.auth.admin.get_user_by_id.return_value.user.email = "felipe.meriga@gmail.com"
    client.active_sessions.return_value = {"sessions": [], "queued_counts": {"total": 0}}
    with (
        patch("routes.usage.get_supabase", return_value=sb),
        patch("services.ai.facade.client_for", return_value=client) as factory,
    ):
        result = active_native_sessions(user_id="admin")
    assert result["available"] is True
    scope, operation, profile = factory.call_args.args
    assert scope.admin is True and scope.owner_id == "admin"
    assert operation == "runtime.sessions.read" and profile is None


def test_admin_grant_cannot_be_repurposed_for_generation(monkeypatch):
    monkeypatch.setenv("TSUKAI_CAPABILITY_KEY", "a" * 32)
    scope = ExecutionScope("admin", admin=True)
    grant = sign_capability(scope, "runtime.sessions.read", None)
    claims = jwt.decode(grant, "a" * 32, audience="tsukai", algorithms=["HS256"])
    assert claims["admin"] is True
    assert claims["profiles"] == claims["folder_ids"] == claims["tool_allowlist"] == []
    with pytest.raises(PermissionError):
        sign_capability(scope, "rag_agent", "chat")
