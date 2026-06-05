"""JWT validation for incoming requests.

Fetches JWKS lazily from the configured Supabase project (the URL in
SUPABASE_URL). This works for both prod and local development — point
SUPABASE_URL at http://127.0.0.1:54321 and the local Supabase stack's
JWKS endpoint will be used automatically. No hardcoded keys.
"""

import os
import threading
import time

import httpx
import jwt
from fastapi import HTTPException, Request

_JWKS_CACHE: jwt.PyJWKSet | None = None
_JWKS_FETCHED_AT: float = 0.0
_JWKS_TTL_S: float = 3600.0  # 1 hour. Supabase rotates rarely; this is plenty.
_JWKS_LOCK = threading.Lock()


def _fetch_jwks() -> dict:
    """Fetch JWKS from the configured Supabase Auth well-known endpoint."""
    base = os.environ.get("SUPABASE_URL")
    if not base:
        raise RuntimeError("SUPABASE_URL is not set; cannot fetch JWKS for auth")
    url = base.rstrip("/") + "/auth/v1/.well-known/jwks.json"
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    return response.json()


def _get_jwks() -> jwt.PyJWKSet:
    """Return cached JWKS, refreshing if past TTL. Thread-safe."""
    global _JWKS_CACHE, _JWKS_FETCHED_AT
    now = time.time()
    if _JWKS_CACHE is None or now - _JWKS_FETCHED_AT > _JWKS_TTL_S:
        with _JWKS_LOCK:
            # Re-check under the lock — another thread may have refreshed.
            if _JWKS_CACHE is None or time.time() - _JWKS_FETCHED_AT > _JWKS_TTL_S:
                _JWKS_CACHE = jwt.PyJWKSet.from_dict(_fetch_jwks())
                _JWKS_FETCHED_AT = time.time()
    return _JWKS_CACHE


def _get_signing_key(token: str) -> tuple[jwt.PyJWK, str]:
    """Find the JWK that signed `token`. Returns (key, algorithm)."""
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    jwks = _get_jwks()
    for key in jwks.keys:
        if key.key_id == kid:
            alg = (key._jwk_data or {}).get("alg") or header.get("alg") or "ES256"
            return key, alg
    raise jwt.InvalidTokenError(f"No matching key found for kid: {kid}")


async def get_current_user(request: Request) -> str:
    """Extract and validate Supabase JWT. Returns user_id."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = auth_header.split(" ", 1)[1]

    try:
        signing_key, alg = _get_signing_key(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=[alg],
            audience="authenticated",
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: no sub claim")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
