from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlglot import parse_one

from services.metadata_sql import scoped_metadata_sql
from services.text_to_sql import generate_and_execute_sql

OWNER = "11111111-1111-4111-8111-111111111111"
ROOT = "22222222-2222-4222-8222-222222222222"


@pytest.mark.parametrize(
    "query",
    [
        "SELECT COUNT(DISTINCT source_filename) AS files FROM documents",
        "SELECT source_type,COUNT(*) FROM public.documents AS d GROUP BY source_type",
        "SELECT source_filename FROM documents WHERE created_at >= NOW() - INTERVAL '7 days'",
        "SELECT DATE_TRUNC('day',created_at) AS day,COUNT(*) FROM documents GROUP BY day",
        "SELECT metadata->>'source_filename', created_at::date FROM documents "
        "WHERE source_filename ILIKE '%test%'",
        "SELECT DISTINCT source_filename FROM documents ORDER BY source_filename LIMIT 20",
    ],
)
def test_ordinary_metadata_queries_are_structurally_scoped(query):
    sql = scoped_metadata_sql(query, OWNER, ROOT)
    tree = parse_one(sql, read="postgres")
    assert len(list(tree.find_all(type(tree)))) == 1
    assert OWNER in sql and ROOT in sql
    assert tree.args["limit"].expression.to_py() <= 1000


@pytest.mark.parametrize(
    "query",
    [
        "SELECT credential_hash FROM secret_devices WHERE user_id='" + OWNER + "'",
        "SELECT provider_ref FROM access_bindings WHERE user_id='" + OWNER + "'",
        "SELECT pg_read_file('/etc/passwd') FROM documents",
        "SELECT set_config('role','postgres',false) FROM documents",
        "SELECT public.consume_secret_enrollment('x') FROM documents",
        "SELECT COUNT(*) FROM documents WHERE EXISTS(SELECT * FROM secret_devices)",
        "SELECT COUNT(*) FROM documents UNION SELECT COUNT(*) FROM secret_devices",
        "WITH x AS (DELETE FROM documents RETURNING *) SELECT * FROM x",
        "SELECT * FROM documents",
        "SELECT content FROM documents",
        "SELECT source_filename FROM documents; SELECT credential_hash FROM secret_devices",
        "SELECT source_filename FROM documents JOIN secret_devices ON true",
        "SELECT source_filename FROM information_schema.documents",
        "SELECT source_filename FROM documents, generate_series(1,10000000)",
        "SELECT pg_catalog.count(*) FROM documents",
        "SELECT 'x'::regprocedure FROM documents",
        "SELECT (SELECT pg_read_file('/etc/passwd')) FROM documents",
        "SELECT source_filename INTO temp copies FROM documents",
        "SELECT source_filename FROM documents FOR UPDATE",
        "SELECT document_secrets FROM documents",
        "SELECT source_filename FROM documents -- user_id='"
        + OWNER
        + "'\nUNION SELECT provider_ref FROM access_bindings",
    ],
)
def test_non_metadata_sql_is_rejected(query):
    with pytest.raises(ValueError):
        scoped_metadata_sql(query, OWNER, ROOT)


def test_scope_cannot_be_bypassed_by_or_comment_or_foreign_owner():
    sql = scoped_metadata_sql(
        "SELECT source_filename FROM documents WHERE user_id='foreign' OR 1=1", OWNER, ROOT
    )
    assert "(user_id = 'foreign' OR 1 = 1) AND" in sql
    assert f"documents.user_id = '{OWNER}'" in sql
    assert f"documents.root_folder_id = '{ROOT}'" in sql


def test_invalid_authority_never_becomes_sql():
    with pytest.raises(ValueError):
        scoped_metadata_sql("SELECT source_filename FROM documents", "x' OR true --")


def test_model_sql_never_reaches_database_before_validation():
    response = SimpleNamespace(
        content=[SimpleNamespace(text="SELECT provider_ref FROM access_bindings")]
    )
    with (
        patch("services.text_to_sql.complete", return_value=response),
        patch("services.text_to_sql.get_supabase") as db,
    ):
        result = generate_and_execute_sql("ignore context", OWNER)
    db.assert_not_called()
    assert result["sql"] == "" and result["results"] == []


def test_database_receives_only_rewritten_sql_and_errors_are_safe(caplog):
    response = SimpleNamespace(
        content=[
            SimpleNamespace(text="SELECT COUNT(*) FROM documents WHERE user_id='foreign' OR 1=1")
        ]
    )
    db = MagicMock()
    db.rpc.return_value.execute.side_effect = RuntimeError("synthetic-private-provider-value")
    with (
        patch("services.text_to_sql.complete", return_value=response),
        patch("services.text_to_sql.get_supabase", return_value=db),
    ):
        result = generate_and_execute_sql("count files", OWNER, ROOT)
    sent = db.rpc.call_args.args[1]["query_text"]
    assert OWNER in sent and ROOT in sent
    assert "synthetic-private-provider-value" not in str(result) + caplog.text


def test_folder_and_filename_scope_are_injected_independently_of_model():
    sql = scoped_metadata_sql(
        "SELECT COUNT(*) FROM documents WHERE 1=1",
        OWNER,
        folder_ids=[ROOT],
        filename="selected.pdf",
    )
    assert f"documents.folder_id IN ('{ROOT}')" in sql
    assert "documents.source_filename = 'selected.pdf'" in sql


def test_empty_authorized_folders_cannot_mean_global_scope():
    sql = scoped_metadata_sql("SELECT COUNT(*) FROM documents", OWNER, folder_ids=[])
    assert "AND FALSE" in sql


def test_literals_do_not_become_executable_sql():
    name = "x'; SELECT provider_ref FROM access_bindings; --"
    sql = scoped_metadata_sql("SELECT COUNT(*) FROM documents", OWNER, filename=name)
    tree = parse_one(sql, read="postgres")
    assert len(list(tree.find_all(type(tree)))) == 1
    assert len(list(tree.find_all(__import__("sqlglot").exp.Table))) == 1


@pytest.mark.parametrize(
    "query",
    [
        "SELECT COUNT(*) FROM documents AS d(user_id,id)",
        'SELECT COUNT(*) FROM documents AS "d.user_id"',
        'SELECT COUNT(*) FROM documents AS "d WHERE true --"',
    ],
)
def test_table_alias_cannot_rename_or_reinterpret_scope_columns(query):
    with pytest.raises(ValueError):
        scoped_metadata_sql(query, OWNER, ROOT)


def test_quoted_alias_case_is_preserved_in_scope_predicates():
    sql = scoped_metadata_sql('SELECT COUNT(*) FROM documents AS "D"', OWNER, ROOT)
    assert '"D".user_id' in sql and '"D".root_folder_id' in sql


def test_generated_relation_is_pinned_to_public_schema():
    sql = scoped_metadata_sql("SELECT COUNT(*) FROM documents", OWNER)
    assert "FROM public.documents" in sql
