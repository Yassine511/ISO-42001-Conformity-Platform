"""M7b document-editing tool — Document -> DocumentVersion restructuring.

- document_versions: one immutable content state per row; pages/chunks are
  re-parented under their version (document_id kept as an immutable
  denormalization, proven coherent by composite FKs). One ACTIVE version per
  document (partial unique); per-document text_checksum reversion rule that
  deliberately EXCLUDES terminal ABANDONED candidates (they must not reserve
  their content against a fresh authorized attempt).
- Backfill: every status='parsed' document becomes version 1 (ACTIVE,
  origin='upload', chunker_version='2', chunk_id_scheme='document_id_v2' —
  existing chunk ids are NEVER touched; chunking is write-once per version).
  FAILED documents get no version and their mirror checksum is CLEARED
  (behavior change: a failed upload no longer blocks re-upload of its bytes).
- patch_proposals / patch_decisions / remediation_artifacts: the anchored
  patch flow (TXT/MD) and the PDF/DOCX Markdown-artifact flow, both with a
  DRAFTING lease (rows exist before the LLM call) and staleness pins.
- document_version_events: append-only generic version lifecycle stream
  (case-scoped remediation_events cannot host caseless superseding uploads).
- remediation_attempts: stages 'patch'/'artifact' + parent FKs.

Circular FKs added AFTER the tables exist (0013 pattern; the ORM keeps the
columns plain because SQLite create_all cannot ALTER-add):
  documents(id, current_version_id)      -> document_versions(document_id, id)
  document_versions.source_artifact_id   -> remediation_artifacts(id) RESTRICT

POST-MIGRATION: run /index (or scripts) for every organization — Qdrant
points must gain the document_version_id payload; points lacking it never
match the snapshot filter (fail-closed) until re-upserted.

Downgrade REFUSES if any document has more than its migration-created version:
dropping version history would destroy exactly the provenance M7b establishes.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-11
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_VERSION_STATES_SQL = "'PENDING_INDEX', 'ACTIVE', 'SUPERSEDED', 'INDEX_FAILED', 'ABANDONED'"
_ABANDONED_REASONS_SQL = "'stale_base', 'stale_action', 'authority_lost', 'checksum_conflict'"
_CANONICAL_FORMATS_SQL = "'pdf', 'docx', 'txt', 'md'"
_CHUNK_ID_SCHEMES_SQL = "'document_id_v2', 'version_id_v3'"
_PATCH_ABSTAIN_SQL = (
    "'anchor_not_found', 'anchor_ambiguous', 'schema_invalid', 'llm_error', "
    "'rate_limited', 'draft_interrupted'"
)
_VERSION_EVENT_TYPES_SQL = (
    "'version_created', 'version_indexed', 'version_activated', "
    "'version_activation_abandoned', 'version_index_failed', 'version_recovered', "
    "'version_superseded_by_upload'"
)
_OLD_EVENT_TYPES_SQL = (
    "'case_created', 'finding_linked', 'finding_link_rejected', 'finding_unlinked', "
    "'triage_drafted', 'triage_approved', 'triage_reopened', 'plan_draft_started', "
    "'plan_drafted', 'plan_abstained', 'plan_superseded', 'plan_draft_recovered', "
    "'action_reviewed', 'lifecycle_changed', 'reassessment_launched', "
    "'effectiveness_recorded', 'case_closed', 'case_reopened'"
)
_NEW_EVENT_TYPES_SQL = _OLD_EVENT_TYPES_SQL + (
    ", 'patch_proposed', 'patch_abstained', 'patch_approved', 'patch_rejected', "
    "'patch_activation_abandoned', 'artifact_created', 'artifact_abstained', "
    "'version_superseded_by_upload'"
)
_OLD_STAGE_COHERENCE_SQL = (
    "(stage = 'triage' AND triage_draft_id IS NOT NULL AND plan_id IS NULL) "
    "OR (stage = 'plan' AND plan_id IS NOT NULL AND triage_draft_id IS NULL)"
)
_NEW_STAGE_COHERENCE_SQL = (
    "(stage = 'triage' AND triage_draft_id IS NOT NULL AND plan_id IS NULL "
    "AND patch_proposal_id IS NULL AND remediation_artifact_id IS NULL) "
    "OR (stage = 'plan' AND plan_id IS NOT NULL AND triage_draft_id IS NULL "
    "AND patch_proposal_id IS NULL AND remediation_artifact_id IS NULL) "
    "OR (stage = 'patch' AND patch_proposal_id IS NOT NULL AND triage_draft_id IS NULL "
    "AND plan_id IS NULL AND remediation_artifact_id IS NULL) "
    "OR (stage = 'artifact' AND remediation_artifact_id IS NOT NULL "
    "AND triage_draft_id IS NULL AND plan_id IS NULL AND patch_proposal_id IS NULL)"
)


def _lease_checks(table: str) -> list:
    return [
        sa.CheckConstraint(
            "status IN ('DRAFTING', 'VERIFIED', 'ABSTAINED')", name=f"ck_{table}_status"
        ),
        sa.CheckConstraint(
            "(status = 'DRAFTING' AND drafting_token IS NOT NULL "
            "AND drafting_started_at IS NOT NULL AND drafting_heartbeat_at IS NOT NULL) "
            "OR (status != 'DRAFTING' AND drafting_token IS NULL "
            "AND drafting_started_at IS NULL AND drafting_heartbeat_at IS NULL)",
            name=f"ck_{table}_lease_coherence",
        ),
        sa.CheckConstraint(
            "(status = 'ABSTAINED' AND abstain_reason IS NOT NULL) "
            "OR (status != 'ABSTAINED' AND abstain_reason IS NULL)",
            name=f"ck_{table}_abstain_coherence",
        ),
        sa.CheckConstraint(
            f"abstain_reason IS NULL OR abstain_reason IN ({_PATCH_ABSTAIN_SQL})",
            name=f"ck_{table}_abstain_taxonomy",
        ),
    ]


def _canonical_format(filename: str) -> str:
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    return ext if ext in ("pdf", "docx", "txt", "md") else "txt"


def upgrade() -> None:
    bind = op.get_bind()

    # ---- preflights -------------------------------------------------------
    dup = bind.execute(
        sa.text(
            "SELECT document_id, page_number, COUNT(*) FROM document_pages "
            "GROUP BY document_id, page_number HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).fetchone()
    if dup:
        raise RuntimeError(
            f"migration 0014 preflight: duplicate (document_id, page_number) "
            f"rows in document_pages ({dup[0]}, page {dup[1]}) — repair before "
            "adding uq_document_pages_version_page."
        )
    orphan = bind.execute(
        sa.text(
            "SELECT p.document_id FROM document_pages p JOIN documents d "
            "ON d.id = p.document_id WHERE d.status != 'parsed' LIMIT 1"
        )
    ).fetchone()
    if orphan:
        raise RuntimeError(
            f"migration 0014 preflight: document {orphan[0]} has pages but is "
            "not 'parsed' — no version can own them; repair before migrating."
        )

    # ---- document_versions ------------------------------------------------
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=True),
        sa.Column("text_checksum", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(20), nullable=False),
        sa.Column("chunker_version", sa.String(20), nullable=False),
        sa.Column("chunk_id_scheme", sa.String(20), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("supersedes_version_id", sa.String(36), nullable=True),
        sa.Column("source_artifact_id", sa.String(36), nullable=True),  # FK post-hoc
        sa.Column("canonical_format", sa.String(10), nullable=False),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("reported_mime", sa.String(100), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("activation_token", sa.String(36), nullable=True),
        sa.Column("activation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activation_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activation_error", sa.Text(), nullable=True),
        sa.Column("abandoned_reason", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "id", name="uq_document_versions_doc_id"),
        sa.UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_number"
        ),
        sa.CheckConstraint(f"state IN ({_VERSION_STATES_SQL})", name="ck_document_versions_state"),
        sa.CheckConstraint("origin IN ('upload', 'patch')", name="ck_document_versions_origin"),
        sa.CheckConstraint(
            f"canonical_format IN ({_CANONICAL_FORMATS_SQL})", name="ck_document_versions_format"
        ),
        sa.CheckConstraint(
            f"chunk_id_scheme IN ({_CHUNK_ID_SCHEMES_SQL})",
            name="ck_document_versions_chunk_scheme",
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_document_versions_number_min"),
        sa.CheckConstraint(
            "(version_number = 1 AND supersedes_version_id IS NULL) "
            "OR (version_number > 1 AND supersedes_version_id IS NOT NULL)",
            name="ck_document_versions_lineage",
        ),
        sa.CheckConstraint(
            "origin != 'patch' OR (source_checksum IS NOT NULL AND byte_size IS NOT NULL)",
            name="ck_document_versions_patch_bytes",
        ),
        sa.CheckConstraint(
            "(state IN ('ACTIVE', 'SUPERSEDED', 'ABANDONED') AND activation_token IS NULL) "
            "OR state IN ('PENDING_INDEX', 'INDEX_FAILED')",
            name="ck_document_versions_settled_no_token",
        ),
        sa.CheckConstraint(
            "(state = 'ABANDONED' AND abandoned_reason IS NOT NULL) "
            "OR (state != 'ABANDONED' AND abandoned_reason IS NULL)",
            name="ck_document_versions_abandoned_reason",
        ),
        sa.CheckConstraint(
            f"abandoned_reason IS NULL OR abandoned_reason IN ({_ABANDONED_REASONS_SQL})",
            name="ck_document_versions_abandoned_taxonomy",
        ),
        sa.CheckConstraint(
            "state != 'INDEX_FAILED' OR activation_error IS NOT NULL",
            name="ck_document_versions_index_failed_error",
        ),
        sa.CheckConstraint(
            "state NOT IN ('ACTIVE', 'SUPERSEDED') OR activation_error IS NULL",
            name="ck_document_versions_settled_no_error",
        ),
    )
    op.create_index(
        "uq_document_versions_one_active",
        "document_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.create_index(
        "uq_document_versions_live_text",
        "document_versions",
        ["document_id", "text_checksum"],
        unique=True,
        postgresql_where=sa.text("state != 'ABANDONED'"),
    )

    # documents: candidate key for the composite org FK, then the FK itself,
    # then the plain current_version_id column (its FK comes post-hoc).
    op.create_unique_constraint("uq_documents_org_id", "documents", ["organization_id", "id"])
    op.create_foreign_key(
        "fk_document_versions_org_document",
        "document_versions",
        "documents",
        ["organization_id", "document_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_document_versions_supersedes",
        "document_versions",
        "document_versions",
        ["document_id", "supersedes_version_id"],
        ["document_id", "id"],
    )
    op.add_column("documents", sa.Column("current_version_id", sa.String(36), nullable=True))

    # ---- backfill ---------------------------------------------------------
    from app.services.checksums import text_checksum  # canonical shared helper

    docs = bind.execute(
        sa.text(
            "SELECT id, organization_id, filename, content_type, checksum, "
            "parser_version FROM documents WHERE status = 'parsed'"
        )
    ).fetchall()
    for doc_id, org_id, filename, content_type, checksum, parser_version in docs:
        pages = [
            row[0]
            for row in bind.execute(
                sa.text(
                    "SELECT text FROM document_pages WHERE document_id = :d "
                    "ORDER BY page_number"
                ),
                {"d": doc_id},
            ).fetchall()
        ]
        version_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO document_versions (id, document_id, organization_id, "
                "version_number, state, source_checksum, text_checksum, "
                "parser_version, chunker_version, chunk_id_scheme, page_count, "
                "origin, canonical_format, filename, reported_mime, created_at) "
                "VALUES (:id, :doc, :org, 1, 'ACTIVE', :source, :text, :parser, "
                "'2', 'document_id_v2', :pages, 'upload', :fmt, :fn, :mime, now())"
            ),
            {
                "id": version_id,
                "doc": doc_id,
                "org": org_id,
                "source": checksum,
                "text": text_checksum(pages),
                "parser": parser_version or "",
                "pages": len(pages),
                "fmt": _canonical_format(filename),
                "fn": filename,
                "mime": content_type,
            },
        )
        bind.execute(
            sa.text("UPDATE documents SET current_version_id = :v WHERE id = :d"),
            {"v": version_id, "d": doc_id},
        )
    # Failed documents: clear the mirror — documents.checksum is henceforth
    # strictly the current version's source_checksum (raw-byte dedup / corpus
    # baseline), written only on successful parse.
    bind.execute(sa.text("UPDATE documents SET checksum = NULL WHERE status = 'failed'"))

    # ---- re-parent pages and chunks --------------------------------------
    for table in ("document_pages", "chunks"):
        op.add_column(table, sa.Column("document_version_id", sa.String(36), nullable=True))
        bind.execute(
            sa.text(
                f"UPDATE {table} t SET document_version_id = v.id "
                "FROM document_versions v WHERE v.document_id = t.document_id"
            )
        )
        op.alter_column(table, "document_version_id", nullable=False)
        op.create_index(f"ix_{table}_document_version_id", table, ["document_version_id"])
        op.create_foreign_key(
            f"fk_{table}_version",
            table,
            "document_versions",
            ["document_id", "document_version_id"],
            ["document_id", "id"],
            ondelete="CASCADE",
        )
    op.create_unique_constraint(
        "uq_document_pages_version_page", "document_pages",
        ["document_version_id", "page_number"],
    )

    # ---- patch_proposals ---------------------------------------------------
    op.create_table(
        "patch_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id", sa.String(36),
            sa.ForeignKey("remediation_cases.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "action_id", sa.String(36),
            sa.ForeignKey("remediation_actions.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("document_version_id", sa.String(36), nullable=False, index=True),
        sa.Column("base_text_checksum", sa.String(64), nullable=False),
        sa.Column("requirement_ids", sa.JSON(), nullable=False),
        sa.Column("requirements_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_action_review_count", sa.Integer(), nullable=False),
        sa.Column("input_plan_id", sa.String(36), nullable=False),
        sa.Column("input_case_evidence_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("drafting_token", sa.String(36), nullable=True),
        sa.Column("drafting_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drafting_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anchor_quote", sa.Text(), nullable=True),
        sa.Column("anchor_page", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(20), nullable=True),
        sa.Column("new_text_fr", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("abstain_reason", sa.String(30), nullable=True),
        sa.Column("verifier_errors", sa.JSON(), nullable=True),
        sa.Column("anchor_char_start", sa.Integer(), nullable=True),
        sa.Column("anchor_char_end", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id", "document_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_patch_proposals_version",
        ),
        *_lease_checks("patch_proposals"),
        sa.CheckConstraint(
            "operation IS NULL OR operation IN ('insert_after', 'replace')",
            name="ck_patch_proposals_operation",
        ),
        sa.CheckConstraint(
            "(status = 'VERIFIED' AND anchor_quote IS NOT NULL AND anchor_page IS NOT NULL "
            "AND operation IS NOT NULL AND new_text_fr IS NOT NULL "
            "AND anchor_char_start IS NOT NULL AND anchor_char_end IS NOT NULL) "
            "OR (status != 'VERIFIED' AND anchor_char_start IS NULL AND anchor_char_end IS NULL)",
            name="ck_patch_proposals_output_coherence",
        ),
    )

    # ---- patch_decisions ---------------------------------------------------
    op.create_table(
        "patch_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "proposal_id", sa.String(36),
            sa.ForeignKey("patch_proposals.id", ondelete="CASCADE"),
            nullable=False, unique=True,
        ),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("final_text_fr", sa.Text(), nullable=True),
        sa.Column("final_text_checksum", sa.String(64), nullable=True),
        sa.Column(
            "result_version_id", sa.String(36),
            sa.ForeignKey("document_versions.id"), nullable=True, unique=True,
        ),
        sa.Column("actor_label", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approve', 'edit', 'reject')", name="ck_patch_decisions_kind"
        ),
        sa.CheckConstraint(
            "(decision = 'reject' AND final_text_fr IS NULL "
            "AND final_text_checksum IS NULL AND result_version_id IS NULL) "
            "OR (decision != 'reject' AND final_text_fr IS NOT NULL "
            "AND final_text_checksum IS NOT NULL AND result_version_id IS NOT NULL)",
            name="ck_patch_decisions_coherence",
        ),
    )

    # ---- remediation_artifacts ---------------------------------------------
    op.create_table(
        "remediation_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id", sa.String(36),
            sa.ForeignKey("remediation_cases.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "action_id", sa.String(36),
            sa.ForeignKey("remediation_actions.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("document_version_id", sa.String(36), nullable=False, index=True),
        sa.Column("base_text_checksum", sa.String(64), nullable=False),
        sa.Column("canonical_format", sa.String(10), nullable=False),
        sa.Column("requirement_ids", sa.JSON(), nullable=False),
        sa.Column("requirements_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_action_review_count", sa.Integer(), nullable=False),
        sa.Column("input_plan_id", sa.String(36), nullable=False),
        sa.Column("input_case_evidence_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("drafting_token", sa.String(36), nullable=True),
        sa.Column("drafting_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drafting_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filename", sa.String(300), nullable=True),
        sa.Column("content_md", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("abstain_reason", sa.String(30), nullable=True),
        sa.Column("verifier_errors", sa.JSON(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id", "document_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_remediation_artifacts_version",
        ),
        *_lease_checks("remediation_artifacts"),
        sa.CheckConstraint(
            "(status = 'VERIFIED' AND content_md IS NOT NULL) OR status != 'VERIFIED'",
            name="ck_remediation_artifacts_output_coherence",
        ),
    )

    # ---- document_version_events -------------------------------------------
    op.create_table(
        "document_version_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id", sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "payload_version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("actor_label", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "sequence", name="uq_document_version_events_seq"),
        sa.CheckConstraint(
            f"event_type IN ({_VERSION_EVENT_TYPES_SQL})",
            name="ck_document_version_events_type",
        ),
    )

    # ---- circular FKs (post-creation, 0013 pattern) -------------------------
    op.create_foreign_key(
        "fk_documents_current_version",
        "documents",
        "document_versions",
        ["id", "current_version_id"],
        ["document_id", "id"],
    )
    op.create_foreign_key(
        "fk_document_versions_source_artifact",
        "document_versions",
        "remediation_artifacts",
        ["source_artifact_id"],
        ["id"],
        # RESTRICT: corrective-action lineage is durable — an artifact cited
        # by a version cannot be deleted out from under it.
        ondelete="RESTRICT",
    )

    # ---- remediation_attempts: stages 'patch' / 'artifact' ------------------
    op.add_column(
        "remediation_attempts",
        sa.Column(
            "patch_proposal_id", sa.String(36),
            sa.ForeignKey("patch_proposals.id", ondelete="CASCADE"), nullable=True,
        ),
    )
    op.add_column(
        "remediation_attempts",
        sa.Column(
            "remediation_artifact_id", sa.String(36),
            sa.ForeignKey("remediation_artifacts.id", ondelete="CASCADE"), nullable=True,
        ),
    )
    op.drop_constraint("ck_remediation_attempts_stage", "remediation_attempts", type_="check")
    op.create_check_constraint(
        "ck_remediation_attempts_stage",
        "remediation_attempts",
        "stage IN ('triage', 'plan', 'patch', 'artifact')",
    )
    op.drop_constraint(
        "ck_remediation_attempts_stage_coherence", "remediation_attempts", type_="check"
    )
    op.create_check_constraint(
        "ck_remediation_attempts_stage_coherence",
        "remediation_attempts",
        _NEW_STAGE_COHERENCE_SQL,
    )
    op.create_index(
        "uq_remediation_attempts_patch",
        "remediation_attempts",
        ["patch_proposal_id", "attempt_number"],
        unique=True,
        postgresql_where=sa.text("patch_proposal_id IS NOT NULL"),
    )
    op.create_index(
        "uq_remediation_attempts_artifact",
        "remediation_attempts",
        ["remediation_artifact_id", "attempt_number"],
        unique=True,
        postgresql_where=sa.text("remediation_artifact_id IS NOT NULL"),
    )

    # ---- remediation_events: new case-scoped types ---------------------------
    op.drop_constraint("ck_remediation_events_type", "remediation_events", type_="check")
    op.create_check_constraint(
        "ck_remediation_events_type",
        "remediation_events",
        f"event_type IN ({_NEW_EVENT_TYPES_SQL})",
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Version history is provenance: a downgrade that dropped non-current
    # versions would destroy exactly what M7b establishes. Refuse outright.
    multi = bind.execute(
        sa.text(
            "SELECT document_id FROM document_versions "
            "GROUP BY document_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).fetchone()
    if multi:
        raise RuntimeError(
            "downgrade 0014 refused: document "
            f"{multi[0]} has version history; dropping it would destroy "
            "citation provenance. Export/archive versions first."
        )
    rem_rows = bind.execute(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM patch_proposals) "
            "+ (SELECT COUNT(*) FROM remediation_artifacts)"
        )
    ).scalar()
    if rem_rows:
        raise RuntimeError(
            "downgrade 0014 refused: patch proposals or artifacts exist; "
            "their lineage cannot survive the un-versioned schema."
        )

    op.drop_constraint("ck_remediation_events_type", "remediation_events", type_="check")
    op.create_check_constraint(
        "ck_remediation_events_type",
        "remediation_events",
        f"event_type IN ({_OLD_EVENT_TYPES_SQL})",
    )
    op.drop_index("uq_remediation_attempts_artifact", table_name="remediation_attempts")
    op.drop_index("uq_remediation_attempts_patch", table_name="remediation_attempts")
    op.drop_constraint(
        "ck_remediation_attempts_stage_coherence", "remediation_attempts", type_="check"
    )
    op.create_check_constraint(
        "ck_remediation_attempts_stage_coherence",
        "remediation_attempts",
        _OLD_STAGE_COHERENCE_SQL,
    )
    op.drop_constraint("ck_remediation_attempts_stage", "remediation_attempts", type_="check")
    op.create_check_constraint(
        "ck_remediation_attempts_stage",
        "remediation_attempts",
        "stage IN ('triage', 'plan')",
    )
    op.drop_column("remediation_attempts", "remediation_artifact_id")
    op.drop_column("remediation_attempts", "patch_proposal_id")

    op.drop_constraint(
        "fk_document_versions_source_artifact", "document_versions", type_="foreignkey"
    )
    op.drop_constraint("fk_documents_current_version", "documents", type_="foreignkey")
    op.drop_table("document_version_events")
    op.drop_table("remediation_artifacts")
    op.drop_table("patch_decisions")
    op.drop_table("patch_proposals")

    op.drop_constraint("uq_document_pages_version_page", "document_pages", type_="unique")
    for table in ("chunks", "document_pages"):
        op.drop_constraint(f"fk_{table}_version", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_document_version_id", table_name=table)
        op.drop_column(table, "document_version_id")

    op.drop_column("documents", "current_version_id")
    op.drop_table("document_versions")
    op.drop_constraint("uq_documents_org_id", "documents", type_="unique")
    # NOTE: failed-document mirror checksums cleared on upgrade are NOT
    # restorable (accepted data loss, documented behavior change).
