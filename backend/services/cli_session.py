"""Mint a separate email-auth session for an explicitly authorized CLI device.

Never verify OTPs on the shared Supabase SDK client: that would replace its
service-role authorization. All OTPs and session credentials stay server-side.
"""

import os
import time

import httpx
import jwt


class DeviceSessionUnavailable(Exception):
    pass


class DeviceSessionUnsupported(DeviceSessionUnavailable):
    pass


async def create_device_session(user_id: str, browser_token: str) -> dict:
    base = os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1"
    public_key = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    service_key = os.environ["SUPABASE_SERVICE_KEY"]
    if not public_key:
        raise DeviceSessionUnavailable("Device session configuration unavailable")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        # Revalidate the browser with Auth; never trust body-supplied email or identity.
        response = await client.get(
            base + "/user",
            headers={"apikey": public_key, "Authorization": "Bearer " + browser_token},
        )
        response.raise_for_status()
        user = response.json()
        if user.get("id") != user_id or not user.get("email") or not user.get("email_confirmed_at"):
            raise DeviceSessionUnavailable("Device identity could not be verified")
        # Email OTP cannot reproduce an MFA assurance level; do not silently downgrade it.
        if any(factor.get("status") == "verified" for factor in user.get("factors", [])):
            raise DeviceSessionUnsupported(
                "CLI authorization for MFA-enabled accounts requires a separate MFA login flow."
            )
        response = await client.post(
            base + "/admin/generate_link",
            headers={"apikey": service_key, "Authorization": "Bearer " + service_key},
            json={"type": "magiclink", "email": user["email"]},
        )
        response.raise_for_status()
        generated = response.json()
        # Supabase's raw Auth endpoint returns the user fields alongside the OTP.
        if generated.get("id") != user_id or not generated.get("hashed_token"):
            raise DeviceSessionUnavailable("Device identity could not be verified")
        response = await client.post(
            base + "/verify",
            headers={"apikey": public_key},
            json={"type": "email", "token_hash": generated["hashed_token"]},
        )
        response.raise_for_status()
        session = response.json()
        token = session.get("access_token")
        refresh = session.get("refresh_token")
        if not token or not refresh or session.get("user", {}).get("id") != user_id:
            raise DeviceSessionUnavailable("Device identity could not be verified")
        # Both tokens come from this project's Auth over TLS. Claims here only
        # check isolation; request authentication is independently verified above.
        old = jwt.decode(browser_token, options={"verify_signature": False})
        new = jwt.decode(token, options={"verify_signature": False})
        if (
            new.get("sub") != user_id
            or not new.get("session_id")
            or new["session_id"] == old.get("session_id")
        ):
            raise DeviceSessionUnavailable("Device session was not independent")
        return {
            "access_token": token,
            "refresh_token": refresh,
            "expires_at": session.get("expires_at") or int(time.time()) + session["expires_in"],
            "user": {"id": user_id, "email": user["email"]},
        }


async def revoke_device_session(tokens: dict) -> None:
    """Revoke only the newly minted, undelivered session; never the browser or other devices."""
    base = os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1"
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.post(
            base + "/logout",
            params={"scope": "local"},
            headers={"apikey": key or "", "Authorization": "Bearer " + tokens["access_token"]},
        )
        response.raise_for_status()
