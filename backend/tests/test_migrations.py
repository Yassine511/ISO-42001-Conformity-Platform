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


def test_0009_creates_chat_tables(scratch_db):
    """0009: chat tables exist at head with the status-coherence CHECK enforced."""
    _alembic(scratch_db, "upgrade", "head")
    con = _connect(scratch_db)
    try:
        for table in ("conversations", "chat_messages", "chat_llm_calls"):
            assert _columns(con, table), f"{table} missing"
        org_id, conv_id = str(uuid.uuid4()), str(uuid.uuid4())
        con.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (%s, 'Lumen AI', now())",
            (org_id,),
        )
        con.execute(
            "INSERT INTO conversations (id, organization_id, title, created_at, updated_at) "
            "VALUES (%s, %s, 'Question ?', now(), now())",
            (conv_id, org_id),
        )

        def _insert_message(status, abstain_reason, evidence_scope):
            con.execute(
                "INSERT INTO chat_messages (id, conversation_id, question, status, "
                "abstain_reason, answer, evidence_scope, claims, citations, "
                "stripped_citations, retrieved_policy, retrieved_kb, attempts, "
                "draft_attempts, prompt_version, corpus_version, created_at) "
                "VALUES (%s, %s, 'Q ?', %s, %s, 'Réponse.', %s, '[]', '[]', '[]', "
                "'[]', '[]', '[]', 1, '1', '1.0.0', now())",
                (str(uuid.uuid4()), conv_id, status, abstain_reason, evidence_scope),
            )

        _insert_message("ANSWERED", None, "policy")
        _insert_message("ABSTAINED", "model_abstained", None)
        con.commit()

        import psycopg

        # ANSWERED without a scope violates the coherence CHECK …
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_message("ANSWERED", None, None)
        con.rollback()
        # … as does ABSTAINED without a reason
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_message("ABSTAINED", None, None)
        con.rollback()

        # chat_llm_calls accepts a row bound to the message
        (msg_id,) = con.execute(
            "SELECT id FROM chat_messages WHERE status = 'ANSWERED'"
        ).fetchone()
        con.execute(
            "INSERT INTO chat_llm_calls (id, chat_message_id, call_number, "
            "draft_attempt_number, prompt_version, provider, requested_model, status, "
            "request_messages, response_format, temperature, started_at) "
            "VALUES (%s, %s, 1, 1, '1', 'mistral', 'mistral-large-latest', 'SUCCESS', "
            "'[]', '{}', 0.0, now())",
            (str(uuid.uuid4()), msg_id),
        )
        con.commit()
    finally:
        con.close()


def test_0010_backfills_legacy_claim_key(scratch_db):
    """0010: pre-ad46dbe claims carry `verified`; upgrading renames the key to
    `citations_verified` so replay validation succeeds (audit round 13 P0)."""
    import json

    _alembic(scratch_db, "upgrade", "0009")
    con = _connect(scratch_db)
    org_id, conv_id, msg_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    con.execute(
        "INSERT INTO organizations (id, name, created_at) VALUES (%s, 'Lumen AI', now())",
        (org_id,),
    )
    con.execute(
        "INSERT INTO conversations (id, organization_id, title, created_at, updated_at) "
        "VALUES (%s, %s, 'Q', now(), now())",
        (conv_id, org_id),
    )
    legacy_claims = json.dumps(
        [
            {"text": "A.", "kind": "organization", "citation_ids": ["c1"],
             "verified": True, "failed_citation_ids": []},
            {"text": "B.", "kind": "standard", "citation_ids": ["c9"],
             "verified": False, "failed_citation_ids": ["c9"]},
        ]
    )
    con.execute(
        "INSERT INTO chat_messages (id, conversation_id, question, status, answer, "
        "evidence_scope, claims, citations, stripped_citations, retrieved_policy, "
        "retrieved_kb, attempts, draft_attempts, prompt_version, corpus_version, "
        "created_at) VALUES (%s, %s, 'Q ?', 'ANSWERED', 'R.', 'policy', %s, '[]', "
        "'[]', '[]', '[]', '[]', 1, '1', '1.0.0', now())",
        (msg_id, conv_id, legacy_claims),
    )
    con.commit()
    con.close()

    _alembic(scratch_db, "upgrade", "head")

    con = _connect(scratch_db)
    try:
        (claims,) = con.execute(
            "SELECT claims FROM chat_messages WHERE id = %s", (msg_id,)
        ).fetchone()
        if isinstance(claims, str):
            claims = json.loads(claims)
        assert [c["citations_verified"] for c in claims] == [True, False]
        assert all("verified" not in c for c in claims)
    finally:
        con.close()

    # downgrade restores the legacy key (data symmetry, audit round 14 P2)
    _alembic(scratch_db, "downgrade", "0009")
    con = _connect(scratch_db)
    try:
        (claims,) = con.execute(
            "SELECT claims FROM chat_messages WHERE id = %s", (msg_id,)
        ).fetchone()
        if isinstance(claims, str):
            claims = json.loads(claims)
        assert [c["verified"] for c in claims] == [True, False]
        assert all("citations_verified" not in c for c in claims)
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


def test_0013_creates_remediation_tables(scratch_db):
    """0013: the ten remediation tables exist at head, the circular case FKs
    are real on Postgres, and the key CHECK constraints are enforced
    (gap-verdict link snapshot, triage projection coherence)."""
    _alembic(scratch_db, "upgrade", "head")
    con = _connect(scratch_db)
    try:
        for table in (
            "remediation_cases",
            "remediation_triage_drafts",
            "remediation_case_findings",
            "remediation_plans",
            "remediation_actions",
            "remediation_action_requirements",
            "remediation_reassessments",
            "remediation_events",
            "remediation_attempts",
            "remediation_llm_calls",
        ):
            assert _columns(con, table), f"{table} missing"

        # both circular FKs were added post-creation
        fks = [
            row[0]
            for row in con.execute(
                "SELECT conname FROM pg_constraint WHERE contype = 'f' "
                "AND conrelid = 'remediation_cases'::regclass"
            ).fetchall()
        ]
        assert "fk_remediation_cases_approved_triage_draft" in fks
        assert "fk_remediation_cases_active_plan" in fks

        import psycopg

        org_id, case_id = str(uuid.uuid4()), str(uuid.uuid4())
        con.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (%s, 'Lumen AI', now())",
            (org_id,),
        )
        con.execute(
            "INSERT INTO remediation_cases (id, organization_id, title, status, "
            "evidence_revision, created_at, updated_at) "
            "VALUES (%s, %s, 'Cas', 'TRIAGE', 0, now(), now())",
            (case_id, org_id),
        )
        con.commit()

        # a link snapshotting a compliant verdict violates the gap-verdict CHECK
        aid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        con.execute(
            "INSERT INTO assessments (id, organization_id, corpus_version, status, "
            "started_at) VALUES (%s, %s, '1.2.0', 'COMPLETED', now())",
            (aid, org_id),
        )
        con.execute(
            "INSERT INTO findings (id, assessment_id, requirement_id, status, attempts, "
            "retrieved, created_at) VALUES (%s, %s, 'A.9.2', 'VERIFIED', 1, '[]', now())",
            (fid, aid),
        )
        con.commit()

        def _insert_link(verdict):
            con.execute(
                "INSERT INTO remediation_case_findings (id, case_id, finding_id, "
                "is_primary, link_source, finding_review_count, finding_human_verdict, "
                "finding_requirement_id, created_at) "
                "VALUES (%s, %s, %s, true, 'creation', 1, %s, 'A.9.2', now())",
                (str(uuid.uuid4()), case_id, fid, verdict),
            )

        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_link("compliant")
        con.rollback()
        _insert_link("non_compliant")
        con.commit()

        # TRIAGE_APPROVED without the triage projection violates coherence
        with pytest.raises(psycopg.errors.CheckViolation):
            con.execute(
                "UPDATE remediation_cases SET status = 'TRIAGE_APPROVED' WHERE id = %s",
                (case_id,),
            )
        con.rollback()
    finally:
        con.close()

    # downgrade removes every remediation table
    _alembic(scratch_db, "downgrade", "0012")
    con = _connect(scratch_db)
    try:
        assert not _columns(con, "remediation_cases")
        assert not _columns(con, "remediation_llm_calls")
    finally:
        con.close()


def test_0014_backfills_document_versions(scratch_db):
    """0014: the four legacy document shapes migrate correctly — parsed docs
    get an ACTIVE version 1 with scheme document_id_v2 and a computed
    text_checksum; FAILED docs get no version and their mirror checksum is
    CLEARED; pages/chunks are re-parented; the circular current-version FK and
    the one-ACTIVE partial unique are real; downgrade refuses with history."""
    from app.services.checksums import text_checksum

    _alembic(scratch_db, "upgrade", "0013")
    con = _connect(scratch_db)
    org_id = str(uuid.uuid4())
    parsed_id, legacy_id, failed_zero_id, failed_ck_id = (
        str(uuid.uuid4()) for _ in range(4)
    )
    chunk_id = "chunk-legacy-1"
    try:
        con.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (%s, 'Lumen AI', now())",
            (org_id,),
        )

        def _doc(doc_id, filename, status, checksum, page_count):
            con.execute(
                "INSERT INTO documents (id, organization_id, filename, content_type, "
                "status, page_count, checksum, parser_version, created_at) "
                "VALUES (%s, %s, %s, 'text/plain', %s, %s, %s, '2', now())",
                (doc_id, org_id, filename, status, page_count, checksum),
            )

        _doc(parsed_id, "politique.md", "parsed", "aa11", 2)
        _doc(legacy_id, "ancien.txt", "parsed", None, 1)  # legacy NULL checksum
        _doc(failed_zero_id, "casse.pdf", "failed", None, 0)
        _doc(failed_ck_id, "casse2.pdf", "failed", "ff22", 0)
        for doc_id, number, page_text in (
            (parsed_id, 1, "Page un."),
            (parsed_id, 2, "Page deux."),
            (legacy_id, 1, "Texte historique."),
        ):
            con.execute(
                "INSERT INTO document_pages (id, document_id, page_number, text) "
                "VALUES (%s, %s, %s, %s)",
                (str(uuid.uuid4()), doc_id, number, page_text),
            )
        con.execute(
            "INSERT INTO chunks (id, document_id, page_number, char_start, char_end, text) "
            "VALUES (%s, %s, 1, 0, 8, 'Page un.')",
            (chunk_id, parsed_id),
        )
        con.commit()
    finally:
        con.close()

    _alembic(scratch_db, "upgrade", "head")

    con = _connect(scratch_db)
    try:
        rows = con.execute(
            "SELECT d.id, d.checksum, d.current_version_id, v.state, v.version_number, "
            "v.chunk_id_scheme, v.chunker_version, v.source_checksum, v.text_checksum "
            "FROM documents d LEFT JOIN document_versions v ON v.id = d.current_version_id"
        ).fetchall()
        by_id = {r[0]: r for r in rows}
        # parsed doc: ACTIVE v1, legacy scheme, checksums correct
        p = by_id[parsed_id]
        assert p[3] == "ACTIVE" and p[4] == 1
        assert p[5] == "document_id_v2" and p[6] == "2"
        assert p[7] == "aa11" == p[1]
        assert p[8] == text_checksum(["Page un.", "Page deux."])
        # legacy NULL-checksum doc: version exists, source_checksum NULL,
        # text_checksum computed
        l = by_id[legacy_id]
        assert l[3] == "ACTIVE" and l[7] is None
        assert l[8] == text_checksum(["Texte historique."])
        # failed docs: no version, mirror checksum cleared
        for fid in (failed_zero_id, failed_ck_id):
            assert by_id[fid][2] is None and by_id[fid][1] is None
        # pages/chunks re-parented; the pre-M7b chunk id is untouched
        (n_orphan_pages,) = con.execute(
            "SELECT COUNT(*) FROM document_pages WHERE document_version_id IS NULL"
        ).fetchone()
        assert n_orphan_pages == 0
        (cid, cvid) = con.execute(
            "SELECT id, document_version_id FROM chunks"
        ).fetchone()
        assert cid == chunk_id and cvid == p[2]

        import psycopg

        # circular FK: current_version_id must reference a version of the SAME doc
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            con.execute(
                "UPDATE documents SET current_version_id = %s WHERE id = %s",
                (by_id[legacy_id][2], parsed_id),
            )
        con.rollback()
        # one-ACTIVE partial unique
        with pytest.raises(psycopg.errors.UniqueViolation):
            con.execute(
                "INSERT INTO document_versions (id, document_id, organization_id, "
                "version_number, state, text_checksum, parser_version, chunker_version, "
                "chunk_id_scheme, page_count, origin, canonical_format, filename, "
                "supersedes_version_id, created_at) "
                "VALUES (%s, %s, %s, 2, 'ACTIVE', 'zz', '2', '3', 'version_id_v3', "
                "1, 'upload', 'md', 'politique.md', %s, now())",
                (str(uuid.uuid4()), parsed_id, org_id, by_id[parsed_id][2]),
            )
        con.rollback()
        # ABANDONED does not reserve content: same text_checksum acceptable
        abandoned_id = str(uuid.uuid4())
        con.execute(
            "INSERT INTO document_versions (id, document_id, organization_id, "
            "version_number, state, text_checksum, parser_version, chunker_version, "
            "chunk_id_scheme, page_count, origin, canonical_format, filename, "
            "supersedes_version_id, abandoned_reason, created_at) "
            "VALUES (%s, %s, %s, 2, 'ABANDONED', 'shared', '2', '3', 'version_id_v3', "
            "1, 'upload', 'md', 'politique.md', %s, 'stale_base', now())",
            (abandoned_id, parsed_id, org_id, by_id[parsed_id][2]),
        )
        con.execute(
            "INSERT INTO document_versions (id, document_id, organization_id, "
            "version_number, state, text_checksum, parser_version, chunker_version, "
            "chunk_id_scheme, page_count, origin, canonical_format, filename, "
            "supersedes_version_id, activation_token, activation_started_at, "
            "activation_heartbeat_at, created_at) "
            "VALUES (%s, %s, %s, 3, 'PENDING_INDEX', 'shared', '2', '3', "
            "'version_id_v3', 1, 'upload', 'md', 'politique.md', %s, %s, now(), now(), now())",
            (str(uuid.uuid4()), parsed_id, org_id, by_id[parsed_id][2], str(uuid.uuid4())),
        )
        con.commit()
        # …but a second NON-abandoned twin of the same content conflicts
        with pytest.raises(psycopg.errors.UniqueViolation):
            con.execute(
                "INSERT INTO document_versions (id, document_id, organization_id, "
                "version_number, state, text_checksum, parser_version, chunker_version, "
                "chunk_id_scheme, page_count, origin, canonical_format, filename, "
                "supersedes_version_id, activation_token, activation_started_at, "
                "activation_heartbeat_at, created_at) "
                "VALUES (%s, %s, %s, 4, 'PENDING_INDEX', 'shared', '2', '3', "
                "'version_id_v3', 1, 'upload', 'md', 'politique.md', %s, %s, now(), now(), now())",
                (str(uuid.uuid4()), parsed_id, org_id, by_id[parsed_id][2], str(uuid.uuid4())),
            )
        con.rollback()
    finally:
        con.close()

    # downgrade refuses while version history exists
    url = "postgresql+psycopg://int102:int102@localhost:5433/" + scratch_db
    env = {**os.environ, "DATABASE_URL": url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0013"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0 and "downgrade 0014 refused" in result.stderr

    # after pruning history down to the migration-created versions, downgrade works
    con = _connect(scratch_db)
    con.execute(
        "DELETE FROM document_versions WHERE version_number > 1"
    )
    con.commit()
    con.close()
    _alembic(scratch_db, "downgrade", "0013")
    con = _connect(scratch_db)
    try:
        assert "current_version_id" not in _columns(con, "documents")
        assert not _columns(con, "document_versions")
        assert "document_version_id" not in _columns(con, "chunks")
        # data survives the round-trip
        (n_pages,) = con.execute("SELECT COUNT(*) FROM document_pages").fetchone()
        assert n_pages == 3
    finally:
        con.close()


def test_0011_preflight_demotes_duplicate_running_rows(scratch_db):
    """0011 must be applicable to a database that already violates the new
    single-RUNNING-per-org invariant: all but the newest RUNNING row per org
    are finalized FAILED (error + finished_at set) before the partial unique
    index is created."""
    _alembic(scratch_db, "upgrade", "0010")
    con = _connect(scratch_db)
    org_id = str(uuid.uuid4())
    old_id, new_id, other_org_id, other_run = (
        str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()),
    )
    try:
        con.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (%s, 'Lumen AI', now())",
            (org_id,),
        )
        con.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (%s, 'Autre SA', now())",
            (other_org_id,),
        )
        con.execute(
            "INSERT INTO assessments (id, organization_id, corpus_version, status, started_at) "
            "VALUES (%s, %s, '1.2.0', 'RUNNING', now() - interval '1 hour')",
            (old_id, org_id),
        )
        con.execute(
            "INSERT INTO assessments (id, organization_id, corpus_version, status, started_at) "
            "VALUES (%s, %s, '1.2.0', 'RUNNING', now())",
            (new_id, org_id),
        )
        con.execute(
            "INSERT INTO assessments (id, organization_id, corpus_version, status, started_at) "
            "VALUES (%s, %s, '1.2.0', 'RUNNING', now() - interval '2 hour')",
            (other_run, other_org_id),
        )
        con.commit()
    finally:
        con.close()

    _alembic(scratch_db, "upgrade", "head")

    con = _connect(scratch_db)
    try:
        rows = dict(
            con.execute(
                "SELECT id, status FROM assessments WHERE organization_id = %s", (org_id,)
            ).fetchall()
        )
        assert rows[new_id] == "RUNNING"      # newest survives
        assert rows[old_id] == "FAILED"       # duplicate demoted
        (err, fin) = con.execute(
            "SELECT error, finished_at FROM assessments WHERE id = %s", (old_id,)
        ).fetchone()
        assert "migration 0011" in err and fin is not None
        # the other org's single RUNNING row is untouched
        (other_status,) = con.execute(
            "SELECT status FROM assessments WHERE id = %s", (other_run,)
        ).fetchone()
        assert other_status == "RUNNING"
        # new columns carry their defaults on legacy rows
        (k, cancel, manifest) = con.execute(
            "SELECT retrieval_k, cancel_requested, document_manifest "
            "FROM assessments WHERE id = %s",
            (new_id,),
        ).fetchone()
        assert k == 6 and cancel is False and manifest is None
    finally:
        con.close()
