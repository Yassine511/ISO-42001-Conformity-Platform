"""Migration-chain tests for the amended-0005 repair (revision 0006).

Revision 0005 was published (c25df1c), then amended in place: a database
stamped 0005 under the PUBLISHED form has no llm_calls.prompt_version and an
abstain-reason CHECK without 'rate_limited'. These tests upgrade a database
from exactly that state — not a fresh one — and assert 0006 applies the delta
(column added, backfilled from assessment_attempts, NOT NULL, CHECK rebuilt).

The historical migration chain is Postgres-only (0002 uses ALTER COLUMN …
DROP NOT NULL), so these tests run against the dev Postgres service on a
throwaway database and SKIP when it is unreachable — like
scripts/retrieval_sanity.py, they need `docker compose up -d postgres`.
Alembic runs in a subprocess: env.py takes its URL from settings, so
DATABASE_URL is enough to redirect it.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
_ADMIN_URL = "postgresql://int102:int102@localhost:5433/int102"


def _connect(dbname: str | None = None):
    import psycopg

    url = _ADMIN_URL if dbname is None else _ADMIN_URL.rsplit("/", 1)[0] + "/" + dbname
    return psycopg.connect(url, connect_timeout=3)


def _postgres_available() -> bool:
    try:
        _connect().close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason="dev Postgres (localhost:5433) unreachable — docker compose up -d postgres",
)


@pytest.fixture()
def scratch_db():
    """A dedicated throwaway database so the dev data is never touched."""
    name = f"mig_test_{uuid.uuid4().hex[:12]}"
    admin = _connect()
    admin.autocommit = True
    admin.execute(f'CREATE DATABASE "{name}"')
    admin.close()
    yield name
    admin = _connect()
    admin.autocommit = True
    admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()


def _alembic(dbname: str, *args: str) -> None:
    url = "postgresql+psycopg://int102:int102@localhost:5433/" + dbname
    env = {**os.environ, "DATABASE_URL": url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"


def _columns(con, table: str) -> dict[str, bool]:
    """column name -> is_nullable"""
    rows = con.execute(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_name = %s",
        (table,),
    ).fetchall()
    return {name: nullable == "YES" for name, nullable in rows}


def _seed_published_0005(con) -> str:
    """Rows a real pre-amendment database would hold. Returns assessment id."""
    org_id, assessment_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    con.execute(
        "INSERT INTO organizations (id, name, created_at) VALUES (%s, %s, now())",
        (org_id, "Lumen AI"),
    )
    con.execute(
        "INSERT INTO assessments (id, organization_id, corpus_version, status, started_at) "
        "VALUES (%s, %s, '1.0.0', 'RUNNING', now())",
        (assessment_id, org_id),
    )
    con.execute(
        "INSERT INTO assessment_attempts (id, assessment_id, requirement_id, "
        "attempt_number, prompt_version, parsed_ok, started_at) "
        "VALUES (%s, %s, 'A.9.2', 1, 'v7', true, now())",
        (attempt_id, assessment_id),
    )
    con.execute(
        "INSERT INTO llm_calls (id, assessment_attempt_id, call_number, provider, "
        "requested_model, status, request_messages, response_format, temperature, "
        "started_at) VALUES (%s, %s, 1, 'mistral', 'mistral-large-latest', 'SUCCESS', "
        "'[]', '{}', 0.0, now())",
        (str(uuid.uuid4()), attempt_id),
    )
    con.commit()
    return assessment_id


def _insert_finding(con, assessment_id: str, requirement_id: str, reason: str) -> None:
    con.execute(
        "INSERT INTO findings (id, assessment_id, requirement_id, status, "
        "abstain_reason, attempts, retrieved, created_at) VALUES (%s, %s, %s, "
        "'ABSTAINED', %s, 1, '[]', now())",
        (str(uuid.uuid4()), assessment_id, requirement_id, reason),
    )


def test_published_0005_has_no_prompt_version(scratch_db):
    """Guard against re-amending 0005: at revision 0005 the schema must be the
    PUBLISHED form (no llm_calls.prompt_version, CHECK without rate_limited)."""
    _alembic(scratch_db, "upgrade", "0005")
    con = _connect(scratch_db)
    try:
        assert "prompt_version" not in _columns(con, "llm_calls")
        (check_def,) = con.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_findings_abstain_reason'"
        ).fetchone()
        assert "rate_limited" not in check_def
    finally:
        con.close()


def test_upgrade_from_published_0005(scratch_db):
    _alembic(scratch_db, "upgrade", "0005")
    con = _connect(scratch_db)
    assessment_id = _seed_published_0005(con)
    con.close()

    _alembic(scratch_db, "upgrade", "head")

    con = _connect(scratch_db)
    try:
        cols = _columns(con, "llm_calls")
        assert "prompt_version" in cols
        assert cols["prompt_version"] is False, "prompt_version must be NOT NULL"
        # no leftover temporary default
        default = con.execute(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'llm_calls' AND column_name = 'prompt_version'"
        ).fetchone()[0]
        assert default is None
        # backfilled from the parent attempt, not defaulted
        (backfilled,) = con.execute("SELECT prompt_version FROM llm_calls").fetchone()
        assert backfilled == "v7"
        # the rebuilt CHECK accepts rate_limited …
        _insert_finding(con, assessment_id, "A.9.2", "rate_limited")
        con.commit()
        # … and still rejects unknown reasons
        import psycopg

        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_finding(con, assessment_id, "A.9.3", "bogus_reason")
        con.rollback()
        # 0007: findings.audit_log exists and is nullable
        finding_cols = _columns(con, "findings")
        assert finding_cols.get("audit_log") is True
    finally:
        con.close()


def test_downgrade_to_published_0005(scratch_db):
    _alembic(scratch_db, "upgrade", "0005")
    con = _connect(scratch_db)
    assessment_id = _seed_published_0005(con)
    con.close()

    _alembic(scratch_db, "upgrade", "head")
    con = _connect(scratch_db)
    _insert_finding(con, assessment_id, "A.9.2", "rate_limited")
    con.commit()
    con.close()

    _alembic(scratch_db, "downgrade", "0005")

    con = _connect(scratch_db)
    try:
        assert "prompt_version" not in _columns(con, "llm_calls")
        assert "audit_log" not in _columns(con, "findings")
        # rate_limited rows were narrowed to llm_error before the old CHECK
        (reason,) = con.execute("SELECT abstain_reason FROM findings").fetchone()
        assert reason == "llm_error"
    finally:
        con.close()


def test_head_accepts_long_provider_model_names(scratch_db):
    """0008: reported_model/requested_model/final_model are Text at head, so a
    provider returning a >100-char model name no longer DataErrors the write
    (which would leave the assessment RUNNING with no finding). Only reproducible
    on Postgres — SQLite does not enforce VARCHAR length."""
    _alembic(scratch_db, "upgrade", "head")
    con = _connect(scratch_db)
    try:
        org_id, aid, attempt_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        con.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (%s, 'Lumen AI', now())",
            (org_id,),
        )
        con.execute(
            "INSERT INTO assessments (id, organization_id, corpus_version, status, started_at) "
            "VALUES (%s, %s, '1.0.0', 'RUNNING', now())",
            (aid, org_id),
        )
        con.execute(
            "INSERT INTO assessment_attempts (id, assessment_id, requirement_id, "
            "attempt_number, prompt_version, parsed_ok, started_at) "
            "VALUES (%s, %s, 'A.9.2', 1, 'v7', true, now())",
            (attempt_id, aid),
        )
        long_name = "x" * 200
        con.execute(
            "INSERT INTO llm_calls (id, assessment_attempt_id, call_number, prompt_version, "
            "provider, requested_model, status, reported_model, request_messages, "
            "response_format, temperature, started_at) VALUES (%s, %s, 1, 'v7', 'groq', %s, "
            "'SUCCESS', %s, '[]', '{}', 0.0, now())",
            (str(uuid.uuid4()), attempt_id, long_name, long_name),
        )
        con.execute(
            "INSERT INTO findings (id, assessment_id, requirement_id, status, attempts, "
            "final_model, retrieved, created_at) VALUES (%s, %s, 'A.9.2', 'VERIFIED', 1, %s, "
            "'[]', now())",
            (str(uuid.uuid4()), aid, long_name),
        )
        con.commit()
        (stored,) = con.execute("SELECT reported_model FROM llm_calls").fetchone()
        assert stored == long_name  # full value stored, not truncated
    finally:
        con.close()
