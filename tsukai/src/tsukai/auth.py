"""Backend-minted scope capabilities, never chosen from service identity alone."""

import hmac
import time

import jwt
from fastapi import HTTPException, Request
from pydantic import ValidationError

from .protocol import Capability, JobRequest


def service_auth(request: Request, settings):
    value = request.headers.get("authorization", "")
    if not settings.service_token or not hmac.compare_digest(
        value, "Bearer " + settings.service_token
    ):
        raise HTTPException(401, "service_auth_required")


def capability(request: Request, settings, allow_cleanup=False, allow_admin=False) -> Capability:
    service_auth(request, settings)
    try:
        raw = jwt.decode(
            request.headers.get("x-tsukai-capability", ""),
            settings.capability_key,
            algorithms=["HS256"],
            audience="tsukai",
            issuer=settings.capability_issuer,
            options={"require": ["exp", "iat", "jti", "sub", "owner_id"]},
        )
        cap = Capability.model_validate(raw)
        if cap.exp - cap.iat > 900 or cap.exp <= cap.iat or cap.iat > time.time() + 5:
            raise ValueError("invalid lifetime")
        if (
            cap.owner_id not in settings.entitled_owners
            and not (
                allow_cleanup
                and cap.sub == "backend"
                and set(cap.operations).issubset({"session.delete", "account.delete"})
            )
            and not (
                allow_admin
                and cap.admin
                and cap.sub == "backend"
                and cap.operations == ["runtime.sessions.read"]
            )
        ):
            raise HTTPException(403, "subscription_owner_not_entitled")
        return cap
    except (jwt.PyJWTError, ValidationError, ValueError):
        raise HTTPException(403, "scope_capability_invalid") from None


def authorize(cap: Capability, req: JobRequest, request_digest=None):
    if request_digest is not None and cap.request_sha256 != request_digest:
        raise HTTPException(403, "request_digest_mismatch")
    if (
        cap.owner_id != req.owner_id
        or cap.sub != req.caller
        or req.operation not in cap.operations
        or req.profile not in cap.profiles
        or not set(req.folder_ids).issubset(cap.folder_ids)
        or not set(req.tool_allowlist).issubset(cap.tool_allowlist)
        or cap.ai_depth != req.ai_depth
        or cap.parent_job_id != req.parent_job_id
        or cap.root_job_id != req.root_job_id
    ):
        raise HTTPException(403, "scope_capability_mismatch")
