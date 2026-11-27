"""Bridge the frozen Kioku services to a disposable PostgreSQL audit database."""

import hashlib
import io
import json
import os
import secrets
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psycopg
from psycopg import ClientCursor, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from storage3.exceptions import StorageApiError

from services.agent_evidence import EvidenceStore
from services.agent_evidence_jobs import process_session
from services.agent_evidence_models import BatchRequest, event_id, sha256

MIGRATION_DIRECTORY = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
AUDIT_DB = "kioku_memory_audit"
MIGRATIONS = (
    "20261029090000_agent_journals",
    "20261105090000_agent_evidence",
    "20261105100000_agent_evidence_empty_attachments",
    "20261105103000_agent_evidence_rpc_privileges",
    "20261105120000_agent_history_calendar",
    "20261105123000_agent_history_bounded_children",
    "20261105130000_agent_history_search",
    "20261106233000_history_session_prefix",
    "20261109090000_agent_memory_recall",
    "20261109110000_memory_relevance",
    "20261109120000_memory_latest_order",
    "20261109130000_memory_escape_tokens",
    "20261109150000_memory_overview",
    "20261109221000_memory_overview_index_coverage",
    "20261113140000_period_reports",
    "20261113220000_chronological_report_backfill",
    "20261119120000_memory_search_custom_plan",
)

# These unrelated platform tables keep their audit-required columns. The archive,
# search, journal and report tables and functions all come from the frozen migrations.
PLATFORM = """
CREATE ROLE anon;
CREATE ROLE authenticated;
CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA extensions;
CREATE SCHEMA auth;
CREATE TABLE auth.users (id uuid PRIMARY KEY);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS
$$ SELECT nullif(current_setting('request.jwt.claim.sub', true),'')::uuid $$;
GRANT USAGE ON SCHEMA auth TO authenticated;
CREATE SCHEMA storage;
CREATE TABLE storage.buckets (
 id text PRIMARY KEY, name text, public boolean, file_size_limit bigint,
 allowed_mime_types text[]
);
CREATE TABLE public.folders (
 id uuid PRIMARY KEY, user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
 name text NOT NULL, kind text NOT NULL, parent_id uuid REFERENCES public.folders(id)
);
CREATE TABLE public.api_keys (
 key_hash text PRIMARY KEY, user_id uuid NOT NULL, scope_folder_id uuid NOT NULL
);
CREATE TABLE public.watched_repos (user_id uuid,folder_id uuid);
CREATE TABLE public.maintenance_preparations (
 id uuid PRIMARY KEY, user_id uuid, folder_id uuid,
 operation text CHECK(operation IN ('activity')), execution_job_id text,
 publication jsonb, snapshot jsonb, request jsonb
);
CREATE TABLE public.maintenance_runner_ack_outbox (
 preparation_id uuid PRIMARY KEY, user_id uuid, folder_id uuid, job_id text
);
GRANT SELECT ON public.folders, public.api_keys TO service_role;
"""


def comma(items):
    return sql.SQL(", ").join(items)


def column(name):
    base, separator, key = name.partition("->>")
    identifier = sql.Identifier(base)
    if separator:
        return sql.SQL("{}->>{}").format(identifier, sql.Literal(key))
    return identifier


def adapt(value):
    return Jsonb(value) if isinstance(value, dict) else value


class Table:
    """Small adapter for the fluent expressions actually used by the audit paths."""

    def __init__(self, lab, name):
        self.lab = lab
        self.name = sql.Identifier("public", name)
        self.projection = sql.SQL("*")
        self.filters = []
        self.parameters = []
        self.ordering = []
        self.row_limit = None
        self.expect_single = False
        self.changes = None

    def select(self, names):
        self.projection = sql.SQL("*") if names == "*" else comma(map(column, names.split(",")))
        return self

    def update(self, changes):
        self.changes = changes
        return self

    def filter(self, name, operator, value):
        self.filters.append(sql.SQL("{} " + operator + " %s").format(column(name)))
        self.parameters.append(value)
        return self

    def eq(self, name, value):
        return self.filter(name, "=", value)

    def gt(self, name, value):
        return self.filter(name, ">", value)

    def gte(self, name, value):
        return self.filter(name, ">=", value)

    def lt(self, name, value):
        return self.filter(name, "<", value)

    def lte(self, name, value):
        return self.filter(name, "<=", value)

    def in_(self, name, values):
        if values:
            self.filters.append(
                sql.SQL("{} IN ({})").format(column(name), comma(sql.Placeholder() for _ in values))
            )
            self.parameters.extend(values)
        else:
            self.filters.append(sql.SQL("false"))
        return self

    @property
    def not_(self):
        return SimpleNamespace(is_=self.is_not)

    def is_(self, name, value, negate=False):
        if value != "null":
            raise ValueError("The audit bridge only supports null checks")
        self.filters.append(
            sql.SQL("{} IS " + ("NOT " if negate else "") + "NULL").format(column(name))
        )
        return self

    def is_not(self, name, value):
        return self.is_(name, value, negate=True)

    def order(self, name, desc=False):
        self.ordering.append(sql.SQL("{} DESC" if desc else "{} ASC").format(column(name)))
        return self

    def limit(self, count):
        self.row_limit = count
        return self

    def single(self):
        self.expect_single = True
        return self

    def execute(self):
        where = sql.SQL("")
        if self.filters:
            where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(self.filters)
        if self.changes is None:
            statement = sql.SQL("SELECT {} FROM {}").format(self.projection, self.name)
            statement += where
            params = list(self.parameters)
            if self.ordering:
                statement += sql.SQL(" ORDER BY ") + comma(self.ordering)
            if self.row_limit is not None:
                statement += sql.SQL(" LIMIT %s")
                params.append(self.row_limit)
            # PostgreSQL uses the same JSON primitives emitted by PostgREST.
            statement = sql.SQL("SELECT to_jsonb(row) AS data FROM ({}) row").format(statement)
        else:
            if not self.filters or self.ordering or self.row_limit is not None:
                raise ValueError("The audit bridge requires a scoped UPDATE")
            fields = comma(sql.SQL("{} = %s").format(column(key)) for key in self.changes)
            update = sql.SQL("UPDATE {} SET {}").format(self.name, fields)
            update += where + sql.SQL(" RETURNING *")
            statement = sql.SQL(
                "WITH changed AS ({}) SELECT to_jsonb(changed) AS data FROM changed"
            ).format(update)
            params = [adapt(value) for value in self.changes.values()] + self.parameters
        rows = [row["data"] for row in self.lab.pg.execute(statement, params)]
        if self.expect_single:
            if len(rows) != 1:
                raise ValueError("The audit query did not return exactly one row")
            return SimpleNamespace(data=rows[0])
        return SimpleNamespace(data=rows)


class Bucket:
    def __init__(self):
        self.objects = {}
        self.downloaded_bytes = 0
        self.download_count = 0

    def upload(self, path, body, options):
        if path in self.objects and options.get("upsert", "false") != "true":
            raise StorageApiError("Already stored", "409", "409")
        self.objects[path] = body if isinstance(body, bytes) else body.read()

    def download(self, path):
        if path not in self.objects:
            raise StorageApiError("Missing fixture", "404", "404")
        payload = self.objects[path]
        self.download_count += 1
        self.downloaded_bytes += len(payload)
        return payload

    def remove(self, paths):
        for path in paths:
            self.objects.pop(path, None)


class Lab:
    """Materials and defaults are isolated from all configured Supabase services."""

    def __init__(self, connection_file):
        path = Path(connection_file)
        if path.stat().st_mode & 0o077:
            raise ValueError("Lab connection file must be private")
        config = json.loads(path.read_text())
        if config["host"] != "127.0.0.1" or config["dbname"] != AUDIT_DB:
            raise ValueError("The audit requires a loopback-only disposable database")
        self.pg = psycopg.connect(
            host=config["host"],
            port=config["port"],
            dbname=config["dbname"],
            user=config["user"],
            password=config["password"],
            connect_timeout=5,
            autocommit=True,
            cursor_factory=ClientCursor,
            row_factory=dict_row,
        )
        if (
            self.pg.execute("SELECT to_regnamespace('kioku_audit_guard') AS guard").fetchone()[
                "guard"
            ]
            is None
        ):
            self.pg.close()
            raise ValueError("The disposable database is missing its audit guard")
        self.buckets = {}
        self.storage = SimpleNamespace(from_=self.bucket)
        self._service_key = secrets.token_hex(32)

    def initialize(self):
        if (
            self.pg.execute(
                "SELECT to_regclass('public.agent_evidence_sessions') AS table"
            ).fetchone()["table"]
            is not None
        ):
            raise RuntimeError("The disposable database already has an audit schema")
        self.pg.execute(PLATFORM)
        for migration in MIGRATIONS:
            self.pg.execute((MIGRATION_DIRECTORY / (migration + ".sql")).read_text())

    def close(self):
        self.pg.close()

    def table(self, name):
        return Table(self, name)

    def rpc(self, name, args):
        statement = sql.SQL("SELECT {}({}) AS data").format(
            sql.Identifier("public", name),
            comma(sql.SQL("{} => %s").format(sql.Identifier(key)) for key in args),
        )

        def execute():
            parameters = [
                Jsonb(value)
                if isinstance(value, dict) or key in {"p_events", "p_chunks", "p_entries"}
                else value
                for key, value in args.items()
            ]
            try:
                data = self.pg.execute(statement, parameters).fetchone()["data"]
            except psycopg.Error as exc:
                # The production RPC wrapper inspects PostgREST's SQLSTATE property.
                exc.code = exc.sqlstate
                raise
            return SimpleNamespace(data=data)

        return SimpleNamespace(execute=execute)

    def bucket(self, name):
        if name not in self.buckets:
            self.buckets[name] = Bucket()
        return self.buckets[name]

    def create_owner(self, owner):
        self.pg.execute("INSERT INTO auth.users (id) VALUES (%s) ON CONFLICT DO NOTHING", [owner])

    def create_folder(self, folder, owner, name, parent=None):
        self.pg.execute(
            "INSERT INTO folders (id,user_id,name,kind,parent_id) VALUES (%s,%s,%s,%s,%s)",
            [folder, owner, name, "repo" if parent else "project", parent],
        )

    def create_api_key(self, owner, scope):
        value = secrets.token_hex(32)
        self.pg.execute(
            "INSERT INTO api_keys VALUES (%s,%s,%s)",
            [hashlib.sha256(value.encode()).hexdigest(), owner, scope],
        )
        return value

    @contextmanager
    def service_role(self):
        self.pg.execute("SET ROLE service_role")
        try:
            yield
        finally:
            self.pg.execute("RESET ROLE")

    @contextmanager
    def tools(self, owner, scope):
        # Import with a local dummy signing secret and dotenv disabled.
        with patch.dict(
            os.environ,
            {
                "SUPABASE_SERVICE_KEY": self._service_key,
                "PYTHON_DOTENV_DISABLED": "1",
            },
        ):
            import mcp_server

            with (
                patch.object(mcp_server, "get_supabase", return_value=self),
                patch.object(mcp_server, "get_supabase_thread_safe", return_value=self),
                self.service_role(),
            ):
                token_user = mcp_server._current_user_id.set(owner)
                token_scope = mcp_server._current_scope_folder_id.set(scope)
                try:
                    yield mcp_server
                finally:
                    mcp_server._current_user_id.reset(token_user)
                    mcp_server._current_scope_folder_id.reset(token_scope)

    def capture(
        self,
        owner,
        folder,
        native,
        records,
        *,
        agent="codex",
        producer="lab",
        parent=None,
        root=None,
        attachments=None,
        index=True,
    ):
        store = EvidenceStore(self, owner, folder)
        previous = self.pg.execute(
            "SELECT manifest_revision, manifest_json FROM agent_evidence_sessions "
            "WHERE user_id=%s AND folder_id=%s AND agent=%s AND native_session_id=%s",
            [owner, folder, agent, native],
        ).fetchone()
        prior_segments = previous["manifest_json"]["segments"] if previous else []
        stream = "source"
        first_record = 1 + sum(item["record_count"] for item in prior_segments)
        source_start = sum(item["byte_length"] for item in prior_segments)
        last_record = first_record + len(records) - 1
        raw = b"".join(
            (json.dumps(record, ensure_ascii=False) + "\n").encode() for record in records
        )
        payloads = {f"segment-{first_record}": raw}
        descriptors = [
            {
                "id": f"segment-{first_record}",
                "kind": "segment",
                "stream_id": stream,
                "generation": 1,
                "first_record": first_record,
                "last_record": last_record,
                "source_start": source_start,
                "source_end": source_start + len(raw),
                "sha256": sha256(raw),
                "byte_length": len(raw),
            }
        ]
        for position, (label, data) in enumerate((attachments or {}).items()):
            object_id = f"attachment-{first_record}-{position}"
            payloads[object_id] = data
            descriptors.append(
                {
                    "id": object_id,
                    "kind": "attachment",
                    "stream_id": stream,
                    "generation": 1,
                    "sha256": sha256(data),
                    "byte_length": len(data),
                    "original_name": label,
                    "source_event_id": event_id(folder, agent, native, stream, 1, first_record),
                }
            )
        batch = sha256(f"{owner}/{folder}/{agent}/{native}/{first_record}".encode())
        request = BatchRequest(
            folder_id=folder,
            agent=agent,
            native_session_id=native,
            producer_id=producer,
            native_parent_session_id=parent,
            native_root_session_id=root,
            batch_id=batch,
            base_revision=previous["manifest_revision"] if previous else 0,
            objects=descriptors,
        )
        with self.service_role():
            receipt = store.prepare(request)
            for object_id in receipt["missing_objects"]:
                payload = payloads[object_id]
                store.upload(batch, object_id, io.BytesIO(payload), sha256(payload), len(payload))
            store.commit(batch)
            if index:
                process_session(
                    self, {"user_id": owner, "folder_id": folder, "id": receipt["session_id"]}
                )
        anchor_ids = [
            event_id(folder, agent, native, stream, 1, number)
            for number in range(first_record, last_record + 1)
        ]
        return receipt["session_id"], anchor_ids
