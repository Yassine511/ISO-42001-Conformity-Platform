"""M7a remediation planning agent — ten new tables, no existing table touched.

- remediation_cases: human triage projection + active_plan_id (sole plan
  authority) + evidence_revision (stale-input protection) + PLANNING lease.
- remediation_triage_drafts / remediation_plans: append-only AI proposals with
  input snapshots; plans add VERIFIED/ABSTAINED -> SUPERSEDED.
- remediation_case_findings: link rows with finding review snapshots
  (gap verdicts only, DB-enforced).
- remediation_actions (+ remediation_action_requirements): write-once AI
  columns vs human review projection; effective requirement scope is
  human-approved and separate from the AI proposal.
- remediation_reassessments: append-only launch records with pre-generated
  planned_assessment_id (crash reconciliation).
- remediation_events: append-only case audit trail.
- remediation_attempts + remediation_llm_calls: provenance pair mirroring
  assessment_attempts/llm_calls (chat precedent, 0009).

Circular FKs (cases.approved_triage_draft_id -> remediation_triage_drafts,
cases.active_plan_id -> remediation_plans) are added AFTER all tables exist
and dropped first on downgrade. The ORM leaves these two as plain columns
(SQLite create_all cannot ALTER-add constraints).

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_ABSTAIN_SQL = (
    "'schema_invalid', 'verification_failed', 'llm_error', 'rate_limited', "
    "'retrieval_error', 'draft_interrupted'"
)

_EVENT_TYPES_SQL = (
    "'case_created', 'finding_linked', 'finding_link_rejected', 'finding_unlinked', "
    "'triage_drafted', 'triage_approved', 'triage_reopened', 'plan_draft_started', "
    "'plan_drafted', 'plan_abstained', 'plan_superseded', 'plan_draft_recovered', "
    "'action_reviewed', 'lifecycle_changed', 'reassessment_launched', "
    "'effectiveness_recorded', 'case_closed', 'case_reopened'"
)


def upgrade() -> None:
    op.create_table(
        "remediation_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default=sa.text("'TRIAGE'")
        ),
        sa.Column("classification", sa.String(40), nullable=True),
        sa.Column("correction_note", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(30), nullable=True),
        sa.Column("scope_rationale", sa.Text(), nullable=True),
        sa.Column("triage_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triage_reviewer_label", sa.String(200), nullable=True),
        # FKs added post-creation (circular)
        sa.Column("approved_triage_draft_id", sa.String(36), nullable=True),
        sa.Column("active_plan_id", sa.String(36), nullable=True),
        sa.Column(
            "evidence_revision", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("planning_token", sa.String(36), nullable=True),
        sa.Column("planning_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planning_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('TRIAGE', 'TRIAGE_APPROVED', 'PLANNING', 'PLAN_READY', "
            "'IN_PROGRESS', 'CLOSED')",
            name="ck_remediation_cases_status",
        ),
        sa.CheckConstraint(
            "classification IS NULL OR classification IN "
            "('evidence_gap', 'observation', 'improvement_opportunity', 'nonconformity')",
            name="ck_remediation_cases_classification",
        ),
        sa.CheckConstraint(
            "scope IS NULL OR scope IN "
            "('local', 'related_requirements', 'organization_wide')",
            name="ck_remediation_cases_scope",
        ),
        sa.CheckConstraint(
            "(status = 'TRIAGE' AND classification IS NULL AND scope IS NULL "
            "AND scope_rationale IS NULL AND triage_approved_at IS NULL "
            "AND approved_triage_draft_id IS NULL) "
            "OR (status != 'TRIAGE' AND classification IS NOT NULL "
            "AND scope IS NOT NULL AND scope_rationale IS NOT NULL "
            "AND triage_approved_at IS NOT NULL)",
            name="ck_remediation_cases_triage_coherence",
        ),
        sa.CheckConstraint(
            "(status = 'CLOSED' AND closed_at IS NOT NULL AND close_note IS NOT NULL) "
            "OR (status != 'CLOSED' AND closed_at IS NULL AND close_note IS NULL)",
            name="ck_remediation_cases_closed_coherence",
        ),
        sa.CheckConstraint(
            "(status = 'PLANNING' AND planning_token IS NOT NULL "
            "AND planning_started_at IS NOT NULL AND planning_heartbeat_at IS NOT NULL) "
            "OR (status != 'PLANNING' AND planning_token IS NULL "
            "AND planning_started_at IS NULL AND planning_heartbeat_at IS NULL)",
            name="ck_remediation_cases_lease_coherence",
        ),
    )

    op.create_table(
        "remediation_triage_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("remediation_cases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("abstain_reason", sa.String(50), nullable=True),
        sa.Column("ai_classification", sa.String(40), nullable=True),
        sa.Column("ai_correction_note", sa.Text(), nullable=True),
        sa.Column("ai_scope", sa.String(30), nullable=True),
        sa.Column("ai_scope_rationale", sa.Text(), nullable=True),
        sa.Column("raw_draft", sa.Text(), nullable=True),
        sa.Column("input_evidence_revision", sa.Integer(), nullable=False),
        sa.Column("input_finding_links", sa.JSON(), nullable=False),
        sa.Column("similar_findings", sa.JSON(), nullable=False),
        sa.Column("similar_corpus", sa.JSON(), nullable=False),
        sa.Column("draft_attempts", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("corpus_version", sa.String(20), nullable=False),
        sa.Column("final_model", sa.Text(), nullable=True),
        sa.Column("final_provider", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "case_id", "sequence", name="uq_remediation_triage_drafts_sequence"
        ),
        sa.CheckConstraint(
            "status IN ('VERIFIED', 'ABSTAINED')",
            name="ck_remediation_triage_drafts_status",
        ),
        sa.CheckConstraint(
            f"abstain_reason IS NULL OR abstain_reason IN ({_ABSTAIN_SQL})",
            name="ck_remediation_triage_drafts_abstain_reason",
        ),
        sa.CheckConstraint(
            "ai_classification IS NULL OR ai_classification IN "
            "('evidence_gap', 'observation', 'improvement_opportunity', 'nonconformity')",
            name="ck_remediation_triage_drafts_classification",
        ),
        sa.CheckConstraint(
            "ai_scope IS NULL OR ai_scope IN "
            "('local', 'related_requirements', 'organization_wide')",
            name="ck_remediation_triage_drafts_scope",
        ),
        sa.CheckConstraint(
            "(status = 'VERIFIED' AND abstain_reason IS NULL "
            "AND ai_classification IS NOT NULL AND ai_correction_note IS NOT NULL "
            "AND ai_scope IS NOT NULL AND ai_scope_rationale IS NOT NULL) "
            "OR (status = 'ABSTAINED' AND abstain_reason IS NOT NULL)",
            name="ck_remediation_triage_drafts_coherence",
        ),
        sa.CheckConstraint(
            "draft_attempts >= 0 AND draft_attempts <= 2",
            name="ck_remediation_triage_drafts_attempts",
        ),
    )

    op.create_table(
        "remediation_case_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("remediation_cases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "finding_id",
            sa.String(36),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("link_source", sa.String(20), nullable=False),
        sa.Column("link_note", sa.Text(), nullable=True),
        sa.Column("linker_label", sa.String(200), nullable=True),
        sa.Column("finding_review_count", sa.Integer(), nullable=False),
        sa.Column("finding_human_verdict", sa.String(20), nullable=False),
        sa.Column("finding_human_rationale", sa.Text(), nullable=True),
        sa.Column("finding_requirement_id", sa.String(20), nullable=False),
        sa.Column("finding_requirement_fr", sa.Text(), nullable=True),
        sa.Column("finding_domain", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "case_id", "finding_id", name="uq_remediation_case_findings_pair"
        ),
        sa.CheckConstraint(
            "link_source IN ('creation', 'search_suggested', 'manual')",
            name="ck_remediation_case_findings_source",
        ),
        sa.CheckConstraint(
            "finding_human_verdict IN ('partial', 'non_compliant', 'missing')",
            name="ck_remediation_case_findings_verdict",
        ),
    )
    op.create_index(
        "uq_remediation_case_findings_primary",
        "remediation_case_findings",
        ["case_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        sqlite_where=sa.text("is_primary"),
    )

    op.create_table(
        "remediation_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("remediation_cases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("abstain_reason", sa.String(50), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "superseded_by_plan_id",
            sa.String(36),
            sa.ForeignKey("remediation_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("gap_restatement", sa.Text(), nullable=True),
        sa.Column("root_cause_hypotheses", sa.JSON(), nullable=True),
        sa.Column("raw_draft", sa.Text(), nullable=True),
        sa.Column("draft_attempts", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("corpus_version", sa.String(20), nullable=False),
        sa.Column("final_model", sa.Text(), nullable=True),
        sa.Column("final_provider", sa.String(20), nullable=True),
        sa.Column("retrieved", sa.JSON(), nullable=False),
        sa.Column("input_finding_links", sa.JSON(), nullable=False),
        sa.Column("input_triage_snapshot", sa.JSON(), nullable=False),
        sa.Column("allowed_requirement_ids", sa.JSON(), nullable=False),
        sa.Column("input_kb", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "sequence", name="uq_remediation_plans_sequence"),
        sa.CheckConstraint(
            "status IN ('VERIFIED', 'ABSTAINED', 'SUPERSEDED')",
            name="ck_remediation_plans_status",
        ),
        sa.CheckConstraint(
            f"abstain_reason IS NULL OR abstain_reason IN ({_ABSTAIN_SQL})",
            name="ck_remediation_plans_abstain_reason",
        ),
        sa.CheckConstraint(
            "(status = 'VERIFIED' AND abstain_reason IS NULL "
            "AND gap_restatement IS NOT NULL AND root_cause_hypotheses IS NOT NULL "
            "AND raw_draft IS NOT NULL) "
            "OR (status = 'ABSTAINED' AND abstain_reason IS NOT NULL) "
            "OR (status = 'SUPERSEDED')",
            name="ck_remediation_plans_coherence",
        ),
        sa.CheckConstraint(
            "(status = 'SUPERSEDED' AND superseded_at IS NOT NULL) "
            "OR (status != 'SUPERSEDED' AND superseded_at IS NULL "
            "AND superseded_by_plan_id IS NULL)",
            name="ck_remediation_plans_superseded_coherence",
        ),
        sa.CheckConstraint(
            "draft_attempts >= 0 AND draft_attempts <= 2",
            name="ck_remediation_plans_attempts",
        ),
    )

    op.create_table(
        "remediation_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("remediation_plans.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("ai_description", sa.Text(), nullable=False),
        sa.Column("ai_rationale", sa.Text(), nullable=False),
        sa.Column("ai_owner_role", sa.Text(), nullable=False),
        sa.Column("ai_success_criterion", sa.Text(), nullable=False),
        sa.Column("ai_impacted_requirement_ids", sa.JSON(), nullable=False),
        sa.Column("policy_quote", sa.Text(), nullable=True),
        sa.Column("matched_chunk_id", sa.String(64), nullable=True),
        sa.Column("match_start", sa.Integer(), nullable=True),
        sa.Column("match_end", sa.Integer(), nullable=True),
        sa.Column("match_method", sa.String(10), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column(
            "review_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("review_action", sa.String(20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("owner_role", sa.Text(), nullable=True),
        sa.Column("success_criterion", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(10), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewer_label", sa.String(200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "review_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "lifecycle",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'PROPOSED'"),
        ),
        sa.Column(
            "effectiveness",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'NOT_CHECKED'"),
        ),
        sa.Column("effectiveness_note", sa.Text(), nullable=True),
        sa.Column("effectiveness_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("plan_id", "position", name="uq_remediation_actions_position"),
        sa.CheckConstraint(
            "action_type IN ('document_amendment', 'new_document', 'process_change', "
            "'training', 'risk_treatment_update', 'other')",
            name="ck_remediation_actions_type",
        ),
        sa.CheckConstraint(
            "review_status IN ('PENDING', 'CONFIRMED')",
            name="ck_remediation_actions_review_status",
        ),
        sa.CheckConstraint(
            "review_action IS NULL OR review_action IN ('approve', 'edit', 'reject')",
            name="ck_remediation_actions_review_action",
        ),
        sa.CheckConstraint(
            "priority IS NULL OR priority IN ('haute', 'normale', 'basse')",
            name="ck_remediation_actions_priority",
        ),
        sa.CheckConstraint(
            "lifecycle IN ('PROPOSED', 'APPROVED', 'REJECTED', 'IN_PROGRESS', "
            "'DONE', 'CANCELLED')",
            name="ck_remediation_actions_lifecycle",
        ),
        sa.CheckConstraint(
            "effectiveness IN ('NOT_CHECKED', 'EFFECTIVE', 'PARTIALLY_EFFECTIVE', "
            "'INEFFECTIVE')",
            name="ck_remediation_actions_effectiveness",
        ),
        sa.CheckConstraint(
            "(policy_quote IS NULL AND matched_chunk_id IS NULL "
            "AND match_start IS NULL AND match_end IS NULL "
            "AND match_method IS NULL AND match_score IS NULL) "
            "OR (policy_quote IS NOT NULL AND matched_chunk_id IS NOT NULL "
            "AND match_start IS NOT NULL AND match_end IS NOT NULL "
            "AND match_method = 'exact' AND match_score IS NOT NULL)",
            name="ck_remediation_actions_quote_coherence",
        ),
        sa.CheckConstraint(
            "(review_status = 'PENDING' AND review_action IS NULL "
            "AND description IS NULL AND rationale IS NULL AND owner_role IS NULL "
            "AND success_criterion IS NULL AND priority IS NULL "
            "AND reviewed_at IS NULL AND lifecycle = 'PROPOSED') "
            "OR (review_status = 'CONFIRMED' AND review_action IN ('approve', 'edit') "
            "AND description IS NOT NULL AND rationale IS NOT NULL "
            "AND owner_role IS NOT NULL AND success_criterion IS NOT NULL "
            "AND priority IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND lifecycle NOT IN ('PROPOSED', 'REJECTED')) "
            "OR (review_status = 'CONFIRMED' AND review_action = 'reject' "
            "AND description IS NULL AND rationale IS NULL AND owner_role IS NULL "
            "AND success_criterion IS NULL AND priority IS NULL "
            "AND reviewed_at IS NOT NULL AND lifecycle = 'REJECTED')",
            name="ck_remediation_actions_review_coherence",
        ),
        sa.CheckConstraint(
            "(effectiveness = 'NOT_CHECKED' AND effectiveness_note IS NULL "
            "AND effectiveness_recorded_at IS NULL) "
            "OR (effectiveness != 'NOT_CHECKED' AND effectiveness_note IS NOT NULL "
            "AND effectiveness_recorded_at IS NOT NULL)",
            name="ck_remediation_actions_effectiveness_coherence",
        ),
    )

    op.create_table(
        "remediation_action_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "action_id",
            sa.String(36),
            sa.ForeignKey("remediation_actions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("requirement_id", sa.String(20), nullable=False),
        sa.Column("requirement_fr", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "action_id", "requirement_id", name="uq_remediation_action_requirements_pair"
        ),
    )

    op.create_table(
        "remediation_reassessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("remediation_cases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("planned_assessment_id", sa.String(36), nullable=False),
        sa.Column(
            "assessment_id",
            sa.String(36),
            sa.ForeignKey("assessments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("selected_action_ids", sa.JSON(), nullable=False),
        sa.Column("included_requirement_ids", sa.JSON(), nullable=False),
        sa.Column("excluded_holdout_ids", sa.JSON(), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default=sa.text("'PENDING'")
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("actor_label", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "planned_assessment_id", name="uq_remediation_reassessments_planned"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'LAUNCHED', 'LAUNCH_FAILED')",
            name="ck_remediation_reassessments_status",
        ),
    )

    op.create_table(
        "remediation_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("remediation_cases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "payload_version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("actor_label", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "sequence", name="uq_remediation_events_sequence"),
        sa.CheckConstraint(
            f"event_type IN ({_EVENT_TYPES_SQL})",
            name="ck_remediation_events_type",
        ),
    )

    op.create_table(
        "remediation_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("remediation_cases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("stage", sa.String(10), nullable=False),
        sa.Column(
            "triage_draft_id",
            sa.String(36),
            sa.ForeignKey("remediation_triage_drafts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("remediation_plans.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("parsed_ok", sa.Boolean(), nullable=False),
        sa.Column("verifier_errors", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "stage IN ('triage', 'plan')", name="ck_remediation_attempts_stage"
        ),
        sa.CheckConstraint(
            "(stage = 'triage' AND triage_draft_id IS NOT NULL AND plan_id IS NULL) "
            "OR (stage = 'plan' AND plan_id IS NOT NULL AND triage_draft_id IS NULL)",
            name="ck_remediation_attempts_stage_coherence",
        ),
    )
    op.create_index(
        "uq_remediation_attempts_triage",
        "remediation_attempts",
        ["triage_draft_id", "attempt_number"],
        unique=True,
        postgresql_where=sa.text("triage_draft_id IS NOT NULL"),
        sqlite_where=sa.text("triage_draft_id IS NOT NULL"),
    )
    op.create_index(
        "uq_remediation_attempts_plan",
        "remediation_attempts",
        ["plan_id", "attempt_number"],
        unique=True,
        postgresql_where=sa.text("plan_id IS NOT NULL"),
        sqlite_where=sa.text("plan_id IS NOT NULL"),
    )

    op.create_table(
        "remediation_llm_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "remediation_attempt_id",
            sa.String(36),
            sa.ForeignKey("remediation_attempts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("call_number", sa.Integer(), nullable=False),
        sa.Column(
            "prompt_version", sa.String(20), nullable=False, server_default=sa.text("''")
        ),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("requested_model", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reported_model", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("request_messages", sa.JSON(), nullable=False),
        sa.Column("response_format", sa.JSON(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "remediation_attempt_id", "call_number", name="uq_remediation_llm_calls_key"
        ),
        sa.CheckConstraint(
            "status IN ('SUCCESS', 'HTTP_ERROR', 'NETWORK_ERROR', 'BAD_RESPONSE', "
            "'SKIPPED_NO_KEY')",
            name="ck_remediation_llm_calls_status",
        ),
    )

    # Circular FKs — added after every table exists (Postgres; the ORM keeps
    # these as plain columns so SQLite create_all works).
    op.create_foreign_key(
        "fk_remediation_cases_approved_triage_draft",
        "remediation_cases",
        "remediation_triage_drafts",
        ["approved_triage_draft_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_remediation_cases_active_plan",
        "remediation_cases",
        "remediation_plans",
        ["active_plan_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # circular FKs first
    op.drop_constraint(
        "fk_remediation_cases_active_plan", "remediation_cases", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_remediation_cases_approved_triage_draft",
        "remediation_cases",
        type_="foreignkey",
    )
    op.drop_table("remediation_llm_calls")
    op.drop_index("uq_remediation_attempts_plan", table_name="remediation_attempts")
    op.drop_index("uq_remediation_attempts_triage", table_name="remediation_attempts")
    op.drop_table("remediation_attempts")
    op.drop_table("remediation_events")
    op.drop_table("remediation_reassessments")
    op.drop_table("remediation_action_requirements")
    op.drop_table("remediation_actions")
    op.drop_table("remediation_plans")
    op.drop_index(
        "uq_remediation_case_findings_primary", table_name="remediation_case_findings"
    )
    op.drop_table("remediation_case_findings")
    op.drop_table("remediation_triage_drafts")
    op.drop_table("remediation_cases")
