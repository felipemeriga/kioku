from routes import briefing


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Resp(self._data)


class _SB:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _Q(self._tables.get(name, []))


def test_index_status_includes_generation_timestamps():
    sb = _SB(
        {
            "repo_graph_meta": [
                {
                    "last_indexed_sha": "abc",
                    "node_count": 10,
                    "edge_count": 20,
                    "updated_at": "2026-10-06T00:00:00+00:00",
                }
            ],
            "code_chunks": [{"created_at": "2026-10-06T01:00:00+00:00"}],
            "repo_documentation": [{"generated_at": "2026-10-05T00:00:00+00:00"}],
        }
    )
    latest = {
        "sections": {
            "architecture": {"updated_at": "2026-10-06T02:24:03+00:00", "updated_by": "watcher"},
            "overview": {"updated_at": "2026-10-06T02:24:04+00:00", "updated_by": "watcher"},
        }
    }
    out = briefing._index_status(sb, "f1", "u1", {"checked_at": "t", "head_sha": "h"}, latest)
    assert out["architecture_at"] == "2026-10-06T02:24:03+00:00"
    assert out["architecture_by"] == "watcher"
    assert out["overview_at"] == "2026-10-06T02:24:04+00:00"
    assert out["detailed_doc_at"] == "2026-10-05T00:00:00+00:00"


def test_index_status_handles_missing(monkeypatch):
    sb = _SB({"repo_graph_meta": [], "code_chunks": [], "repo_documentation": []})
    out = briefing._index_status(sb, "f1", "u1", None, None)
    assert out["architecture_at"] is None
    assert out["detailed_doc_at"] is None
    assert out["graph_at"] is None
