import os
import threading
from functools import lru_cache

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

_thread_local = threading.local()


def _make_httpx_client() -> httpx.Client:
    """Create an httpx client with retry-capable transport.

    Uses HTTP/1.1 and retries to avoid stale HTTP/2 connection errors
    (RemoteProtocolError: Server disconnected) that occur when the server
    closes idle pooled connections.

    The default httpx read timeout is 5s, which is too aggressive for
    inserts into the HNSW-indexed `code_chunks` table under load: a burst
    of vector inserts (e.g. a first full code index) legitimately takes
    longer than 5s and was failing with ReadTimeout. Give all Supabase
    calls a generous 60s read/write budget (connect stays tight).
    """
    transport = httpx.HTTPTransport(retries=3, http2=False)
    timeout = httpx.Timeout(60.0, connect=10.0)
    return httpx.Client(transport=transport, timeout=timeout)


def _create_supabase_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    options = SyncClientOptions(httpx_client=_make_httpx_client())
    return create_client(url, key, options)


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Return the cached Supabase client for the main thread / request handlers."""
    return _create_supabase_client()


def get_supabase_thread_safe() -> Client:
    """Return a per-thread Supabase client.

    Background threads (e.g. asyncio.to_thread for ingestion) need their
    own httpx connection pool — the cached singleton is not thread-safe.
    """
    client = getattr(_thread_local, "client", None)
    if client is None:
        client = _create_supabase_client()
        _thread_local.client = client
    return client
