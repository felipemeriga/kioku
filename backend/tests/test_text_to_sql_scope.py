"""Document scope is imposed by the backend, never inferred from model text."""

from services.metadata_sql import scoped_metadata_sql

OWNER = "11111111-1111-4111-8111-111111111111"
ROOT = "22222222-2222-4222-8222-222222222222"


def test_missing_user_filter_is_added():
    assert OWNER in scoped_metadata_sql("SELECT source_filename FROM documents", OWNER)


def test_foreign_user_predicate_cannot_expand_caller_scope():
    sql = scoped_metadata_sql(
        "SELECT source_filename FROM documents WHERE user_id='foreign'", OWNER
    )
    assert "AND documents.user_id = '" + OWNER + "'" in sql


def test_root_filter_is_enforced_even_when_model_omits_it():
    sql = scoped_metadata_sql("SELECT COUNT(*) FROM documents", OWNER, ROOT)
    assert "documents.root_folder_id = '" + ROOT + "'" in sql
