from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class OrganizationCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime


# --- M10 auth -------------------------------------------------------------
# Password policy (min length, bcrypt 72-byte cap) is enforced in api/auth.py
# with French messages — not via StringConstraints, whose pydantic messages
# reach the UI in English through the generic 422 handler.


class SignupIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]
    password: str
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    organization_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


class LoginIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str


class SessionOut(BaseModel):
    user: UserOut
    organizations: list[OrganizationOut]


class InvitationCreateIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]


class InvitationCreatedOut(BaseModel):
    # raw token — returned exactly once, never persisted
    invite_token: str
    email: str
    expires_at: datetime


class InvitationPublicOut(BaseModel):
    organization_name: str
    email: str
    expired: bool


class InvitationAcceptIn(BaseModel):
    password: str
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    filename: str
    content_type: str
    status: str
    error: str | None
    page_count: int
    checksum: str | None
    parser_version: str
    current_version_id: str | None = None
    created_at: datetime


class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    version_number: int
    state: str
    origin: str
    canonical_format: str
    filename: str
    page_count: int
    source_checksum: str | None
    text_checksum: str
    parser_version: str
    chunker_version: str
    chunk_id_scheme: str
    supersedes_version_id: str | None
    source_artifact_id: str | None
    abandoned_reason: str | None
    activation_error: str | None
    created_at: datetime


class DocumentPageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_number: int
    text: str


class SearchRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    k: int = Field(default=8, ge=1, le=50)
    scope: Literal["policy", "kb", "both"] = "policy"


class SearchResult(BaseModel):
    result_id: str
    source_type: Literal["policy", "iso_requirement"]
    text: str
    rrf_score: float
    vector_rank: int | None
    bm25_rank: int | None
    document_id: str | None = None
    filename: str | None = None
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    requirement_id: str | None = None
    domain: str | None = None


class SoaDecisionBody(BaseModel):
    """One SoA applicability decision (M8): mandatory French justification."""

    applicable: bool
    justification_fr: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    editor_label: str | None = Field(default=None, max_length=200)


class ChatAsk(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    conversation_id: str | None = None
    k_policy: int = Field(default=8, ge=1, le=20)
    k_kb: int = Field(default=4, ge=1, le=10)
    # M8 drill-down: anchor the exchange on one finding (server loads the
    # snapshot; the finding's text is context, never citable evidence)
    finding_id: str | None = None
    # M9 «Norme seule» mode: skip the policy retrieval arm entirely, so the
    # answer can only cite the ISO KB. Combines freely with finding_id (the
    # finding stays non-citable context). The REQUESTED mode is not persisted;
    # evidence_scope on the message records what survived verification.
    kb_only: bool = False


class ChatClaimOut(BaseModel):
    text: str
    kind: Literal["organization", "standard"]
    citation_ids: list[str]
    citations_verified: bool = Field(
        description=(
            "Citation-LOCATION verified: every referenced quote exists exactly (after "
            "documented normalization: case folding, accents, whitespace, typography) in "
            "a retrieved passage, and every clause was among the retrieved KB "
            "requirements. NOT a semantic-support judgment — answers are AI drafts under "
            "passive review: the reader assesses support via the rendered references "
            "(render the source slice at the matched offsets, not this quote string); "
            "citation quality is measured in M6. No formal chat-claim confirmation "
            "workflow exists."
        )
    )
    failed_citation_ids: list[str] = []


class ChatCitationOut(BaseModel):
    """Verified citation (tagged by type). Policy fields snapshot the source
    location; KB fields carry the server-hydrated paraphrase."""

    id: str
    type: Literal["policy", "kb"]
    # policy
    quote: str | None = Field(
        default=None,
        description=(
            "MODEL-PROVIDED quote string. It matched the source exactly AFTER "
            "normalization (case folding, accents, whitespace, typography), so its raw "
            "characters may differ from the source. Never render it as source text — "
            "render source_quote."
        ),
    )
    source_quote: str | None = Field(
        default=None,
        description=(
            "AUTHORITATIVE raw source characters at the matched span, server-derived "
            "from the persisted retrieval snapshot after fail-closed validation "
            "(offsets in bounds AND the slice normalizes to the verified quote). This "
            "is the string a UI renders as the citation text. Null when validation "
            "failed — see source_quote_error; never render quote in its place."
        ),
    )
    source_quote_error: str | None = Field(
        default=None,
        description=(
            "French provenance error when source_quote could not be derived safely "
            "(missing/out-of-bounds offsets, or the slice does not normalize to the "
            "verified quote). Null on success."
        ),
    )
    chunk_id: str | None = None
    document_id: str | None = None
    filename: str | None = None
    page_number: int | None = Field(
        default=None,
        description="1-based page of the source document the offsets refer to.",
    )
    match_start: int | None = Field(
        default=None,
        description=(
            "Zero-based raw character offset into the page text (page_number), "
            "inclusive start of the matched span."
        ),
    )
    match_end: int | None = Field(
        default=None,
        description=(
            "Zero-based raw character offset into the page text, EXCLUSIVE end of the "
            "matched span ([match_start, match_end))."
        ),
    )
    match_method: str | None = Field(
        default=None,
        description=(
            "Always 'exact' (after documented normalization) for verified chat "
            "citations — fuzzy candidates are stripped and only appear in "
            "stripped_citations provenance."
        ),
    )
    match_score: float | None = None
    # kb
    requirement_id: str | None = None
    requirement_fr: str | None = None
    domain: str | None = None


class StrippedCitationOut(BaseModel):
    citation: dict
    error: str | None
    match: dict | None = None  # fuzzy candidate provenance, when any


class RetrievalNoteOut(BaseModel):
    result_id: str
    reason: str


class SuggestedClauseOut(BaseModel):
    requirement_id: str
    requirement_fr: str
    domain: str | None = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatAnswerSegmentOut(BaseModel):
    """One surviving claim as it appears in the assembled answer, with the
    citation ids that back it (footnote anchors)."""

    text: str
    citation_ids: list[str]


class ChatMessageOut(BaseModel):
    id: str
    conversation_id: str
    # M8 drill-down: live pointer (may be null after finding deletion) + the
    # IMMUTABLE ask-time snapshot the UI renders the context chip from
    finding_id: str | None = None
    finding_context: dict | None = None
    question: str
    status: Literal["ANSWERED", "ABSTAINED"]
    abstain_reason: str | None
    answer: str
    evidence_scope: Literal["policy", "kb_only", "mixed"] | None
    claims: list[ChatClaimOut]
    answer_citations: list[ChatCitationOut] = Field(
        description=(
            "ANSWER EVIDENCE: the location-verified citations referenced by surviving "
            "claims, in claim-reference (footnote) order. This is what a UI renders "
            "next to the answer."
        )
    )
    citations: list[ChatCitationOut] = Field(
        description=(
            "AUDIT PROVENANCE: every location-verified citation, including those "
            "referenced only by dropped claims or by nothing. Never render these as "
            "evidence for the final answer — use answer_citations."
        )
    )
    answer_segments: list["ChatAnswerSegmentOut"] = Field(
        description=(
            "The persisted answer, segmented by surviving claim so a UI can "
            "attach inline footnotes safely (the flat `answer` string also "
            "contains the KB-only caveat and cannot be split reliably "
            "client-side). Empty for ABSTAINED messages."
        )
    )
    answer_caveat: str | None = Field(
        description=(
            "The KB-only caveat appended to `answer` when evidence_scope is "
            "'kb_only' — rendered as a distinct caveat line, not claim prose."
        )
    )
    stripped_citations: list[StrippedCitationOut]
    retrieval_notes: list[RetrievalNoteOut] | None = Field(
        description=(
            "MODEL-GENERATED, UNVERIFIED commentary on why each displayed passage does "
            "not answer the question (no_evidence path). Deterministically checked for "
            "COVERAGE only (one note per displayed passage) — the reasons themselves are "
            "not verified and must be labelled as model commentary in any UI."
        )
    )
    searched: list[SearchResult]
    suggested_clause: SuggestedClauseOut | None
    final_model: str | None
    final_provider: str | None
    created_at: datetime


class IndexReport(BaseModel):
    documents: int
    chunks: int
    added: int
    removed: int
    stale_parser: list[str] = []


class KbIndexReport(BaseModel):
    requirements: int
    corpus_version: str


# ------------------------------------------------------------ M5 assessments


class AssessmentCreate(BaseModel):
    # None => the frozen 51-requirement dev manifest (M6 holdout protection:
    # ids outside the dev split are rejected by create_assessment).
    requirement_ids: list[str] | None = None
    k: int = Field(default=6, ge=1, le=20)


class AssessmentProgressOut(BaseModel):
    """Best-effort in-process progress decoration (lost on restart); the
    findings tallies in the same payload are the authoritative progress."""

    requirement_id: str
    node: str
    done: int
    total: int


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    corpus_version: str
    status: str
    requirement_ids: list[str] | None
    retrieval_k: int
    document_manifest: dict | None
    cancel_requested: bool
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class AssessmentListItemOut(AssessmentOut):
    total: int
    findings_done: int
    verified_count: int
    abstained_count: int
    reviewed_count: int
    # False for legacy pre-M5 rows (no frozen manifests): resume is refused.
    manifest_complete: bool
    progress: AssessmentProgressOut | None = None


class FindingSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    requirement_id: str
    status: str
    verdict: str | None
    abstain_reason: str | None
    confidence: float | None
    domain: str | None
    review_status: str
    review_action: str | None
    human_verdict: str | None
    created_at: datetime


class AssessmentDetailOut(AssessmentListItemOut):
    findings: list[FindingSummaryOut]


class KbRequirementOut(BaseModel):
    id: str
    domain: str | None = None
    requirement_fr: str


# ------------------------------------------------------------ M5 HITL review


class FindingReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    action: Literal["approve", "edit", "override"]
    human_verdict: str
    human_rationale: str | None
    review_note: str | None
    # free-text, EXPLICITLY UNVERIFIED (no identity layer by design)
    reviewer_label: str | None
    created_at: datetime


class ReviewDecision(BaseModel):
    action: Literal["approve", "edit", "override"]
    human_verdict: Literal["compliant", "partial", "non_compliant", "missing"] | None = None
    human_rationale: str | None = None
    review_note: str | None = None
    reviewer_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class LlmCallSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    call_number: int
    provider: str
    requested_model: str
    reported_model: str | None
    status: str
    http_status: int | None
    error: str | None


class AttemptDetailOut(BaseModel):
    attempt_number: int
    prompt_version: str
    parsed_ok: bool
    verifier_errors: list | None
    llm_calls: list[LlmCallSummaryOut]


class FindingDetailOut(FindingSummaryOut):
    """Full review payload: untouched AI draft + provenance + human decision.

    source_quote is the display text (raw source slice at the persisted
    offsets, fail-closed) — the UI renders it, never the model's policy_quote,
    which appears only as audit provenance. Its authority depends on
    source_quote_kind: "verified" (exact match, cross-checked against the
    verified quote — authoritative citation text) vs "candidate" (fuzzy
    near-match location kept for human review — bounded but NOT a verified
    citation, and labelled as such)."""

    assessment_id: str
    policy_quote: str | None
    clause_ref: str | None
    rationale: str | None
    matched_chunk_id: str | None
    match_start: int | None
    match_end: int | None
    match_method: str | None
    match_score: float | None
    attempts: int
    final_model: str | None
    final_provider: str | None
    # requirement snapshot; corpus_mismatch=True marks a legacy row whose
    # snapshot is NULL and whose corpus_version no longer matches the live KB
    requirement_fr: str | None
    corpus_mismatch: bool = False
    source_quote: str | None = None
    source_quote_error: str | None = None
    # "verified" = exact match cross-checked against the verified quote
    # (authoritative citation text); "candidate" = fuzzy near-match location
    # kept for human review — bounded but NOT a verified citation.
    source_quote_kind: Literal["verified", "candidate"] | None = None
    retrieved: list
    audit_log: list | None
    attempt_history: list[AttemptDetailOut]
    human_rationale: str | None
    review_note: str | None
    reviewed_at: datetime | None
    review_count: int
    reviews: list[FindingReviewOut]


# ------------------------------------------------------------ M7a remediation


class RemediationCaseCreate(BaseModel):
    finding_id: str
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    link_note: str | None = None
    actor_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class RemediationLinkDecision(BaseModel):
    finding_id: str
    decision: Literal["link", "reject"]
    link_source: Literal["search_suggested", "manual"] = "manual"
    link_note: str | None = None
    actor_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class RemediationTriageApprove(BaseModel):
    # explicit draft id — approval never targets an implicit "latest"
    triage_draft_id: str
    # omitted fields accept the AI draft; provided fields override it
    classification: Literal[
        "evidence_gap", "observation", "improvement_opportunity", "nonconformity"
    ] | None = None
    correction_note: str | None = None
    scope: Literal["local", "related_requirements", "organization_wide"] | None = None
    scope_rationale: str | None = None
    reviewer_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class RemediationActorBody(BaseModel):
    actor_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class RemediationCloseBody(BaseModel):
    close_note: str
    actor_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class RemediationCaseFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finding_id: str
    is_primary: bool
    link_source: str
    link_note: str | None
    linker_label: str | None
    finding_review_count: int
    finding_human_verdict: str
    finding_human_rationale: str | None
    finding_requirement_id: str
    finding_requirement_fr: str | None
    finding_domain: str | None
    created_at: datetime


class RemediationTriageDraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence: int
    status: str
    abstain_reason: str | None
    ai_classification: str | None
    ai_correction_note: str | None
    ai_scope: str | None
    ai_scope_rationale: str | None
    input_evidence_revision: int
    input_finding_links: list
    similar_findings: list
    similar_corpus: list
    draft_attempts: int
    prompt_version: str
    corpus_version: str
    final_model: str | None
    final_provider: str | None
    created_at: datetime


class RemediationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    event_type: str
    payload: dict
    payload_version: int
    # free-text, EXPLICITLY UNVERIFIED (no identity layer by design)
    actor_label: str | None
    created_at: datetime


class RemediationCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    title: str
    status: str
    classification: str | None
    correction_note: str | None
    scope: str | None
    scope_rationale: str | None
    triage_approved_at: datetime | None
    triage_reviewer_label: str | None
    approved_triage_draft_id: str | None
    active_plan_id: str | None
    evidence_revision: int
    closed_at: datetime | None
    close_note: str | None
    # ---- case planning (0018): human operational metadata, nullable —
    # rendered honestly (« Non attribué » / « À définir ») when absent
    owner_role: str | None
    due_date: date | None
    closure_criterion: str | None
    planning_revision: int
    planning_updated_at: datetime | None
    planning_editor_label: str | None
    created_at: datetime
    updated_at: datetime


class RemediationLinkSuggestionOut(BaseModel):
    finding_id: str
    assessment_id: str
    requirement_id: str
    requirement_fr: str | None
    domain: str | None
    human_verdict: str
    human_rationale: str | None
    same_domain: bool


class RemediationActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str
    position: int
    action_type: str
    ai_description: str
    ai_rationale: str
    ai_owner_role: str
    ai_success_criterion: str
    ai_impacted_requirement_ids: list
    policy_quote: str | None
    matched_chunk_id: str | None
    match_start: int | None
    match_end: int | None
    match_method: str | None
    match_score: float | None
    review_status: str
    review_action: str | None
    description: str | None
    rationale: str | None
    owner_role: str | None
    success_criterion: str | None
    priority: str | None
    due_date: date | None
    review_note: str | None
    reviewer_label: str | None
    reviewed_at: datetime | None
    review_count: int
    lifecycle: str
    effectiveness: str
    effectiveness_note: str | None
    effectiveness_recorded_at: datetime | None
    created_at: datetime


class RemediationPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    sequence: int
    status: str
    abstain_reason: str | None
    superseded_at: datetime | None
    superseded_by_plan_id: str | None
    gap_restatement: str | None
    root_cause_hypotheses: list | None
    draft_attempts: int
    prompt_version: str
    corpus_version: str
    final_model: str | None
    final_provider: str | None
    input_finding_links: list
    input_triage_snapshot: dict
    allowed_requirement_ids: list
    input_kb: dict
    created_at: datetime


class RemediationActionReview(BaseModel):
    action: Literal["approve", "edit", "reject"]
    # edit only: human text wins, omitted fields keep the AI values
    description: str | None = None
    rationale: str | None = None
    owner_role: str | None = None
    success_criterion: str | None = None
    # mandatory on approve/edit, forbidden meaning on reject
    priority: Literal["haute", "normale", "basse"] | None = None
    # human-set deadline (0018) — a provided date is stored; an omitted one
    # keeps the current value. The LLM planner never proposes deadlines.
    due_date: date | None = None
    # edit only: human-supplied effective requirement scope (override)
    impacted_requirement_ids: list[str] | None = None
    review_note: str | None = None
    reviewer_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class RemediationCasePlanningBody(BaseModel):
    """Human case-planning update (0018) under an optimistic revision check.
    Values are stored as given: null clears a field (an explicit, audited
    decision)."""

    expected_revision: int
    owner_role: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=300)
    ] | None = None
    due_date: date | None = None
    closure_criterion: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=2000)
    ] | None = None
    editor_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class RemediationLifecycleBody(BaseModel):
    lifecycle: Literal["IN_PROGRESS", "DONE", "CANCELLED"]
    actor_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class RemediationEffectivenessBody(BaseModel):
    effectiveness: Literal["EFFECTIVE", "PARTIALLY_EFFECTIVE", "INEFFECTIVE"]
    note: str
    # optional EVIDENCE citation, validated server-side; null = external
    # human evidence only (mandatory for actions with zero dev-split scope)
    reassessment_id: str | None = None
    actor_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class PatchProposalCreate(BaseModel):
    document_id: str
    actor_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class PatchDecisionBody(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    # NOT stripped: the human's edited text is applied EXACTLY (the UI promises
    # "appliquée telle quelle"). Emptiness/whitespace-only is rejected in the
    # service, which keeps intentional leading/trailing whitespace intact.
    final_text_fr: Annotated[str, StringConstraints(max_length=8000)] | None = None
    actor_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class RemediationReassessmentCreate(BaseModel):
    selected_action_ids: list[str]
    actor_label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200)
    ] | None = None


class RemediationReassessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    planned_assessment_id: str
    assessment_id: str | None
    selected_action_ids: list
    included_requirement_ids: list
    excluded_holdout_ids: list
    status: str
    error: str | None
    actor_label: str | None
    created_at: datetime
