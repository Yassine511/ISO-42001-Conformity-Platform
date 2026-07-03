from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401 — register tables on Base metadata
from app.api import documents, organizations
from app.config import settings
from app.db import Base, engine


def run_migrations() -> None:
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if engine.url.get_backend_name() == "sqlite":
        Base.metadata.create_all(bind=engine)  # tests / throwaway local runs
    else:
        run_migrations()
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
