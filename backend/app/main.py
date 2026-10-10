"""FastAPI routes. Audit endpoints arrive with the job queue (M2/M3)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.tracing import flush, init_tracing


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_tracing()
    yield
    flush()


app = FastAPI(title="PreJudge", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
