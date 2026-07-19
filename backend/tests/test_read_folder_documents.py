"""Tests for the read_folder_documents MCP tool.

Hermetic: no DB. We stub get_supabase + resolve_folder + get_docs_in_subtree and
drive the request context (the contextvars the tool reads) directly.
"""

from __future__ import annotations

import pytest

import mcp_server
import services.folder_summary.repo as repo_mod


@pytest.fixture
def ctx(monkeypatch):
    """Authenticated + scoped, with supabase and folder resolution stubbed."""
    t1 = mcp_server._current_user_id.set("u1")
    t2 = mcp_server._current_scope_folder_id.set("scope-folder")
    monkeypatch.setattr(mcp_server, "get_supabase", lambda: object())
    monkeypatch.setattr(
        mcp_server,
        "resolve_focus_folder",
        lambda sb, *, scope_folder_id, user_id, focus: ("f1", "myfolder"),
    )
    yield
    mcp_server._current_user_id.reset(t1)
    mcp_server._current_scope_folder_id.reset(t2)


def _stub_docs(monkeypatch, docs):
    # The tool imports get_docs_in_subtree from this module at call time.
    monkeypatch.setattr(repo_mod, "get_docs_in_subtree", lambda sb, fid, uid: docs)


def test_not_authenticated(monkeypatch):
    tok = mcp_server._current_user_id.set(None)
    try:
        assert mcp_server.read_folder_documents().startswith("Error: Not authenticated")
    finally:
        mcp_server._current_user_id.reset(tok)


def test_empty_folder_is_a_noop(ctx, monkeypatch):
    _stub_docs(monkeypatch, [])
    out = mcp_server.read_folder_documents()
    assert "nothing to fold in" in out.lower()
    assert "myfolder" in out


def test_returns_all_files_with_headers(ctx, monkeypatch):
    _stub_docs(
        monkeypatch,
        [
            {"source_filename": "arch.md", "content": "architecture notes"},
            {"source_filename": "spec.md", "content": "the ecosystem spec"},
        ],
    )
    out = mcp_server.read_folder_documents()
    assert "2 of 2 file(s)" in out
    assert "## arch.md" in out and "architecture notes" in out
    assert "## spec.md" in out and "the ecosystem spec" in out
    assert "Truncated" not in out


def test_resolve_error_is_surfaced(ctx, monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "resolve_focus_folder",
        lambda sb, *, scope_folder_id, user_id, focus: (None, "no scope"),
    )
    assert mcp_server.read_folder_documents() == "Error: no scope"


def test_truncation_cap(ctx, monkeypatch):
    # Three docs, each ~half the cap → output is bounded and flagged truncated.
    big = "x" * (mcp_server._DOC_DUMP_CHAR_CAP // 2 + 5_000)
    _stub_docs(
        monkeypatch,
        [
            {"source_filename": "a.md", "content": big},
            {"source_filename": "b.md", "content": big},
            {"source_filename": "c.md", "content": big},
        ],
    )
    out = mcp_server.read_folder_documents()
    assert "Truncated" in out
    assert "## a.md" in out  # at least the first file survives
    # bounded to the cap plus a little header/footer overhead
    assert len(out) <= mcp_server._DOC_DUMP_CHAR_CAP + 2_000


def test_giant_first_doc_is_partially_included(ctx, monkeypatch):
    huge = "y" * (mcp_server._DOC_DUMP_CHAR_CAP + 50_000)
    _stub_docs(monkeypatch, [{"source_filename": "huge.md", "content": huge}])
    out = mcp_server.read_folder_documents()
    assert "## huge.md" in out and "Truncated" in out
    assert len(out) <= mcp_server._DOC_DUMP_CHAR_CAP + 2_000
