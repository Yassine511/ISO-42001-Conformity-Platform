"""Versioned, typed payload schemas for remediation_events (M7a).

Every append to remediation_events validates its payload against the schema
registered for the event type and stamps PAYLOAD_VERSION. Mutation events
carry full before/after values so the audit trail reconstructs history
without diffing table state. actor_label lives on the event row itself and
is free-text, EXPLICITLY UNVERIFIED (no identity layer by design).

Bump PAYLOAD_VERSION and keep the old model readable whenever a payload
shape changes — replay of historical events must keep validating.
"""

from pydantic import BaseModel, ConfigDict

PAYLOAD_VERSION = 1


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindingSnapshot(_Payload):
    """Finding review state as recorded on the link row."""

    finding_id: str
    is_primary: bool
    link_source: str
    finding_review_count: int
    finding_human_verdict: str
    finding_human_rationale: str | None = None
    finding_requirement_id: str
    finding_requirement_fr: str | None = None
    finding_domain: str | None = None


class TriageProjection(_Payload):
    """Human triage projection values (cleared/set on the case)."""

    classification: str | None = None
    correction_note: str | None = None
    scope: str | None = None
    scope_rationale: str | None = None
    triage_approved_at: str | None = None
    triage_reviewer_label: str | None = None
    approved_triage_draft_id: str | None = None


class TriageEffective(_Payload):
    """Effective human-approved triage fields written at approval."""

    classification: str
    correction_note: str | None = None
    scope: str
    scope_rationale: str


class ActionProjection(_Payload):
    """Action review projection before/after one review decision.

    due_date (0018) is additive and optional: historical payloads without the
    key keep validating unchanged — no PAYLOAD_VERSION bump needed."""

    review_status: str
    review_action: str | None = None
    description: str | None = None
    rationale: str | None = None
    owner_role: str | None = None
    success_criterion: str | None = None
    priority: str | None = None
    due_date: str | None = None  # ISO date, human-set
    lifecycle: str
    effective_requirement_ids: list[str]


class EffectivenessState(_Payload):
    effectiveness: str
    effectiveness_note: str | None = None


class CaseCreated(_Payload):
    finding_id: str
    title: str


class FindingLinked(_Payload):
    finding_id: str
    link_source: str
    is_primary: bool
    # finding review snapshot recorded on the link row (duplicated here so
    # the event stream alone reconstructs the case basis)
    snapshot: FindingSnapshot


class FindingLinkRejected(_Payload):
    finding_id: str
    note: str | None = None


class FindingUnlinked(_Payload):
    finding_id: str
    snapshot: FindingSnapshot


class TriageDrafted(_Payload):
    triage_draft_id: str
    sequence: int
    status: str
    abstain_reason: str | None = None
    input_evidence_revision: int


class TriageApproved(_Payload):
    triage_draft_id: str
    # effective human-approved projection written to the case
    after: TriageEffective
    # fields where the human overrode the AI draft
    overridden_fields: list[str]


class TriageReopened(_Payload):
    # cleared projection values (preserved history)
    before: TriageProjection
    superseded_plan_id: str | None = None


class PlanDraftStarted(_Payload):
    planning_token: str
    evidence_revision: int


class PlanDrafted(_Payload):
    plan_id: str
    sequence: int
    action_count: int
    activated: bool


class PlanAbstained(_Payload):
    plan_id: str
    sequence: int
    abstain_reason: str
    activated: bool


class PlanSuperseded(_Payload):
    plan_id: str
    superseded_by_plan_id: str | None = None
    cause: str  # 'replacement' | 'triage_reopen'


class PlanDraftRecovered(_Payload):
    plan_id: str
    previous_active_plan_id: str | None = None


class ActionReviewed(_Payload):
    action_id: str
    review_action: str
    before: ActionProjection
    after: ActionProjection
    effective_requirement_ids: list[str]
    # True when the effective scope differs from the AI proposal
    requirement_override: bool


class LifecycleChanged(_Payload):
    action_id: str
    before: str
    after: str


class ReassessmentLaunched(_Payload):
    reassessment_id: str
    planned_assessment_id: str
    assessment_id: str | None = None
    selected_action_ids: list[str]
    included_requirement_ids: list[str]
    excluded_holdout_ids: list[str]
    status: str


class EffectivenessRecorded(_Payload):
    action_id: str
    before: EffectivenessState
    after: EffectivenessState
    reassessment_id: str | None = None


class CasePlanningState(_Payload):
    """Human case-planning fields (0018) — owner/deadline/closure criterion."""

    owner_role: str | None = None
    due_date: str | None = None  # ISO date
    closure_criterion: str | None = None


class CasePlanningUpdated(_Payload):
    """One optimistic-revision planning edit; full before/after values."""

    before: CasePlanningState
    after: CasePlanningState
    planning_revision: int  # the NEW revision after this edit


class CaseClosed(_Payload):
    close_note: str
    from_status: str


class CaseReopened(_Payload):
    previous_close_note: str
    previous_closed_at: str
    restored_status: str


# ------------------------------------------------------------------ M7b patch
# Case-scoped view of the patch/artifact flow. The generic version lifecycle
# additionally lands in document_version_events; these payloads reference the
# version ids so both streams correlate.


class PatchProposed(_Payload):
    proposal_id: str
    action_id: str
    document_id: str
    document_version_id: str
    operation: str
    anchor_page: int
    attempts: int


class PatchAbstained(_Payload):
    proposal_id: str
    action_id: str
    abstain_reason: str
    attempts: int


class PatchApproved(_Payload):
    proposal_id: str
    decision_id: str
    decision: str  # 'approve' | 'edit'
    document_id: str
    base_version_id: str
    result_version_id: str


class PatchRejected(_Payload):
    proposal_id: str
    decision_id: str


class PatchActivationAbandoned(_Payload):
    document_id: str
    version_id: str
    abandoned_reason: str
    proposal_id: str | None = None
    artifact_id: str | None = None


class ArtifactCreated(_Payload):
    artifact_id: str
    action_id: str
    document_id: str
    document_version_id: str
    filename: str
    attempts: int


class ArtifactAbstained(_Payload):
    artifact_id: str
    action_id: str
    abstain_reason: str
    attempts: int


class VersionSupersededByUpload(_Payload):
    artifact_id: str
    document_id: str
    superseded_version_id: str
    new_version_id: str
    document_version_event_id: str


PAYLOAD_SCHEMAS: dict[str, type[_Payload]] = {
    "case_created": CaseCreated,
    "finding_linked": FindingLinked,
    "finding_link_rejected": FindingLinkRejected,
    "finding_unlinked": FindingUnlinked,
    "triage_drafted": TriageDrafted,
    "triage_approved": TriageApproved,
    "triage_reopened": TriageReopened,
    "plan_draft_started": PlanDraftStarted,
    "plan_drafted": PlanDrafted,
    "plan_abstained": PlanAbstained,
    "plan_superseded": PlanSuperseded,
    "plan_draft_recovered": PlanDraftRecovered,
    "action_reviewed": ActionReviewed,
    "lifecycle_changed": LifecycleChanged,
    "reassessment_launched": ReassessmentLaunched,
    "effectiveness_recorded": EffectivenessRecorded,
    "case_planning_updated": CasePlanningUpdated,
    "case_closed": CaseClosed,
    "case_reopened": CaseReopened,
    "patch_proposed": PatchProposed,
    "patch_abstained": PatchAbstained,
    "patch_approved": PatchApproved,
    "patch_rejected": PatchRejected,
    "patch_activation_abandoned": PatchActivationAbandoned,
    "artifact_created": ArtifactCreated,
    "artifact_abstained": ArtifactAbstained,
    "version_superseded_by_upload": VersionSupersededByUpload,
}


def validate_payload(event_type: str, payload: dict) -> dict:
    """Validate and normalize a payload for its event type. Raises KeyError
    for an unknown type and pydantic.ValidationError for a bad shape — an
    event that cannot be validated must never be appended."""
    model = PAYLOAD_SCHEMAS[event_type]
    return model.model_validate(payload).model_dump()
