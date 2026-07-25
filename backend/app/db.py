from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


# LangGraph's PostgresSaver owns these tables (created by .setup(), versioned by
# the library): they exist in the database but not in Base.metadata. Anything
# comparing the two — Alembic autogenerate AND the migration-vs-model drift test
# — must skip them, so the filter lives here rather than in alembic/env.py
# (which cannot be imported: it runs migrations at module scope).
LANGGRAPH_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table" and name in LANGGRAPH_TABLES:
        return False
    if type_ == "index" and getattr(obj, "table", None) is not None:
        return obj.table.name not in LANGGRAPH_TABLES
    return True


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()