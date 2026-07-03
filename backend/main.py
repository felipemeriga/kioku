import asyncio
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.client import get_supabase
from routes.api_keys import router as api_keys_router
from routes.chat import router as chat_router
from routes.context import router as context_router
from routes.conversations import router as conversations_router
from routes.documents import router as documents_router
from routes.drop import router as drop_router
from routes.evaluation import router as evaluation_router
from routes.folders import router as folders_router
from routes.ingestion_jobs import router as ingestion_jobs_router
from routes.notes import router as notes_router
from routes.notion import router as notion_router
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


@app.get("/api/health")
async def health():
    return {"status": "ok"}
