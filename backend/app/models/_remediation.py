from app.models._shared import *  # noqa: F401,F403
from app.models._shared import _now, _uuid  # noqa: F401

# The only cross-module reference in the package: a case link declares an
# UNQUOTED relationship to Finding. Acyclic — _pipeline never imports from
# _remediation (its side of the association is a string-resolved backref).
from app.models._pipeline import Finding  # noqa: F401

# --------------------------------------------------------------- M7a remediation
# Human-supervised corrective-action workflow (spec §8). A case starts from a
# human-confirmed GAP finding (CONFIRMED + human_verdict in partial/
# non_compliant/missing — CONFIRMED alone includes compliant findings), goes
# through LLM-suggested/human-approved triage, an LLM-drafted plan of typed
# actions gated by deterministic verification (requirement + quote binding),
# per-action human review, lifecycle/effectiveness tracking and a scoped
# reassessment as effectiveness evidence.
#
# Write-once doctrine (same as Finding): the agent writes AI columns once;
# humans write only projection columns + append-only events. The only AI-row
# mutations are plan supersession (status -> SUPERSEDED) and the reassessment
# launch record's controlled PENDING -> terminal transition.
#
# remediation_attempts/remediation_llm_calls deliberately mirror
# assessment_attempts/llm_calls (chat precedent, 0009): llm_calls rows require
# an assessment attempt, so remediation gets its own pair.

# Abstention taxonomy shared by triage drafts and plans. Two classes:
# - completed drafting outcomes: schema_invalid (validation exhausted),
#   verification_failed (KB/quote binding exhausted), llm_error/rate_limited
#   (provider trail exhausted, via classify_failure);
# - operational aborts: retrieval_error (search failed before any LLM call),
#   draft_interrupted (stale PLANNING lease recovery). Operational-abort plan
#   rows are audit records and are never activated.
REMEDIATION_ABSTAIN_REASONS = (
    "schema_invalid",
    "verification_failed",
    "llm_error",
    "rate_limited",
    "retrieval_error",
    "draft_interrupted",
)

_REMEDIATION_ABSTAIN_SQL = ", ".join(f"'{r}'" for r in REMEDIATION_ABSTAIN_REASONS)

REMEDIATION_EVENT_TYPES = (
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
    # 0018 human case-planning edits (owner / deadline / closure criterion)
    "case_planning_updated",
    "case_closed",
    "case_reopened",
    # M7b patch/artifact flow (case-scoped view; generic version lifecycle
    # additionally lands in document_version_events)
    "patch_proposed",
    "patch_abstained",
    "patch_approved",
    "patch_rejected",
    "patch_activation_abandoned",
    "artifact_created",
    "artifact_abstained",
    "version_superseded_by_upload",
)

# M7b patch-proposal / artifact abstention taxonomy. Completed drafting
# outcomes (anchor_not_found/anchor_ambiguous only for proposals) vs the
# operational draft_interrupted recovery row (stale DRAFTING lease).
PATCH_ABSTAIN_REASONS = (
    "anchor_not_found",
    "anchor_ambiguous",
    "schema_invalid",
    "llm_error",
    "rate_limited",
    "draft_interrupted",
)
_PATCH_ABSTAIN_SQL = ", ".join(f"'{r}'" for r in PATCH_ABSTAIN_REASONS)

DOCUMENT_VERSION_EVENT_TYPES = (
    "version_created",
    "version_indexed",
    "version_activated",
    "version_activation_abandoned",
    "version_index_failed",
    "version_recovered",
    "version_superseded_by_upload",
)
_VERSION_EVENT_TYPES_SQL = ", ".join(f"'{t}'" for t in DOCUMENT_VERSION_EVENT_TYPES)


class RemediationCase(Base):
    """One corrective-action case over one or more linked CONFIRMED gap
    findings.

    The case row holds only the HUMAN-approved triage projection; every AI
    triage proposal lives in the append-only remediation_triage_drafts table.
    active_plan_id is the sole authority for which plan is executable —
    never inferred from plan sequence. evidence_revision increments on every
    successful finding link/unlink and on triage reopen; triage drafts
    snapshot it so stale LLM results are discarded, never persisted against
    a different case composition.

    approved_triage_draft_id / active_plan_id are plain columns in the ORM
    (SQLite create_all cannot ALTER-add circular FKs); migration 0013 adds
    the real SET NULL foreign keys on Postgres after all tables exist.
    """

    __tablename__ = "remediation_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('TRIAGE', 'TRIAGE_APPROVED', 'PLANNING', 'PLAN_READY', "
            "'IN_PROGRESS', 'CLOSED')",
            name="ck_remediation_cases_status",
        ),
        CheckConstraint(
            "classification IS NULL OR classification IN "
            "('evidence_gap', 'observation', 'improvement_opportunity', 'nonconformity')",
            name="ck_remediation_cases_classification",
        ),
        CheckConstraint(
            "scope IS NULL OR scope IN "
            "('local', 'related_requirements', 'organization_wide')",
            name="ck_remediation_cases_scope",
        ),
        # Human triage projection is all-NULL in TRIAGE and fully set beyond
        # (correction_note stays optional — the immediate correction may be
        # legitimately empty).
        CheckConstraint(
            "(status = 'TRIAGE' AND classification IS NULL AND scope IS NULL "
            "AND scope_rationale IS NULL AND triage_approved_at IS NULL "
            "AND approved_triage_draft_id IS NULL) "
            "OR (status != 'TRIAGE' AND classification IS NOT NULL "
            "AND scope IS NOT NULL AND scope_rationale IS NOT NULL "
            "AND triage_approved_at IS NOT NULL)",
            name="ck_remediation_cases_triage_coherence",
        ),
        CheckConstraint(
            "(status = 'CLOSED' AND closed_at IS NOT NULL AND close_note IS NOT NULL) "
            "OR (status != 'CLOSED' AND closed_at IS NULL AND close_note IS NULL)",
            name="ck_remediation_cases_closed_coherence",
        ),
        CheckConstraint(
            "(status = 'PLANNING' AND planning_token IS NOT NULL "
            "AND planning_started_at IS NOT NULL AND planning_heartbeat_at IS NOT NULL) "
            "OR (status != 'PLANNING' AND planning_token IS NULL "
            "AND planning_started_at IS NULL AND planning_heartbeat_at IS NULL)",
            name="ck_remediation_cases_lease_coherence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(
        String(20), default="TRIAGE", server_default=text("'TRIAGE'")
    )
    # Human-approved triage projection (AI drafts live in
    # remediation_triage_drafts; approval snapshots/overrides one draft).
    classification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    correction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str | None] = mapped_column(String(30), nullable=True)
    scope_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    triage_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # free-text, EXPLICITLY UNVERIFIED (no identity layer by design)
    triage_reviewer_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Circular FKs (case <-> draft, case <-> plan): use_alter mirrors the
    # post-hoc ALTER migration 0013 performs. See Document.current_version_id.
    approved_triage_draft_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "remediation_triage_drafts.id",
            use_alter=True,
            name="fk_remediation_cases_approved_triage_draft",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    active_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "remediation_plans.id",
            use_alter=True,
            name="fk_remediation_cases_active_plan",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    # Stale-input protection: bumped on every finding link/unlink and triage
    # reopen; triage drafts must match it to persist / be approved.
    evidence_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    # PLANNING lease (synchronous plan drafting crash recovery): the drafter
    # renews planning_heartbeat_at between provider calls; recovery is allowed
    # only once the heartbeat is stale (see remediation/planner.py).
    planning_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    planning_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    planning_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ---- case planning (0018): HUMAN operational metadata, all nullable —
    # existing cases stay honestly empty (« Non attribué » / « À définir »),
    # never backfilled. owner_role/editor label are free text, EXPLICITLY
    # UNVERIFIED (no identity layer by design). planning_revision guards
    # concurrent edits (optimistic check: the client sends the revision it
    # read; a mismatch is a 409, never a silent overwrite).
    owner_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closure_criterion: Mapped[str | None] = mapped_column(Text, nullable=True)
    planning_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    planning_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    planning_editor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    finding_links: Mapped[list["RemediationCaseFinding"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    triage_drafts: Mapped[list["RemediationTriageDraft"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="RemediationTriageDraft.sequence",
        foreign_keys="RemediationTriageDraft.case_id",
    )
    plans: Mapped[list["RemediationPlan"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="RemediationPlan.sequence",
        foreign_keys="RemediationPlan.case_id",
    )
    events: Mapped[list["RemediationEvent"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="RemediationEvent.sequence",
    )
    reassessments: Mapped[list["RemediationReassessment"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="RemediationReassessment.created_at",
    )


class RemediationTriageDraft(Base):
    """One AI triage proposal — immutable, append-only (a redraft appends the
    next sequence; the case's AI columns are never overwritten). Snapshot of
    the exact finding links + evidence_revision it was drafted from."""

    __tablename__ = "remediation_triage_drafts"
    __table_args__ = (
        UniqueConstraint("case_id", "sequence", name="uq_remediation_triage_drafts_sequence"),
        CheckConstraint(
            "status IN ('VERIFIED', 'ABSTAINED')",
            name="ck_remediation_triage_drafts_status",
        ),
        CheckConstraint(
            f"abstain_reason IS NULL OR abstain_reason IN ({_REMEDIATION_ABSTAIN_SQL})",
            name="ck_remediation_triage_drafts_abstain_reason",
        ),
        CheckConstraint(
            "ai_classification IS NULL OR ai_classification IN "
            "('evidence_gap', 'observation', 'improvement_opportunity', 'nonconformity')",
            name="ck_remediation_triage_drafts_classification",
        ),
        CheckConstraint(
            "ai_scope IS NULL OR ai_scope IN "
            "('local', 'related_requirements', 'organization_wide')",
            name="ck_remediation_triage_drafts_scope",
        ),
        # VERIFIED requires the complete structured proposal and no reason;
        # ABSTAINED requires a reason (raw_draft may be NULL on provider
        # failure — nothing truthful exists to store).
        CheckConstraint(
            "(status = 'VERIFIED' AND abstain_reason IS NULL "
            "AND ai_classification IS NOT NULL AND ai_correction_note IS NOT NULL "
            "AND ai_scope IS NOT NULL AND ai_scope_rationale IS NOT NULL) "
            "OR (status = 'ABSTAINED' AND abstain_reason IS NOT NULL)",
            name="ck_remediation_triage_drafts_coherence",
        ),
        CheckConstraint(
            "draft_attempts >= 0 AND draft_attempts <= 2",
            name="ck_remediation_triage_drafts_attempts",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_cases.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)  # 1-based
    status: Mapped[str] = mapped_column(String(20))
    abstain_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_classification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_correction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_scope: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_scope_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stale-input protection (see RemediationCase.evidence_revision).
    input_evidence_revision: Mapped[int] = mapped_column(Integer)
    # exact finding-link snapshots at draft start
    input_finding_links: Mapped[list] = mapped_column(JSON, default=list)
    # similar-gap search provenance (retrieval passages + candidate findings)
    similar_findings: Mapped[list] = mapped_column(JSON, default=list)
    similar_corpus: Mapped[list] = mapped_column(JSON, default=list)
    draft_attempts: Mapped[int] = mapped_column(Integer, default=0)
    prompt_version: Mapped[str] = mapped_column(String(20))
    corpus_version: Mapped[str] = mapped_column(String(20))
    # Text, not VARCHAR: provider-controlled (0008 rationale)
    final_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    case: Mapped[RemediationCase] = relationship(
        back_populates="triage_drafts", foreign_keys=[case_id]
    )


class RemediationCaseFinding(Base):
    """One finding linked to a case, with the finding's review state
    SNAPSHOTTED at link time — a later re-review of the finding never
    silently changes the case's recorded basis. One active (non-CLOSED) case
    per finding is service-enforced under the finding row lock (creation,
    link, reopen); the DB cannot express that cross-table invariant."""

    __tablename__ = "remediation_case_findings"
    __table_args__ = (
        UniqueConstraint("case_id", "finding_id", name="uq_remediation_case_findings_pair"),
        CheckConstraint(
            "link_source IN ('creation', 'search_suggested', 'manual')",
            name="ck_remediation_case_findings_source",
        ),
        # eligibility snapshot: only gap verdicts may ever be linked
        CheckConstraint(
            "finding_human_verdict IN ('partial', 'non_compliant', 'missing')",
            name="ck_remediation_case_findings_verdict",
        ),
        # at most one primary finding per case
        Index(
            "uq_remediation_case_findings_primary",
            "case_id",
            unique=True,
            postgresql_where=text("is_primary"),
            sqlite_where=text("is_primary"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_cases.id", ondelete="CASCADE"), index=True
    )
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    link_source: Mapped[str] = mapped_column(String(20))
    link_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    linker_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # finding snapshot at link time
    finding_review_count: Mapped[int] = mapped_column(Integer)
    finding_human_verdict: Mapped[str] = mapped_column(String(20))
    finding_human_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    finding_requirement_id: Mapped[str] = mapped_column(String(20))
    finding_requirement_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    finding_domain: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    case: Mapped[RemediationCase] = relationship(back_populates="finding_links")
    finding: Mapped[Finding] = relationship()


class RemediationPlan(Base):
    """One drafted corrective-action plan — write-once except the
    VERIFIED/ABSTAINED -> SUPERSEDED transition. Input snapshots make the
    plan self-contained: later unlinking a finding or reopening triage never
    changes the apparent basis of a historical plan."""

    __tablename__ = "remediation_plans"
    __table_args__ = (
        UniqueConstraint("case_id", "sequence", name="uq_remediation_plans_sequence"),
        CheckConstraint(
            "status IN ('VERIFIED', 'ABSTAINED', 'SUPERSEDED')",
            name="ck_remediation_plans_status",
        ),
        CheckConstraint(
            f"abstain_reason IS NULL OR abstain_reason IN ({_REMEDIATION_ABSTAIN_SQL})",
            name="ck_remediation_plans_abstain_reason",
        ),
        # VERIFIED requires the complete structured plan; ABSTAINED requires a
        # reason. SUPERSEDED keeps whatever shape it had before supersession.
        CheckConstraint(
            "(status = 'VERIFIED' AND abstain_reason IS NULL "
            "AND gap_restatement IS NOT NULL AND root_cause_hypotheses IS NOT NULL "
            "AND raw_draft IS NOT NULL) "
            "OR (status = 'ABSTAINED' AND abstain_reason IS NOT NULL) "
            "OR (status = 'SUPERSEDED')",
            name="ck_remediation_plans_coherence",
        ),
        # superseded_by_plan_id stays NULL when supersession came from triage
        # reopening rather than replacement by another plan.
        CheckConstraint(
            "(status = 'SUPERSEDED' AND superseded_at IS NOT NULL) "
            "OR (status != 'SUPERSEDED' AND superseded_at IS NULL "
            "AND superseded_by_plan_id IS NULL)",
            name="ck_remediation_plans_superseded_coherence",
        ),
        CheckConstraint(
            "draft_attempts >= 0 AND draft_attempts <= 2",
            name="ck_remediation_plans_attempts",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_cases.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)  # 1-based
    status: Mapped[str] = mapped_column(String(20))
    abstain_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_by_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("remediation_plans.id", ondelete="SET NULL"), nullable=True
    )
    gap_restatement: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{label, hypothesis}] — hypotheses are LABELED as such (spec §8)
    root_cause_hypotheses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    raw_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_attempts: Mapped[int] = mapped_column(Integer, default=0)
    prompt_version: Mapped[str] = mapped_column(String(20))
    corpus_version: Mapped[str] = mapped_column(String(20))
    final_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # exact server evidence set offered to the model (quote binding target)
    retrieved: Mapped[list] = mapped_column(JSON, default=list)
    # input snapshots (self-contained historical basis)
    input_finding_links: Mapped[list] = mapped_column(JSON, default=list)
    # the four effective human-approved triage fields + reviewer label +
    # approval time + source draft id — NOT the AI draft
    input_triage_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # server-owned list of KB ids actually offered in the prompt evidence;
    # impacted_requirement_ids must be a subset (requirement binding)
    allowed_requirement_ids: Mapped[list] = mapped_column(JSON, default=list)
    # requirement_fr/domain snapshots for every offered KB id
    input_kb: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    case: Mapped[RemediationCase] = relationship(
        back_populates="plans", foreign_keys=[case_id]
    )
    actions: Mapped[list["RemediationAction"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan",
        order_by="RemediationAction.position",
    )


class RemediationAction(Base):
    """One typed corrective action inside a plan. AI columns are write-once;
    the human decision lives in the review projection columns + events.
    Operable only while its plan is the case's active_plan_id AND VERIFIED
    (active-plan action authority — superseded plans' actions are immutable
    historical records and never block case closure)."""

    __tablename__ = "remediation_actions"
    __table_args__ = (
        UniqueConstraint("plan_id", "position", name="uq_remediation_actions_position"),
        CheckConstraint(
            "action_type IN ('document_amendment', 'new_document', 'process_change', "
            "'training', 'risk_treatment_update', 'other')",
            name="ck_remediation_actions_type",
        ),
        CheckConstraint(
            "review_status IN ('PENDING', 'CONFIRMED')",
            name="ck_remediation_actions_review_status",
        ),
        CheckConstraint(
            "review_action IS NULL OR review_action IN ('approve', 'edit', 'reject')",
            name="ck_remediation_actions_review_action",
        ),
        CheckConstraint(
            "priority IS NULL OR priority IN ('haute', 'normale', 'basse')",
            name="ck_remediation_actions_priority",
        ),
        CheckConstraint(
            "lifecycle IN ('PROPOSED', 'APPROVED', 'REJECTED', 'IN_PROGRESS', "
            "'DONE', 'CANCELLED')",
            name="ck_remediation_actions_lifecycle",
        ),
        CheckConstraint(
            "effectiveness IN ('NOT_CHECKED', 'EFFECTIVE', 'PARTIALLY_EFFECTIVE', "
            "'INEFFECTIVE')",
            name="ck_remediation_actions_effectiveness",
        ),
        # quote binding provenance: no quote => no match fields; a quote
        # requires COMPLETE exact-match provenance (fuzzy is never persisted)
        CheckConstraint(
            "(policy_quote IS NULL AND matched_chunk_id IS NULL "
            "AND match_start IS NULL AND match_end IS NULL "
            "AND match_method IS NULL AND match_score IS NULL) "
            "OR (policy_quote IS NOT NULL AND matched_chunk_id IS NOT NULL "
            "AND match_start IS NOT NULL AND match_end IS NOT NULL "
            "AND match_method = 'exact' AND match_score IS NOT NULL)",
            name="ck_remediation_actions_quote_coherence",
        ),
        # three-branch review coherence (deliberately NOT a mirror of
        # ck_findings_review_coherence — reject clears effective fields)
        CheckConstraint(
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
        CheckConstraint(
            "(effectiveness = 'NOT_CHECKED' AND effectiveness_note IS NULL "
            "AND effectiveness_recorded_at IS NULL) "
            "OR (effectiveness != 'NOT_CHECKED' AND effectiveness_note IS NOT NULL "
            "AND effectiveness_recorded_at IS NOT NULL)",
            name="ck_remediation_actions_effectiveness_coherence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_plans.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)  # 1-based, plan order
    # ---- write-once AI proposal
    action_type: Mapped[str] = mapped_column(String(30))
    ai_description: Mapped[str] = mapped_column(Text)
    ai_rationale: Mapped[str] = mapped_column(Text)
    ai_owner_role: Mapped[str] = mapped_column(Text)
    ai_success_criterion: Mapped[str] = mapped_column(Text)
    # immutable AI proposal; the human-approved effective scope lives in
    # remediation_action_requirements
    ai_impacted_requirement_ids: Mapped[list] = mapped_column(JSON, default=list)
    policy_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_chunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ---- human review projection (approve snapshots AI values; edit stores
    # human text; reject clears — AI columns above are never touched)
    review_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", server_default=text("'PENDING'")
    )
    review_action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_criterion: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 0018: human-set deadline — never invented by the LLM planner (there is
    # deliberately no ai_due_date). Nullable: existing actions stay honest.
    # Required (with the other operational fields) before IN_PROGRESS.
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # ---- independent tracking dimensions
    lifecycle: Mapped[str] = mapped_column(
        String(20), default="PROPOSED", server_default=text("'PROPOSED'")
    )
    effectiveness: Mapped[str] = mapped_column(
        String(30), default="NOT_CHECKED", server_default=text("'NOT_CHECKED'")
    )
    effectiveness_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    effectiveness_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    plan: Mapped[RemediationPlan] = relationship(back_populates="actions")
    requirements: Mapped[list["RemediationActionRequirement"]] = relationship(
        back_populates="action", cascade="all, delete-orphan"
    )


class RemediationActionRequirement(Base):
    """Human-approved EFFECTIVE requirement scope of one action. Written only
    by the action-review endpoint: approve snapshots ai_impacted_requirement_ids,
    edit stores validated human ids, reject deletes the rows (prior values
    preserved in the event payload). Feeds the effectiveness reassessment
    manifest now and M7b RemediationContext.requirement_ids later."""

    __tablename__ = "remediation_action_requirements"
    __table_args__ = (
        UniqueConstraint(
            "action_id", "requirement_id", name="uq_remediation_action_requirements_pair"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_actions.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(String(20))
    # requirement snapshot (M5 0012 precedent: review must not depend on the
    # live KB)
    requirement_fr: Mapped[str] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    action: Mapped[RemediationAction] = relationship(back_populates="requirements")


class RemediationReassessment(Base):
    """Append-only launch record for one scoped effectiveness reassessment,
    with a controlled PENDING -> LAUNCHED/LAUNCH_FAILED transition
    (status/error/assessment_id are the only mutable fields).
    planned_assessment_id is pre-generated BEFORE create_assessment so a crash
    between assessment creation and linkage is deterministically reconcilable.
    Holdout exclusions are recorded, never silent."""

    __tablename__ = "remediation_reassessments"
    __table_args__ = (
        UniqueConstraint(
            "planned_assessment_id", name="uq_remediation_reassessments_planned"
        ),
        CheckConstraint(
            "status IN ('PENDING', 'LAUNCHED', 'LAUNCH_FAILED')",
            name="ck_remediation_reassessments_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_cases.id", ondelete="CASCADE"), index=True
    )
    planned_assessment_id: Mapped[str] = mapped_column(String(36))
    assessment_id: Mapped[str | None] = mapped_column(
        ForeignKey("assessments.id", ondelete="SET NULL"), nullable=True
    )
    selected_action_ids: Mapped[list] = mapped_column(JSON, default=list)
    # manifest actually launched (dev split only) + the recorded exclusions
    included_requirement_ids: Mapped[list] = mapped_column(JSON, default=list)
    excluded_holdout_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(
        String(20), default="PENDING", server_default=text("'PENDING'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    case: Mapped[RemediationCase] = relationship(back_populates="reassessments")


class RemediationEvent(Base):
    """Append-only audit trail for the whole case aggregate — rows are never
    updated or deleted. sequence is assigned under the case row lock.
    Payloads are versioned discriminated schemas (remediation/events.py) with
    full before/after values for mutations. actor_label is free-text,
    EXPLICITLY UNVERIFIED (no identity layer by design)."""

    __tablename__ = "remediation_events"
    __table_args__ = (
        UniqueConstraint("case_id", "sequence", name="uq_remediation_events_sequence"),
        CheckConstraint(
            "event_type IN (" + ", ".join(f"'{t}'" for t in REMEDIATION_EVENT_TYPES) + ")",
            name="ck_remediation_events_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_cases.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)  # 1-based
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1")
    )
    actor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    case: Mapped[RemediationCase] = relationship(back_populates="events")


class RemediationAttempt(Base):
    """One semantic LLM attempt of the triage drafter or the planner. Mirrors
    AssessmentAttempt; stage names the flow and exactly one parent FK is set
    (coherence CHECK)."""

    __tablename__ = "remediation_attempts"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('triage', 'plan', 'patch', 'artifact')",
            name="ck_remediation_attempts_stage",
        ),
        CheckConstraint(
            "(stage = 'triage' AND triage_draft_id IS NOT NULL AND plan_id IS NULL "
            "AND patch_proposal_id IS NULL AND remediation_artifact_id IS NULL) "
            "OR (stage = 'plan' AND plan_id IS NOT NULL AND triage_draft_id IS NULL "
            "AND patch_proposal_id IS NULL AND remediation_artifact_id IS NULL) "
            "OR (stage = 'patch' AND patch_proposal_id IS NOT NULL AND triage_draft_id IS NULL "
            "AND plan_id IS NULL AND remediation_artifact_id IS NULL) "
            "OR (stage = 'artifact' AND remediation_artifact_id IS NOT NULL "
            "AND triage_draft_id IS NULL AND plan_id IS NULL AND patch_proposal_id IS NULL)",
            name="ck_remediation_attempts_stage_coherence",
        ),
        # unique attempt numbering per parent (one FK is always NULL, hence
        # partial indexes instead of a plain UniqueConstraint)
        Index(
            "uq_remediation_attempts_triage",
            "triage_draft_id",
            "attempt_number",
            unique=True,
            postgresql_where=text("triage_draft_id IS NOT NULL"),
            sqlite_where=text("triage_draft_id IS NOT NULL"),
        ),
        Index(
            "uq_remediation_attempts_plan",
            "plan_id",
            "attempt_number",
            unique=True,
            postgresql_where=text("plan_id IS NOT NULL"),
            sqlite_where=text("plan_id IS NOT NULL"),
        ),
        Index(
            "uq_remediation_attempts_patch",
            "patch_proposal_id",
            "attempt_number",
            unique=True,
            postgresql_where=text("patch_proposal_id IS NOT NULL"),
            sqlite_where=text("patch_proposal_id IS NOT NULL"),
        ),
        Index(
            "uq_remediation_attempts_artifact",
            "remediation_artifact_id",
            "attempt_number",
            unique=True,
            postgresql_where=text("remediation_artifact_id IS NOT NULL"),
            sqlite_where=text("remediation_artifact_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_cases.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(10))
    triage_draft_id: Mapped[str | None] = mapped_column(
        ForeignKey("remediation_triage_drafts.id", ondelete="CASCADE"), nullable=True
    )
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("remediation_plans.id", ondelete="CASCADE"), nullable=True
    )
    patch_proposal_id: Mapped[str | None] = mapped_column(
        ForeignKey("patch_proposals.id", ondelete="CASCADE"), nullable=True
    )
    remediation_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("remediation_artifacts.id", ondelete="CASCADE"), nullable=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer)  # 1-based
    prompt_version: Mapped[str] = mapped_column(String(20))
    parsed_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    verifier_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    llm_calls: Mapped[list["RemediationLlmCall"]] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="RemediationLlmCall.call_number",
    )


class RemediationLlmCall(Base):
    """One HTTP attempt against one provider within a remediation attempt.
    Deliberate mirror of llm_calls (chat precedent, 0009): llm_calls rows
    require an assessment attempt."""

    __tablename__ = "remediation_llm_calls"
    __table_args__ = (
        UniqueConstraint(
            "remediation_attempt_id", "call_number", name="uq_remediation_llm_calls_key"
        ),
        CheckConstraint(
            "status IN ('SUCCESS', 'HTTP_ERROR', 'NETWORK_ERROR', 'BAD_RESPONSE', "
            "'SKIPPED_NO_KEY')",
            name="ck_remediation_llm_calls_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    remediation_attempt_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_attempts.id", ondelete="CASCADE"), index=True
    )
    call_number: Mapped[int] = mapped_column(Integer)  # 1-based
    prompt_version: Mapped[str] = mapped_column(String(20), default="")
    provider: Mapped[str] = mapped_column(String(20))
    requested_model: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    reported_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_messages: Mapped[list] = mapped_column(JSON, default=list)
    response_format: Mapped[dict] = mapped_column(JSON, default=dict)
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    attempt: Mapped[RemediationAttempt] = relationship(back_populates="llm_calls")


# ------------------------------------------------------------------ M7b patch


def _drafting_lease_checks(table: str) -> tuple:
    """Shared coherence CHECKs for the DRAFTING-lease rows (patch proposals
    and artifacts are inserted BEFORE the LLM call; the case PLANNING lease is
    structurally unusable here — its coherence CHECK ties it to
    status='PLANNING' while patch drafting happens on IN_PROGRESS cases)."""
    return (
        CheckConstraint(
            "status IN ('DRAFTING', 'VERIFIED', 'ABSTAINED')",
            name=f"ck_{table}_status",
        ),
        # Lease fields set iff DRAFTING (token-fenced heartbeats).
        CheckConstraint(
            "(status = 'DRAFTING' AND drafting_token IS NOT NULL "
            "AND drafting_started_at IS NOT NULL AND drafting_heartbeat_at IS NOT NULL) "
            "OR (status != 'DRAFTING' AND drafting_token IS NULL "
            "AND drafting_started_at IS NULL AND drafting_heartbeat_at IS NULL)",
            name=f"ck_{table}_lease_coherence",
        ),
        CheckConstraint(
            "(status = 'ABSTAINED' AND abstain_reason IS NOT NULL) "
            "OR (status != 'ABSTAINED' AND abstain_reason IS NULL)",
            name=f"ck_{table}_abstain_coherence",
        ),
        CheckConstraint(
            f"abstain_reason IS NULL OR abstain_reason IN ({_PATCH_ABSTAIN_SQL})",
            name=f"ck_{table}_abstain_taxonomy",
        ),
    )


class PatchProposal(Base):
    """One AI anchored-patch proposal against ONE immutable document version
    (TXT/MD only). Server-owned context + staleness pins are set at creation;
    the AI draft columns are write-once after drafting; the human decision
    lives in patch_decisions.

    VERIFIED means exactly one raw-equality anchor match on page 1 within
    bounds (services/anchors.py) — never that the new text is good policy.
    ABSTAINED rows persist no resolved span: multiple matches select no
    authoritative location (candidates go to verifier_errors diagnostics).
    """

    __tablename__ = "patch_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "document_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_patch_proposals_version",
        ),
        *_drafting_lease_checks("patch_proposals"),
        CheckConstraint(
            "operation IS NULL OR operation IN ('insert_after', 'replace')",
            name="ck_patch_proposals_operation",
        ),
        # VERIFIED requires the complete AI output + resolved span; ABSTAINED
        # and DRAFTING never carry a resolved span.
        CheckConstraint(
            "(status = 'VERIFIED' AND anchor_quote IS NOT NULL AND anchor_page IS NOT NULL "
            "AND operation IS NOT NULL AND new_text_fr IS NOT NULL "
            "AND anchor_char_start IS NOT NULL AND anchor_char_end IS NOT NULL) "
            "OR (status != 'VERIFIED' AND anchor_char_start IS NULL AND anchor_char_end IS NULL)",
            name="ck_patch_proposals_output_coherence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_cases.id", ondelete="CASCADE"), index=True
    )
    action_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_actions.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(String(36))
    document_version_id: Mapped[str] = mapped_column(String(36), index=True)
    base_text_checksum: Mapped[str] = mapped_column(String(64))
    # Server-owned requirement scope (effective human-approved rows snapshot).
    requirement_ids: Mapped[list] = mapped_column(JSON, default=list)
    requirements_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    # Staleness pins (validated again at decision Tx A and activation Tx B).
    input_action_review_count: Mapped[int] = mapped_column(Integer)
    input_plan_id: Mapped[str] = mapped_column(String(36))
    input_case_evidence_revision: Mapped[int] = mapped_column(Integer)
    # DRAFTING lease.
    status: Mapped[str] = mapped_column(String(20), default="DRAFTING")
    drafting_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    drafting_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    drafting_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # AI draft (write-once after drafting completes).
    anchor_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    anchor_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_text_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstain_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    verifier_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Server-resolved anchor span (page-relative raw offsets), VERIFIED only.
    anchor_char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor_char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    prompt_version: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    decision: Mapped["PatchDecision | None"] = relationship(
        back_populates="proposal", uselist=False
    )


class PatchDecision(Base):
    """The single human decision on one proposal. UNIQUE(proposal_id) is the
    atomic duplicate-application gate; result_version_id links the decision to
    the version it created (recovery chain base -> decision -> result).
    approve snapshots the proposal's new_text_fr; edit carries human text; the
    FINAL human text is the only text ever applied."""

    __tablename__ = "patch_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('approve', 'edit', 'reject')", name="ck_patch_decisions_kind"
        ),
        # reject carries nothing; approve/edit carry text + checksum + version.
        CheckConstraint(
            "(decision = 'reject' AND final_text_fr IS NULL "
            "AND final_text_checksum IS NULL AND result_version_id IS NULL) "
            "OR (decision != 'reject' AND final_text_fr IS NOT NULL "
            "AND final_text_checksum IS NOT NULL AND result_version_id IS NOT NULL)",
            name="ck_patch_decisions_coherence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("patch_proposals.id", ondelete="CASCADE"), unique=True
    )
    decision: Mapped[str] = mapped_column(String(20))
    final_text_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    # sha256 of the exact UTF-8 final_text_fr (the result version's
    # text_checksum covers the whole resulting page sequence instead).
    final_text_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_versions.id"), unique=True, nullable=True
    )
    actor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    proposal: Mapped[PatchProposal] = relationship(back_populates="decision")


class RemediationArtifact(Base):
    """AI-drafted Markdown revision proposal for a PDF/DOCX target (the
    patch/artifact flow can never create a PDF/DOCX version — only an explicit
    human superseding re-upload can, which may then cite this artifact via
    document_versions.source_artifact_id to close the corrective-action loop).
    Same server-owned context, staleness pins and DRAFTING lease as
    patch_proposals; the target document is human-confirmed."""

    __tablename__ = "remediation_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "document_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_remediation_artifacts_version",
        ),
        *_drafting_lease_checks("remediation_artifacts"),
        CheckConstraint(
            "(status = 'VERIFIED' AND content_md IS NOT NULL) OR status != 'VERIFIED'",
            name="ck_remediation_artifacts_output_coherence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_cases.id", ondelete="CASCADE"), index=True
    )
    action_id: Mapped[str] = mapped_column(
        ForeignKey("remediation_actions.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(String(36))
    document_version_id: Mapped[str] = mapped_column(String(36), index=True)
    base_text_checksum: Mapped[str] = mapped_column(String(64))
    canonical_format: Mapped[str] = mapped_column(String(10))
    requirement_ids: Mapped[list] = mapped_column(JSON, default=list)
    requirements_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    input_action_review_count: Mapped[int] = mapped_column(Integer)
    input_plan_id: Mapped[str] = mapped_column(String(36))
    input_case_evidence_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFTING")
    drafting_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    drafting_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    drafting_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstain_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    verifier_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    prompt_version: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DocumentVersionEvent(Base):
    """Append-only audit trail of the generic version lifecycle (upload,
    indexing, activation, recovery) — separate from case-scoped
    remediation_events, which cannot host caseless superseding uploads.
    sequence is assigned under the DOCUMENT row lock, and rows are appended
    only from transactions already holding that lock in the declared order
    (org [-> case] -> document -> versions): version_indexed is recorded in
    the locked Tx B / recovery transaction after Qdrant success was observed,
    never from the lock-free indexing step."""

    __tablename__ = "document_version_events"
    __table_args__ = (
        UniqueConstraint("document_id", "sequence", name="uq_document_version_events_seq"),
        CheckConstraint(
            f"event_type IN ({_VERSION_EVENT_TYPES_SQL})",
            name="ck_document_version_events_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)  # 1-based
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1")
    )
    actor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
