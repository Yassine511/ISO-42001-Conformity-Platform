"""PG-backed consistency test for the M8 reporting snapshot.

READ COMMITTED would let a review committed between report-assembly stages
leak into the second half of a report (mixed state). The reporting session
opens REPEATABLE READ / READ ONLY before its first query, so every stage
reads one snapshot. SQLite cannot express isolation levels — PG only, same
skip contract as tests/test_pg_concurrency.py."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Assessment, Finding, FindingReview, Organization
from app.services import scoring
from tests.test_migrations import _connect, _postgres_available

pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason="dev Postgres (localhost:5433) unreachable — docker compose up -d postgres",
)

NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def pg_env():
    name = f"report_test_{uuid.uuid4().hex[:12]}"
    admin = _connect()
    admin.autocommit = True
    admin.execute(f'CREATE DATABASE "{name}"')
    admin.close()
    url = "postgresql+psycopg://int102:int102@localhost:5433/" + name
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    db = session_factory()
    org = Organization(name="Snapshot SA")
    db.add(org)
    db.commit()
    a = Assessment(
        organization_id=org.id, corpus_version="1.3.0", status="COMPLETED",
        requirement_ids=["4.1"],
    )
    db.add(a)
    db.commit()
    f = Finding(
        assessment_id=a.id, requirement_id="4.1", status="VERIFIED",
        verdict="compliant", attempts=1,
    )
    db.add(f)
    db.commit()
    ids = (org.id, a.id, f.id)
    db.close()

    yield session_factory, ids

    engine.dispose()
    admin = _connect()
    admin.autocommit = True
    admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()


def _reporting_session(session_factory):
    db = session_factory()
    db.connection(
        execution_options={
            "isolation_level": "REPEATABLE READ",
            "postgresql_readonly": True,
        }
    )
    return db


def test_review_committed_mid_assembly_never_mixes_states(pg_env):
    session_factory, (org_id, assessment_id, finding_id) = pg_env

    report_db = _reporting_session(session_factory)
    scope = scoring.build_reporting_scope(report_db, org_id)
    conformity_before = scoring.conformity_summary(scope)
    assert conformity_before["scored"] == 0  # nothing confirmed yet

    # another session confirms the finding between assembly stages
    writer = session_factory()
    f = writer.get(Finding, finding_id)
    f.review_status = "CONFIRMED"
    f.review_action = "approve"
    f.human_verdict = "compliant"
    f.reviewed_at = NOW
    f.review_count = 1
    writer.add(
        FindingReview(
            finding_id=finding_id, sequence=1, action="approve",
            human_verdict="compliant",
        )
    )
    writer.commit()
    writer.close()

    # the SAME report transaction must keep seeing the pre-review state:
    # trust_panel re-queries the DB, so READ COMMITTED would count 1 event
    trust = scoring.trust_panel(report_db, scope)
    assert trust["review"]["review_events"] == 0
    report_db.close()

    # a NEW report sees the entirely-new state
    fresh = _reporting_session(session_factory)
    scope2 = scoring.build_reporting_scope(fresh, org_id)
    assert scoring.conformity_summary(scope2)["scored"] == 1
    assert scoring.trust_panel(fresh, scope2)["review"]["review_events"] == 1
    fresh.close()


def test_reporting_session_is_read_only(pg_env):
    session_factory, (org_id, _, finding_id) = pg_env
    db = _reporting_session(session_factory)
    scoring.build_reporting_scope(db, org_id)  # opens the tx
    f = db.get(Finding, finding_id)
    f.review_note = "tentative d'écriture"
    with pytest.raises(Exception) as exc:
        db.flush()
    assert "read-only" in str(exc.value).lower()
    db.rollback()
    db.close()
