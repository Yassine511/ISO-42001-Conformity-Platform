"""Remediation operations: human case-planning fields + action deadline.

Case level (all nullable — existing records stay NULL, no fake backfill):
owner_role / due_date / closure_criterion are HUMAN operational metadata the
UI previously had to render as « Non attribué » / « À définir » / « Non
renseigné ». planning_revision (default 0) is an optimistic-concurrency
counter: the planning-update endpoint requires the client to send the
revision it read, so two editors can never silently overwrite each other.
planning_updated_at / planning_editor_label record the last edit (the label
is free text, EXPLICITLY UNVERIFIED — no identity layer by design).

Action level: due_date (nullable) — human-set, never LLM-invented; the
lifecycle endpoint now requires it (with owner_role / description /
success_criterion / priority) before an action may move to IN_PROGRESS.

Every planning change is audited through the append-only
remediation_events stream (event_type case_planning_updated).

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

# ck_remediation_events_type must admit the new event type (0014 pattern:
# drop + recreate with the widened list).
_OLD_EVENT_TYPES = (
    "case_created",
    "finding_linked",
    "finding_link_rejected",
    "finding_unlinked",
    "triage_drafted",
    "triage_approved",
    "triage_reopened",
    "plan_draft_started",
    "plan_drafted",
    "plan_abstained",
    "plan_superseded",
    "plan_draft_recovered",
    "action_reviewed",
    "lifecycle_changed",
    "reassessment_launched",
    "effectiveness_recorded",
    "case_closed",
    "case_reopened",
    "patch_proposed",
    "patch_abstained",
    "patch_approved",
    "patch_rejected",
    "patch_activation_abandoned",
    "artifact_created",
    "artifact_abstained",
    "version_superseded_by_upload",
)
_NEW_EVENT_TYPES = _OLD_EVENT_TYPES + ("case_planning_updated",)
_OLD_EVENT_TYPES_SQL = ", ".join(f"'{t}'" for t in _OLD_EVENT_TYPES)
_NEW_EVENT_TYPES_SQL = ", ".join(f"'{t}'" for t in _NEW_EVENT_TYPES)


def upgrade() -> None:
    op.add_column("remediation_cases", sa.Column("owner_role", sa.Text(), nullable=True))
    op.add_column("remediation_cases", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column(
        "remediation_cases", sa.Column("closure_criterion", sa.Text(), nullable=True)
    )
    op.add_column(
        "remediation_cases",
        sa.Column(
            "planning_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "remediation_cases",
        sa.Column("planning_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "remediation_cases",
        sa.Column("planning_editor_label", sa.String(200), nullable=True),
    )
    op.add_column("remediation_actions", sa.Column("due_date", sa.Date(), nullable=True))
    op.drop_constraint("ck_remediation_events_type", "remediation_events", type_="check")
    op.create_check_constraint(
        "ck_remediation_events_type",
        "remediation_events",
        f"event_type IN ({_NEW_EVENT_TYPES_SQL})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_remediation_events_type", "remediation_events", type_="check")
    op.create_check_constraint(
        "ck_remediation_events_type",
        "remediation_events",
        f"event_type IN ({_OLD_EVENT_TYPES_SQL})",
    )
    op.drop_column("remediation_actions", "due_date")
    op.drop_column("remediation_cases", "planning_editor_label")
    op.drop_column("remediation_cases", "planning_updated_at")
    op.drop_column("remediation_cases", "planning_revision")
    op.drop_column("remediation_cases", "closure_criterion")
    op.drop_column("remediation_cases", "due_date")
    op.drop_column("remediation_cases", "owner_role")
