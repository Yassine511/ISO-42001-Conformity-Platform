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
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    # A database created before Alembic was introduced (M1a create_all) has the
    # tables but no alembic_version: adopt it by stamping the initial revision.
    from sqlalchemy import inspect

    inspector = inspect(engine)
    if inspector.has_table("organizations") and not inspector.has_table("alembic_version"):
        command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")


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
