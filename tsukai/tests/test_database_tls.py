"""Verify-full uses system trust without home-directory certificate provisioning."""

import ssl

import pytest

from tsukai.store import Store


@pytest.mark.parametrize(
    "query", ["ssl=verify-full", "sslmode=verify-full", "ssl=verify-full&sslmode=verify-full"]
)
async def test_verify_full_uses_verified_system_context_and_bounded_pool(monkeypatch, query):
    captured = {}
    sentinel = object()

    def engine(url, **options):
        captured.update(url=url, options=options)
        return sentinel

    monkeypatch.setattr("tsukai.store.create_async_engine", engine)
    store = Store(
        "postgresql+asyncpg://fixture:fixture@db.example/tsukai_fixture?"
        + query
        + "&prepared_statement_cache_size=0"
    )
    assert store.engine is sentinel
    context = captured["options"]["connect_args"]["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True and context.verify_mode == ssl.CERT_REQUIRED
    assert "ssl" not in captured["url"].query and "sslmode" not in captured["url"].query
    assert captured["url"].query["prepared_statement_cache_size"] == "0"
    assert captured["options"]["pool_size"] == 4
    assert captured["options"]["max_overflow"] == 0
    assert captured["options"]["pool_timeout"] == 5


@pytest.mark.parametrize(
    "query", ["ssl=require&sslmode=verify-full", "ssl=verify-full&ssl=require"]
)
def test_conflicting_or_repeated_tls_modes_fail_closed(query):
    with pytest.raises(ValueError, match="conflicting PostgreSQL TLS modes"):
        Store("postgresql+asyncpg://fixture:fixture@db.example/tsukai_fixture?" + query)


async def test_sqlite_fixture_keeps_driver_options_unchanged(monkeypatch):
    captured = {}

    def engine(url, **options):
        captured.update(options)
        return object()

    monkeypatch.setattr("tsukai.store.create_async_engine", engine)
    Store("sqlite+aiosqlite://")
    assert captured == {"pool_pre_ping": True}


@pytest.mark.parametrize("source", ["argument", "environment", "url"])
async def test_explicit_public_ca_is_added_without_weakening_system_trust(
    monkeypatch, tmp_path, source
):
    captured = {}
    context = ssl.create_default_context()
    roots = context.get_ca_certs(binary_form=True)
    assert roots
    ca = tmp_path / "public-ca.crt"
    ca.write_text(ssl.DER_cert_to_PEM_cert(roots[0]))

    def engine(url, **options):
        captured.update(url=url, options=options)
        return object()

    monkeypatch.setattr("tsukai.store.create_async_engine", engine)
    url = "postgresql+asyncpg://fixture:fixture@db.example/tsukai_fixture?ssl=verify-full"
    options = {}
    if source == "argument":
        options["database_ca_file"] = str(ca)
    elif source == "environment":
        monkeypatch.setenv("TSUKAI_DATABASE_CA_FILE", str(ca))
    else:
        from sqlalchemy.engine import make_url

        url = make_url(url).update_query_dict({"sslrootcert": str(ca)})
    Store(url, **options)
    ctx = captured["options"]["connect_args"]["ssl"]
    assert ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
    assert set(roots).issubset(ctx.get_ca_certs(binary_form=True))
    assert "sslrootcert" not in captured["url"].query


def test_configured_ca_cannot_downgrade_tls_or_fall_back_if_missing(tmp_path):
    ca = str(tmp_path / "missing-ca.crt")
    with pytest.raises(ValueError, match="requires verify-full"):
        Store(
            "postgresql+asyncpg://fixture:fixture@db.example/tsukai_fixture?ssl=require",
            database_ca_file=ca,
        )
    with pytest.raises(FileNotFoundError):
        Store(
            "postgresql+asyncpg://fixture:fixture@db.example/tsukai_fixture?ssl=verify-full",
            database_ca_file=ca,
        )


def test_conflicting_ca_sources_fail_closed(monkeypatch):
    monkeypatch.setenv("TSUKAI_DATABASE_CA_FILE", "/first/ca.crt")
    with pytest.raises(ValueError, match="conflicting PostgreSQL CA files"):
        Store(
            "postgresql+asyncpg://fixture:fixture@db.example/tsukai_fixture?ssl=verify-full",
            database_ca_file="/second/ca.crt",
        )
