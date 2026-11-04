"""Real PostgreSQL CI runs the shipped migration, including private table grants."""

import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from tsukai.store import Store
from tsukai.tables import metadata


@pytest.fixture
async def store(tmp_path):
    url = os.getenv("TSUKAI_TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/fixture.db")
    value = Store(url, str(tmp_path / "workspaces"))
    if value.engine.dialect.name == "postgresql":
        if value.engine.url.database != "tsukai_fixture":
            raise RuntimeError("PostgreSQL tests require isolated database tsukai_fixture")
        admin_url = os.environ["TSUKAI_TEST_ADMIN_DATABASE_URL"]
        admin = create_async_engine(admin_url)
        async with admin.begin() as conn:
            await conn.run_sync(metadata.drop_all)
            migration = (
                Path(__file__).parents[2]
                / "supabase/migrations/20261104090000_tsukai_execution.sql"
            )
            lifecycle = migration.parent / "20261104110000_tsukai_execution_lifecycle.sql"
            migration_text = migration.read_text() + "\n" + lifecycle.read_text()
            script = "\n".join(
                line for line in migration_text.splitlines() if not line.lstrip().startswith("--")
            )
            for statement in script.split(";"):
                if statement.strip():
                    await conn.exec_driver_sql(statement)
            # Runtime URL uses a separate restricted LOGIN, never the migration owner.
            role = value.engine.url.username
            if role != "tsukai_fixture_runtime":
                raise RuntimeError("PostgreSQL tests require restricted runtime role")
            await conn.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            for table in metadata.sorted_tables:
                name = table.name
                await conn.exec_driver_sql(
                    f'GRANT SELECT,INSERT,UPDATE,DELETE ON public.{name} TO "{role}"'
                )
                await conn.exec_driver_sql(
                    f"CREATE POLICY tsukai_runtime ON public.{name} FOR ALL "
                    f'TO "{role}" USING (true) WITH CHECK (true)'
                )
            await conn.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS public.tsukai_fixture_domain_secret (id integer)"
            )
        await admin.dispose()
    else:
        await value.create_test_schema()
    yield value
    await value.engine.dispose()
