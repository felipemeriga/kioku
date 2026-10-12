"""text-to-SQL must enforce the caller's user_id filter structurally, not just
via the generation prompt (the RPC bypasses RLS)."""

from services.text_to_sql import _is_user_scoped


class TestIsUserScoped:
    def test_accepts_query_scoped_to_caller(self):
        assert _is_user_scoped("SELECT source_filename FROM documents WHERE user_id = 'u1'", "u1")

    def test_accepts_flexible_whitespace(self):
        assert _is_user_scoped("select * from documents where user_id='u1'", "u1")

    def test_rejects_missing_user_filter(self):
        assert not _is_user_scoped("SELECT * FROM documents", "u1")

    def test_rejects_other_users_id(self):
        assert not _is_user_scoped("SELECT * FROM documents WHERE user_id = 'u2'", "u1")
