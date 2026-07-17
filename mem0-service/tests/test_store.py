import os

import pytest

from app.store import MemoryStore

pytestmark = pytest.mark.skipif(
    not os.getenv("MEM0_IT"), reason="needs a real pgvector DB"
)


@pytest.fixture(scope="module")
def store():
    return MemoryStore()


def test_add_then_list_scoped(store):
    store.add(
        "u1",
        "folderA",
        "prefers tabs over spaces",
        scope="eternal",
        category="preference",
    )
    a = store.list("u1", "folderA", scope="eternal", limit=50)
    b = store.list("u1", "folderB", scope="eternal", limit=50)
    assert any("prefers tabs" in m["memory"] for m in a)
    assert all("prefers tabs" not in m["memory"] for m in b)  # folder isolation


def test_dedup_same_content(store):
    r1 = store.add(
        "u1", "folderC", "rule X applies here", scope="eternal", category="preference"
    )
    r2 = store.add(
        "u1", "folderC", "rule X applies here", scope="eternal", category="preference"
    )
    assert r2["duplicate"] is True and r2["memory_id"] == r1["memory_id"]
