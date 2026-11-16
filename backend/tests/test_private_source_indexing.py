from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from routes.cli import CodeFileIn
from services.code_sources import is_indexable_source_file
from services.repo_graph.mapping import map_edge, map_node
from services.repo_graph.store import apply_delta


@pytest.mark.parametrize(
    "path",
    [
        ".mcp.json",
        "nested/.MCP.JSON",
        ".env",
        "a/.env.local",
        ".claude/settings.json",
        ".codex/config.toml",
        ".npmrc",
        "a\\.mcp.json",
        "../outside.py",
        "/etc/passwd",
    ],
)
def test_private_sources_rejected_without_echoing_content(path):
    assert not is_indexable_source_file(path)
    with pytest.raises(ValidationError) as error:
        CodeFileIn(file=path, file_hash="hash", chunks=[{"content": "private credential sentinel"}])
    assert "private credential sentinel" not in str(error.value)
    assert map_node({"id": "n", "source_file": path}, folder_id="f", user_id="u") is None
    assert (
        map_edge(
            {"source": "n", "target": "m", "relation": "calls", "source_file": path},
            folder_id="f",
            user_id="u",
        )
        is None
    )


def test_regular_code_is_still_indexable():
    assert is_indexable_source_file("src/module.py")
    assert CodeFileIn(file="src/module.py", file_hash="hash", chunks=[]).file == "src/module.py"


def test_graph_edges_to_rejected_private_nodes_are_not_stored():
    writes = []
    deleted_files = []

    class Database:
        def table(self, name):
            self.name = name
            return self

        def insert(self, rows):
            writes.extend(rows)
            return self

        def upsert(self, rows, **kwargs):
            return self

        def in_(self, column, values):
            if column in {"file", "ref_file"}:
                deleted_files.extend(values)
            return self

        def query(self, *args, **kwargs):
            return self

        select = eq = delete = query

        def execute(self):
            return SimpleNamespace(data=[], count=0)

    apply_delta(
        Database(),
        folder_id="f",
        user_id="u",
        changed_files=[".mcp.json"],
        deleted_files=[],
        nodes=[{"id": "private_config", "source_file": ".mcp.json"}],
        edges=[
            {
                "source": "public_func",
                "target": target,
                "relation": "calls",
                "source_file": "src/main.py",
            }
            for target in ["private_config", "unchanged_public_target"]
        ],
        head_sha=None,
    )
    assert ".mcp.json" in deleted_files
    assert len(writes) == 1
    assert writes[0]["dst_node_id"] == "unchanged_public_target"


@pytest.mark.asyncio
async def test_preexisting_queue_jobs_cannot_embed_private_configuration(monkeypatch):
    from services import embeddings
    from services.queue import tasks

    embed = MagicMock(return_value=[[0.1]])
    insert = AsyncMock()
    monkeypatch.setattr(embeddings, "embed_code_batch", embed)
    monkeypatch.setattr(tasks, "_insert_rows_concurrent", insert)
    await tasks.embed_code_chunks_task(
        {},
        {
            "rows": [
                {"file": ".mcp.json", "content": "private sentinel"},
                {"file": "src/main.py", "content": "public source"},
            ]
        },
    )
    embed.assert_called_once_with(["public source"])
    assert len(insert.call_args.args[1]) == 1
    assert insert.call_args.args[1][0]["file"] == "src/main.py"
