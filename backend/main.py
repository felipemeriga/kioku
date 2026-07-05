import asyncio
import logging
import traceback
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from db.client import get_supabase
from routes.api_keys import router as api_keys_router
from routes.briefing import router as briefing_router
from routes.chat import router as chat_router
from routes.cli import router as cli_router
from routes.context import router as context_router
from routes.conversations import router as conversations_router
from routes.documents import router as documents_router
from routes.drop import router as drop_router
from routes.evaluation import router as evaluation_router
from routes.folders import router as folders_router
from routes.ingestion_jobs import router as ingestion_jobs_router
from routes.github import router as github_router
from routes.mem0 import router as mem0_router
from routes.notes import router as notes_router
from routes.notion import router as notion_router
from routes.retrieval_log import router as retrieval_log_router
from services.notion_sync.sync_engine import sync_loop

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(sync_loop(get_supabase))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Agentic RAG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(folders_router)
app.include_router(api_keys_router)
app.include_router(drop_router)
app.include_router(evaluation_router)
app.include_router(notes_router)
app.include_router(context_router)
app.include_router(notion_router)
app.include_router(ingestion_jobs_router)
app.include_router(mem0_router)
app.include_router(github_router)
app.include_router(briefing_router)
app.include_router(cli_router)
app.include_router(retrieval_log_router)


log = logging.getLogger("agentic-rag")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return JSON with {detail} on unhandled exceptions so the frontend's
    ApiError.userMessage extraction has something to work with. Without
    this, Starlette responds with an HTML error page + a Content-Type of
    text/html — the frontend then shows a generic 'server hit an error'
    instead of the real cause.

    Logs the full traceback server-side so operators can still debug.
    """
    log.error(
        "unhandled exception on %s %s: %s\n%s",
        request.method,
        request.url.path,
        exc,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"{type(exc).__name__}: {exc}",
        },
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}
