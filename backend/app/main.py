from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401 — register tables on Base metadata
from app.api import documents, organizations
from app.config import settings
from app.db import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # M1a: create_all suffices; replace with Alembic migrations when the schema grows.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="INT102 — Copilote de conformité ISO/IEC 42001", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(organizations.router)
app.include_router(documents.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
