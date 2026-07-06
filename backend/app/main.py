from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from fastapi.exceptions import RequestValidationError

from app import models  # noqa: F401 — register tables on Base metadata
from app.api import assessments, chat, documents, organizations, retrieval
from app.config import settings
from app.db import Base, engine, get_db
from app.services import qdrant


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


@app.exception_handler(RequestValidationError)
async def french_validation_errors(request: Request, exc: RequestValidationError):
    """Normalize Pydantic request-validation errors into one usable French
    detail string (the UI surfaces `detail` directly)."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body",))
        msg = err.get("msg", "valeur invalide")
        parts.append(f"{loc} : {msg}" if loc else msg)
    return JSONResponse(
        {"detail": "Requête invalide — " + " ; ".join(parts)}, status_code=422
    )


@app.middleware("http")
async def reject_oversized_upload(request: Request, call_next):
    """Reject an oversized upload by its declared Content-Length BEFORE Starlette
    parses (and buffers) the multipart body.

    The bound is the REQUEST-size limit (file limit + framing margin), not the
    file limit: Content-Length covers the whole multipart envelope, so comparing
    it against the 20 MB file limit would 413 a valid ~20 MB file. The exact file
    size is still enforced by _read_capped in the handler. A chunked request with
    no Content-Length slips past this cheap check — in production nginx's
    client_max_body_size caps the request body as it streams; on the direct
    backend path _read_capped still bounds our own memory use."""
    if request.method == "POST" and request.url.path.endswith("/documents"):
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                oversized = int(declared) > (
                    documents.MAX_FILE_SIZE + documents.UPLOAD_REQUEST_MARGIN
                )
            except ValueError:
                oversized = False
            if oversized:
                return JSONResponse(
                    {"detail": "Fichier trop volumineux (limite : 20 Mo)."},
                    status_code=413,
                )
    return await call_next(request)


# Added AFTER the upload guard so CORS is the outermost layer (its headers apply
# even to the early 413).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(organizations.router)
app.include_router(documents.router)
app.include_router(retrieval.router)
app.include_router(chat.router)
app.include_router(assessments.router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    """Liveness + dependency readiness: probes PostgreSQL and Qdrant so an
    orchestrator (and the container healthcheck) sees 503 when a backing store
    is down instead of a misleading 200."""
    deps: dict[str, str] = {}
    healthy = True
    try:
        db.execute(text("SELECT 1"))
        deps["database"] = "ok"
    except Exception:
        deps["database"] = "unavailable"
        healthy = False
    try:
        qdrant.get_client().get_collections()
        deps["qdrant"] = "ok"
    except Exception:
        deps["qdrant"] = "unavailable"
        healthy = False
    body = {"status": "ok" if healthy else "degraded", "dependencies": deps}
    return body if healthy else JSONResponse(body, status_code=503)
