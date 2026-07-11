"""PG-backed concurrency integration tests for the M5 run guards.

SQLite ignores SELECT ... FOR UPDATE, so the org-lock serialization and the
partial unique index backstop can only be validated against a real Postgres.
Like tests/test_migrations.py these use the dev service on a throwaway
database and SKIP when it is unreachable (`docker compose up -d postgres`).

The vector stack stays fake (conftest autouse): only the relational
concurrency semantics are under test here.
"""

import threading
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Assessment, Document, DocumentPage, Organization
from app.pipeline import graph as graph_module
from app.pipeline.graph import AssessmentAlreadyRunningError, create_assessment
from app.services.parsing import PARSER_VERSION
from app.services.run_guard import lock_organization, running_assessment_id
from tests.test_migrations import _connect, _postgres_available

pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason="dev Postgres (localhost:5433) unreachable — docker compose up -d postgres",
)


@pytest.fixture()
def pg_env():
    """Throwaway PG database with the current schema + one parsed document."""
    name = f"conc_test_{uuid.uuid4().hex[:12]}"
    admin = _connect()
    admin.autocommit = True
    admin.execute(f'CREATE DATABASE "{name}"')
    admin.close()
    url = "postgresql+psycopg://int102:int102@localhost:5433/" + name
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    db = session_factory()
    org = Organization(name="Concurrence SA")
    db.add(org)
    db.commit()
    from tests.conftest import seed_parsed_document

    seed_parsed_document(db, org.id, "politique.txt", ["Politique IA de test."], checksum="cafe")
    org_id = org.id
    db.close()

    yield session_factory, org_id

    engine.dispose()
    admin = _connect()
    admin.autocommit = True
    admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()


def test_concurrent_creation_yields_exactly_one_running(pg_env):
    """Two simultaneous creations: the org row lock serializes them; the loser
    sees the winner's RUNNING row (or, in a pre-check race, the partial unique
    index rejects the second INSERT). Exactly one assessment survives."""
    session_factory, org_id = pg_env
    barrier = threading.Barrier(2, timeout=10)
    results: list = [None, None]

    def worker(slot: int) -> None:
        barrier.wait()
        try:
            results[slot] = ("ok", create_assessment(session_factory, org_id, ["A.9.2"]))
        except (AssessmentAlreadyRunningError, IntegrityError) as exc:
            results[slot] = ("conflict", type(exc).__name__)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    outcomes = sorted(r[0] for r in results)
    assert outcomes == ["conflict", "ok"], results
    db = session_factory()
    running = db.scalars(
        select(Assessment).where(
            Assessment.organization_id == org_id, Assessment.status == "RUNNING"
        )
    ).all()
    db.close()
    assert len(running) == 1


def test_creation_blocks_concurrent_index_style_mutation(pg_env, monkeypatch):
    """A corpus mutation (the /index handler pattern: lock org, check RUNNING)
    that starts while creation holds the org lock must block until creation
    commits, then see the RUNNING assessment — never interleave."""
    session_factory, org_id = pg_env
    in_creation = threading.Event()
    saw_running: list = []

    real_sync = graph_module.sync_index

    def sync_and_pause(db, oid):
        import time

        out = real_sync(db, oid)
        in_creation.set()  # creation now holds the org lock with staged work
        time.sleep(0.5)  # keep the lock held while the mutator attempts its own
        return out

    monkeypatch.setattr(graph_module, "sync_index", sync_and_pause)

    def mutator() -> None:
        assert in_creation.wait(timeout=15)
        db = session_factory()
        try:
            # blocks on the org row lock until creation commits
            lock_organization(db, org_id)
            saw_running.append(running_assessment_id(db, org_id))
        finally:
            db.rollback()
            db.close()

    t_mutate = threading.Thread(target=mutator)
    t_create = threading.Thread(
        target=lambda: create_assessment(session_factory, org_id, ["A.9.2"])
    )
    t_mutate.start()
    t_create.start()
    t_create.join(timeout=30)
    t_mutate.join(timeout=30)

    assert len(saw_running) == 1 and saw_running[0] is not None


def test_partial_unique_index_rejects_second_running_row(pg_env):
    """DB-level backstop, independent of application code paths."""
    session_factory, org_id = pg_env
    db = session_factory()
    db.add(
        Assessment(organization_id=org_id, corpus_version="1.2.0", status="RUNNING")
    )
    db.commit()
    db.add(
        Assessment(organization_id=org_id, corpus_version="1.2.0", status="RUNNING")
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()
