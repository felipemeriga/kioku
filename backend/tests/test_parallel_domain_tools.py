"""Independent read tools keep database clients, scopes and results per worker."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from db import client as database
from services import tools


@pytest.mark.parametrize("name", ["knowledge_base_search", "code_graph_lookup", "recent_changes"])
def test_parallel_domain_reads_use_thread_local_clients_and_scopes(monkeypatch, name):
    clients = []
    overlap = threading.Barrier(2)

    def factory():
        client = SimpleNamespace(thread=threading.get_ident())
        clients.append(client)
        return client

    monkeypatch.setattr(database, "_thread_local", threading.local())
    monkeypatch.setattr(database, "_create_supabase_client", factory)
    assert tools.get_supabase is database.get_supabase_thread_safe

    def names(client, folders):
        assert client.thread == threading.get_ident()
        assert len(folders) == 1
        overlap.wait(timeout=5)
        return {folders[0]: folders[0]}

    def definition(client, *, folder_id, symbol):
        assert client.thread == threading.get_ident()
        assert symbol == folder_id
        return [{"kind": "function", "symbol": symbol, "file": symbol + ".py", "start_line": 1}]

    def summary(client, folder, owner):
        assert client.thread == threading.get_ident()
        assert folder == "folder-" + owner
        return {"sections": {"activity": {"content": {"summary": owner}}}}

    class Query:
        def __init__(self, client):
            self.client = client

        def select(self, _columns):
            return self

        def eq(self, column, owner):
            assert column == "user_id"
            self.owner = owner
            return self

        def in_(self, column, ids):
            assert column == "id" and ids == ["document-" + self.owner]
            return self

        def execute(self):
            assert self.client.thread == threading.get_ident()
            overlap.wait(timeout=5)
            return SimpleNamespace(
                data=[
                    {
                        "id": "document-" + self.owner,
                        "folder_id": "folder-" + self.owner,
                        "source_filename": self.owner + ".md",
                        "content_hash": self.owner,
                    }
                ]
            )

    def kb_factory():
        client = factory()
        client.table = lambda table: Query(client)
        return client

    if name == "knowledge_base_search":
        monkeypatch.setattr(database, "_create_supabase_client", kb_factory)

    def search(_embedding, **kwargs):
        owner = kwargs["user_id"]
        assert kwargs["folder_ids"] == ["folder-" + owner]
        return [{"id": "document-" + owner, "source_type": "document", "content": owner}]

    monkeypatch.setattr(tools, "_folder_names", names)
    monkeypatch.setattr(tools.graph_store, "find_definition", definition)
    monkeypatch.setattr(tools, "get_latest_summary", summary)
    monkeypatch.setattr(tools, "embed_query", lambda _query: [0.0])
    monkeypatch.setattr(tools, "search_documents", search)

    def invoke(owner):
        folder = "folder-" + owner
        arguments = {"query": owner, "operation": "definition", "symbol": folder}
        result = tools.execute_tool(
            name, arguments, owner, scope_folder_ids=[folder], full_debug=True
        )
        assert database.get_supabase_thread_safe() is tools.get_supabase()
        assert owner in result
        assert ("bob" if owner == "alice" else "alice") not in result
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, ["alice", "bob"]))
    assert len(results) == 2
    assert len(clients) == 2 and clients[0] is not clients[1]
    assert clients[0].thread != clients[1].thread
