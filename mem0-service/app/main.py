from fastapi import Depends, FastAPI, Header, HTTPException

from app.config import settings
from app.models import AddReq, ListReq, SearchReq
from app.store import MemoryStore

app = FastAPI(title="kioku mem0 service")

# Built lazily on first use (constructing MemoryStore loads the embedder and
# opens the DB pool). Tests patch this module global with a fake store.
store: MemoryStore | None = None


def get_store() -> MemoryStore:
    global store
    if store is None:
        store = MemoryStore()
    return store


def require_token(authorization: str = Header(default="")):
    if authorization != f"Bearer {settings.service_token}":
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/health")
def health(_=Depends(require_token)):
    try:
        ok, err = get_store().ping()
    except Exception as e:  # noqa: BLE001 — health must never raise
        ok, err = False, str(e)
    return {"ok": ok, "error": err}


@app.post("/memories")
def add(body: AddReq, _=Depends(require_token)):
    return get_store().add(
        body.user_id,
        body.folder_id,
        body.content,
        scope=body.scope,
        category=body.category,
        tags=body.tags,
        written_by=body.written_by or "kioku",
    )


@app.post("/memories/search")
def search(body: SearchReq, _=Depends(require_token)):
    return {
        "results": get_store().search(
            body.user_id,
            body.folder_id,
            body.query,
            scope=body.scope or "any",
            limit=body.limit or 10,
        )
    }


@app.post("/memories/list")
def list_(body: ListReq, _=Depends(require_token)):
    return {
        "results": get_store().list(
            body.user_id,
            body.folder_id,
            scope=body.scope or "any",
            limit=body.limit or 50,
        )
    }


@app.delete("/memories/{memory_id}")
def delete(memory_id: str, _=Depends(require_token)):
    return get_store().delete(memory_id)
