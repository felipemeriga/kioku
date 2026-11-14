"""Infisical adapter. Only opaque references and safe errors cross this boundary."""

import json
import os
import re
from urllib.parse import urlsplit

import httpx


class ProviderUnavailable(Exception):
    def __init__(self):
        super().__init__("Credential provider unavailable")


class InfisicalProvider:
    def __init__(self):
        self.origin = os.getenv("KIOKU_VAULT_URL", "").rstrip("/")
        self.project = os.getenv("KIOKU_VAULT_PROJECT_ID", "")
        self.environment = os.getenv("KIOKU_VAULT_ENVIRONMENT", "prod")
        self.client_id = os.getenv("KIOKU_VAULT_CLIENT_ID", "")
        self.client_secret = os.getenv("KIOKU_VAULT_CLIENT_SECRET", "")
        parsed = urlsplit(self.origin)
        internal_http = os.getenv("KIOKU_VAULT_ALLOW_INTERNAL_HTTP") == "true"
        if self.origin and (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path
            or (parsed.scheme != "https" and not internal_http)
        ):
            raise ProviderUnavailable()

    @property
    def configured(self):
        return bool(self.origin and self.project and self.client_id and self.client_secret)

    def _client(self):
        if not self.configured:
            raise ProviderUnavailable()
        return httpx.Client(
            base_url=self.origin,
            timeout=httpx.Timeout(15, connect=5),
            follow_redirects=False,
            trust_env=False,
        )

    def _token(self, client):
        response = client.post(
            "/api/v1/auth/universal-auth/login",
            json={"clientId": self.client_id, "clientSecret": self.client_secret},
        )
        if response.status_code != 200:
            raise ProviderUnavailable()
        token = response.json().get("accessToken")
        if not isinstance(token, str) or not token:
            raise ProviderUnavailable()
        return token

    def _params(self):
        return {
            "workspaceId": self.project,
            "environment": self.environment,
            "secretPath": "/",
            "type": "shared",
        }

    @staticmethod
    def _reference(ref):
        if not re.fullmatch(r"KIOKU_[a-f0-9]{32}_[a-f0-9]{32}_[a-f0-9]{32}", ref):
            raise ProviderUnavailable()
        return ref

    def write(self, ref, values):
        ref = self._reference(ref)
        try:
            with self._client() as client:
                auth = {"Authorization": "Bearer " + self._token(client)}
                # Immutable per-operation object: retry after uncertain response reuses the
                # existing value; never overwrites a completed operation with new input.
                existing = client.get(
                    "/api/v3/secrets/raw/" + ref, params=self._params(), headers=auth
                )
                if existing.status_code == 200:
                    return
                if existing.status_code != 404:
                    raise ProviderUnavailable()
                response = client.post(
                    "/api/v3/secrets/raw/" + ref,
                    json={**self._params(), "secretValue": json.dumps(values, ensure_ascii=False)},
                    headers=auth,
                )
                if response.status_code not in {200, 201}:
                    raise ProviderUnavailable()
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ProviderUnavailable() from None

    def read(self, ref):
        ref = self._reference(ref)
        try:
            with self._client() as client:
                response = client.get(
                    "/api/v3/secrets/raw/" + ref,
                    params=self._params(),
                    headers={"Authorization": "Bearer " + self._token(client)},
                )
                if response.status_code != 200:
                    raise ProviderUnavailable()
                value = json.loads(response.json()["secret"]["secretValue"])
                if (
                    not isinstance(value, dict)
                    or not value
                    or len(value) > 32
                    or any(
                        not isinstance(k, str)
                        or not isinstance(v, str)
                        or not v
                        or "\x00" in v
                        or len(v.encode()) > 65536
                        for k, v in value.items()
                    )
                    or sum(len(v.encode()) for v in value.values()) > 262144
                ):
                    raise ProviderUnavailable()
                return value
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ProviderUnavailable() from None
