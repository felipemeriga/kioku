"""Tests for the read_folder_documents MCP tool.

Hermetic: no DB. We stub get_supabase + resolve_folder + the repo doc helpers,
and drive the request context (the contextvars the tool reads) directly.

Shared-context model: everything under the ROOT except the repositories
container and this repo's own subtree. In these stubs get_descendant_folder_ids
returns [fid] (each folder = just itself), so shared_ids resolves to the root
and get_docs_for_folder_ids controls the shared payload.
"""

from __future__ import annotations

import pytest

import mcp_server
import services.folder_summary.repo as repo_mod


@pytest.fixture
def ctx(monkeypatch):
    t1 = mcp_server._current_user_id.set("u1")
    t2 = mcp_server._current_scope_folder_id.set("scope-folder")
    monkeypatch.setattr(mcp_server, "get_supabase", lambda: object())
    monkeypatch.setattr(
        mcp_server,
        "resolve_focus_folder",
        lambda sb, *, scope_folder_id, user_id, focus: ("f1", "myfolder"),
    )
    monkeypatch.setattr(repo_mod, "get_descendant_folder_ids", lambda sb, fid, uid: [fid])
    monkeypatch.setattr(repo_mod, "get_root_folder_id", lambda sb, fid, uid: "root")
    monkeypatch.setattr(repo_mod, "find_child_folder_id", lambda sb, pid, name, uid: None)
    # No shared docs by default; tests opt in via _stub_shared_docs.
    monkeypatch.setattr(repo_mod, "get_docs_for_folder_ids", lambda sb, ids, uid: [])
    yield
    mcp_server._current_user_id.reset(t1)
    mcp_server._current_scope_folder_id.reset(t2)


def _stub_repo_docs(monkeypatch, docs):
    monkeypatch.setattr(repo_mod, "get_docs_in_subtree", lambda sb, fid, uid: docs)


def _stub_shared_docs(monkeypatch, docs):
    monkeypatch.setattr(repo_mod, "get_docs_for_folder_ids", lambda sb, ids, uid: docs)


def test_not_authenticated(monkeypatch):
    tok = mcp_server._current_user_id.set(None)
    try:
        assert mcp_server.read_folder_documents().startswith("Error: Not authenticated")
    finally:
        mcp_server._current_user_id.reset(tok)


def test_empty_folder_is_a_noop(ctx, monkeypatch):
    _stub_repo_docs(monkeypatch, [])
    out = mcp_server.read_folder_documents()
    assert "nothing to fold in" in out.lower()


def test_returns_repo_files_with_headers(ctx, monkeypatch):
    _stub_repo_docs(
        monkeypatch,
        [
            {"source_filename": "arch.md", "content": "architecture notes"},
            {"source_filename": "spec.md", "content": "the ecosystem spec"},
        ],
    )
    out = mcp_server.read_folder_documents()
    assert "Repo documents in 'myfolder' (2 file(s))" in out
    assert "## arch.md" in out and "architecture notes" in out
    assert "## spec.md" in out and "the ecosystem spec" in out
    assert "Truncated" not in out
    # No shared docs → no shared-context section.
    assert "Shared context from the workspace" not in out


def test_includes_shared_workspace_docs(ctx, monkeypatch):
    _stub_repo_docs(monkeypatch, [{"source_filename": "repo.md", "content": "repo doc"}])
    _stub_shared_docs(
        monkeypatch,
        [{"source_filename": "company-mdr.md", "content": "company-wide context"}],
    )
    out = mcp_server.read_folder_documents()
    assert "## repo.md" in out and "repo doc" in out
    assert "Shared context from the workspace (1 file(s))" in out
    assert "## company-mdr.md" in out and "company-wide context" in out


def test_shared_docs_only_still_returns(ctx, monkeypatch):
    # Repo has no docs but the workspace root does → still fold in the context.
    _stub_repo_docs(monkeypatch, [])
    _stub_shared_docs(monkeypatch, [{"source_filename": "root.md", "content": "root doc"}])
    out = mcp_server.read_folder_documents()
    assert "nothing to fold in" not in out.lower()
    assert "Shared context from the workspace" in out and "## root.md" in out


def test_resolve_error_is_surfaced(ctx, monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "resolve_focus_folder",
        lambda sb, *, scope_folder_id, user_id, focus: (None, "no scope"),
    )
    assert mcp_server.read_folder_documents() == "Error: no scope"


def test_truncation_cap(ctx, monkeypatch):
    big = "x" * (mcp_server._DOC_DUMP_CHAR_CAP // 2 + 5_000)
    _stub_repo_docs(
        monkeypatch,
        [
            {"source_filename": "a.md", "content": big},
            {"source_filename": "b.md", "content": big},
            {"source_filename": "c.md", "content": big},
        ],
    )
    out = mcp_server.read_folder_documents()
    assert "Truncated" in out
    assert "## a.md" in out
    assert len(out) <= mcp_server._DOC_DUMP_CHAR_CAP + 2_000


def test_giant_first_doc_is_partially_included(ctx, monkeypatch):
    huge = "y" * (mcp_server._DOC_DUMP_CHAR_CAP + 50_000)
    _stub_repo_docs(monkeypatch, [{"source_filename": "huge.md", "content": huge}])
    out = mcp_server.read_folder_documents()
    assert "## huge.md" in out and "Truncated" in out
    assert len(out) <= mcp_server._DOC_DUMP_CHAR_CAP + 2_000
