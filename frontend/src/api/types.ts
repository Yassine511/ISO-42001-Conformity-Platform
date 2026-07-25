// Shared API types and constants for the app.
// Split out of the former single src/api.ts — see ./index.ts for the contract.

export interface Organization {
  id: string;
  name: string;
  created_at: string;
}

// ------------------------------------------------------------ auth (M10)

export interface User {
  id: string;
  email: string;
  display_name: string;
}

export interface SessionInfo {
  user: User;
  organizations: Organization[];
}

export interface InvitationCreated {
  invite_token: string; // raw token — shown once, never retrievable again
  email: string;
  expires_at: string;
}

export interface InvitationPublic {
  organization_name: string;
  email: string;
  expired: boolean;
  /** true when the invited address already has an account: joining is then a
      sign-in, not a sign-up (the accept page switches form accordingly). */
  account_exists: boolean;
}

export interface OrganizationMember {
  user_id: string;
  email: string;
  display_name: string;
  joined_at: string;
  is_self: boolean;
}

/** Pending invitation. Carries no token — the raw link is displayable exactly
    once, at creation; this is the metadata needed to revoke it. */
export interface PendingInvitation {
  id: string;
  email: string;
  created_at: string;
  expires_at: string;
  expired: boolean;
}

/** Fired on any 401 API response so the auth provider can drop the session. */
export const UNAUTHORIZED_EVENT = "int102:unauthorized";

export interface Doc {
  id: string;
  organization_id: string;
  filename: string;
  content_type: string;
  status: "uploaded" | "parsed" | "failed";
  error: string | null;
  page_count: number;
  created_at: string;
}

export interface IndexReport {
  documents: number;
  chunks: number;
  added: number;
  removed: number;
  stale_parser: string[];
}

// ------------------------------------------------------------ assessments

export type Verdict = "compliant" | "partial" | "non_compliant" | "missing";
export type AssessmentStatus = "RUNNING" | "COMPLETED" | "FAILED";
export type FindingStatus = "VERIFIED" | "ABSTAINED";
export type ReviewAction = "approve" | "edit" | "override";

export interface AssessmentProgress {
  requirement_id: string;
  node: string;
  done: number;
  total: number;
}

export interface Assessment {
  id: string;
  organization_id: string;
  corpus_version: string;
  status: AssessmentStatus;
  requirement_ids: string[] | null;
  retrieval_k: number;
  // M7b: chunker provenance is recorded PER DOCUMENT VERSION (a mixed
  // v2/v3 corpus has no honest global chunker_version claim).
  document_manifest: {
    documents: {
      document_id: string;
      filename: string;
      checksum: string | null;
      parser_version: string;
      page_count: number;
      document_version_id?: string | null;
      version_number?: number | null;
      source_checksum?: string | null;
      text_checksum?: string | null;
      chunker_version?: string | null;
      chunk_id_scheme?: string | null;
    }[];
    chunk_count: number;
    indexed_at: string;
  } | null;
  cancel_requested: boolean;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  total: number;
  findings_done: number;
  verified_count: number;
  abstained_count: number;
  reviewed_count: number;
  manifest_complete: boolean;
  // true only for an ORPHANED RUNNING run (server restarted mid-run): resume
  // 409s on any run the server is actually executing.
  resumable: boolean;
  progress: AssessmentProgress | null;
}

export interface FindingSummary {
  id: string;
  requirement_id: string;
  status: FindingStatus;
  verdict: Verdict | null;
  abstain_reason: string | null;
  confidence: number | null;
  domain: string | null;
  review_status: "PENDING" | "CONFIRMED";
  review_action: ReviewAction | null;
  human_verdict: Verdict | null;
  created_at: string;
}

export interface AssessmentDetail extends Assessment {
  findings: FindingSummary[];
}

export interface RetrievedItem {
  result_id: string;
  source_type: "policy" | "iso_requirement";
  text: string;
  rrf_score: number;
  vector_rank: number | null;
  bm25_rank: number | null;
  document_id: string | null;
  filename: string | null;
  page_number: number | null;
  char_start: number | null;
  char_end: number | null;
  requirement_id: string | null;
  domain: string | null;
}

export interface FindingReview {
  sequence: number;
  action: ReviewAction;
  human_verdict: Verdict;
  human_rationale: string | null;
  review_note: string | null;
  reviewer_label: string | null; // free text, explicitly unverified
  created_at: string;
}

export interface LlmCallSummary {
  call_number: number;
  provider: string;
  requested_model: string;
  reported_model: string | null;
  status: string;
  http_status: number | null;
  error: string | null;
}

export interface AttemptDetail {
  attempt_number: number;
  prompt_version: string;
  parsed_ok: boolean;
  verifier_errors: string[] | null;
  llm_calls: LlmCallSummary[];
}

export interface FindingDetail extends FindingSummary {
  assessment_id: string;
  policy_quote: string | null;
  clause_ref: string | null;
  rationale: string | null;
  matched_chunk_id: string | null;
  match_start: number | null;
  match_end: number | null;
  match_method: string | null;
  match_score: number | null;
  attempts: number;
  final_model: string | null;
  final_provider: string | null;
  requirement_fr: string | null;
  corpus_mismatch: boolean;
  // Display text (raw source slice at persisted offsets, fail-closed) —
  // render THIS, never policy_quote. Authority depends on source_quote_kind:
  // "verified" = exact, cross-checked citation text (authoritative);
  // "candidate" = fuzzy near-match location for human review — bounded but
  // NOT a verified citation, must be labelled as a candidate.
  source_quote: string | null;
  source_quote_error: string | null;
  source_quote_kind: "verified" | "candidate" | null;
  retrieved: RetrievedItem[];
  audit_log: { node: string; event: string; at?: string }[] | null;
  attempt_history: AttemptDetail[];
  human_rationale: string | null;
  review_note: string | null;
  reviewed_at: string | null;
  review_count: number;
  reviews: FindingReview[];
}

export interface ReviewDecision {
  action: ReviewAction;
  human_verdict?: Verdict;
  human_rationale?: string;
  review_note?: string;
  reviewer_label?: string;
}

export interface KbRequirement {
  id: string;
  domain: string | null;
  requirement_fr: string;
}

// ------------------------------------------------------------------- chat

export interface Conversation {
  id: string;
  organization_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatClaim {
  text: string;
  kind: "organization" | "standard";
  citation_ids: string[];
  citations_verified: boolean; // LOCATION verified, never semantic support
  failed_citation_ids?: string[];
}

export interface ChatCitation {
  id: string;
  type: "policy" | "kb";
  quote?: string | null; // model-provided — audit only, never rendered as evidence
  source_quote?: string | null; // AUTHORITATIVE server-derived slice
  source_quote_error?: string | null;
  chunk_id?: string | null;
  document_id?: string | null;
  filename?: string | null;
  page_number?: number | null;
  match_start?: number | null;
  match_end?: number | null;
  match_method?: string | null;
  match_score?: number | null;
  requirement_id?: string | null;
  requirement_fr?: string | null;
  domain?: string | null;
}

export interface AnswerSegment {
  text: string;
  citation_ids: string[];
}

export interface StrippedCitation {
  citation: Record<string, unknown>;
  error: string | null;
  match: Record<string, unknown> | null;
}

export interface RetrievalNote {
  result_id: string;
  reason: string; // model commentary — UNVERIFIED, label it as such
}

export interface SuggestedClause {
  requirement_id: string;
  requirement_fr: string;
  domain: string | null;
}

export interface FindingContext {
  finding_id: string;
  assessment_id: string;
  requirement_id: string;
  requirement_fr: string | null;
  domain: string | null;
  ai_status: FindingStatus;
  ai_verdict: Verdict | null;
  abstain_reason: string | null;
  ai_rationale: string | null;
  review_status: "PENDING" | "CONFIRMED";
  review_action: ReviewAction | null;
  human_verdict: Verdict | null;
  human_rationale: string | null;
  review_count: number;
  reviewed_at: string | null;
  evidence: {
    matched_chunk_id: string | null;
    match_start: number | null;
    match_end: number | null;
    match_method: "exact" | "fuzzy" | null;
  };
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  // M8 drill-down: live pointer (null after finding deletion) + the
  // immutable ask-time snapshot the chip renders from
  finding_id: string | null;
  finding_context: FindingContext | null;
  question: string;
  status: "ANSWERED" | "ABSTAINED";
  abstain_reason: string | null;
  answer: string;
  evidence_scope: "policy" | "kb_only" | "mixed" | null;
  claims: ChatClaim[];
  answer_segments: AnswerSegment[];
  answer_caveat: string | null;
  answer_citations: ChatCitation[]; // footnote order — what the UI renders
  citations: ChatCitation[]; // audit provenance, never answer evidence
  stripped_citations: StrippedCitation[];
  retrieval_notes: RetrievalNote[] | null;
  searched: RetrievedItem[];
  suggested_clause: SuggestedClause | null;
  final_model: string | null;
  final_provider: string | null;
  created_at: string;
}

// ----------------------------------------------------------- remediation

export type CaseStatus =
  | "TRIAGE"
  | "TRIAGE_APPROVED"
  | "PLANNING"
  | "PLAN_READY"
  | "IN_PROGRESS"
  | "CLOSED";
export type Classification =
  | "evidence_gap"
  | "observation"
  | "improvement_opportunity"
  | "nonconformity";
export type RemediationScope = "local" | "related_requirements" | "organization_wide";
export type ActionLifecycle =
  | "PROPOSED"
  | "APPROVED"
  | "REJECTED"
  | "IN_PROGRESS"
  | "DONE"
  | "CANCELLED";
export type Effectiveness =
  | "NOT_CHECKED"
  | "EFFECTIVE"
  | "PARTIALLY_EFFECTIVE"
  | "INEFFECTIVE";
// Operational aborts are audit rows (never activated) — rendered neutrally,
// unlike completed drafting abstentions.
export const OPERATIONAL_ABORT_REASONS = ["retrieval_error", "draft_interrupted"] as const;

export interface CaseFindingLink {
  finding_id: string;
  is_primary: boolean;
  link_source: "creation" | "search_suggested" | "manual";
  link_note: string | null;
  linker_label: string | null;
  finding_review_count: number;
  finding_human_verdict: Verdict;
  finding_human_rationale: string | null;
  finding_requirement_id: string;
  finding_requirement_fr: string | null;
  finding_domain: string | null;
  created_at: string;
}

export interface TriageDraft {
  id: string;
  sequence: number;
  status: "VERIFIED" | "ABSTAINED";
  abstain_reason: string | null;
  ai_classification: Classification | null;
  ai_correction_note: string | null;
  ai_scope: RemediationScope | null;
  ai_scope_rationale: string | null;
  input_evidence_revision: number;
  input_finding_links: Record<string, unknown>[];
  similar_findings: Record<string, unknown>[];
  similar_corpus: Record<string, unknown>[];
  draft_attempts: number;
  prompt_version: string;
  corpus_version: string;
  final_model: string | null;
  final_provider: string | null;
  created_at: string;
}

export interface RemediationAction {
  id: string;
  plan_id: string;
  position: number;
  action_type:
    | "document_amendment"
    | "new_document"
    | "process_change"
    | "training"
    | "risk_treatment_update"
    | "other";
  ai_description: string;
  ai_rationale: string;
  ai_owner_role: string;
  ai_success_criterion: string;
  ai_impacted_requirement_ids: string[];
  policy_quote: string | null;
  matched_chunk_id: string | null;
  match_start: number | null;
  match_end: number | null;
  match_method: string | null;
  match_score: number | null;
  review_status: "PENDING" | "CONFIRMED";
  review_action: "approve" | "edit" | "reject" | null;
  description: string | null;
  rationale: string | null;
  owner_role: string | null;
  success_criterion: string | null;
  priority: "haute" | "normale" | "basse" | null;
  // 0018: human-set deadline (ISO date) — required before IN_PROGRESS,
  // never proposed by the LLM planner
  due_date: string | null;
  review_note: string | null;
  reviewer_label: string | null;
  reviewed_at: string | null;
  review_count: number;
  lifecycle: ActionLifecycle;
  effectiveness: Effectiveness;
  effectiveness_note: string | null;
  effectiveness_recorded_at: string | null;
  created_at: string;
  // human-approved effective scope (remediation_action_requirements) — the
  // authoritative projection, distinct from ai_impacted_requirement_ids
  effective_requirement_ids: string[];
  // AUTHORITATIVE citation display text: raw source slice at the persisted
  // offsets, fail-closed (render THIS, never policy_quote)
  source_quote: string | null;
  source_quote_error: string | null;
  // M8 read-only severity-derived suggestion (pre-fill only — the human
  // priority decision stays mandatory); pinned to a scoring-policy version
  suggested_priority: "haute" | "normale" | "basse" | null;
  suggested_priority_reason:
    | "no_linked_gap_in_action_scope"
    | "all_matching_weights_unscored"
    | null;
  suggested_priority_policy_version: string;
}

export interface RemediationPlan {
  id: string;
  case_id: string;
  sequence: number;
  status: "VERIFIED" | "ABSTAINED" | "SUPERSEDED";
  abstain_reason: string | null;
  superseded_at: string | null;
  superseded_by_plan_id: string | null;
  gap_restatement: string | null;
  root_cause_hypotheses: { label: string; hypothesis: string }[] | null;
  draft_attempts: number;
  prompt_version: string;
  corpus_version: string;
  final_model: string | null;
  final_provider: string | null;
  input_finding_links: Record<string, unknown>[];
  input_triage_snapshot: Record<string, unknown>;
  allowed_requirement_ids: string[];
  input_kb: Record<string, { requirement_fr: string; domain: string | null }>;
  created_at: string;
  actions: RemediationAction[];
}

export interface RemediationEvent {
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  payload_version: number;
  actor_label: string | null; // free text, explicitly unverified
  created_at: string;
}

/** Compact workflow summary computed server-side (0018). The frontend
    translates next_action_key / recommendations through lib/labels — raw
    keys never render. */
export interface CaseWorkflowSummary {
  active_plan_status: "VERIFIED" | "ABSTAINED" | "SUPERSEDED" | null;
  blocker_reason: string | null;
  pending_action_count: number;
  open_action_count: number;
  next_action_key: string;
  closure: {
    // a recommendation, never an enforced gate — the backend does not yet
    // require effectiveness at closure
    recommended_ready: boolean;
    recommendations: string[];
  };
}

export interface RemediationCase {
  id: string;
  organization_id: string;
  title: string;
  status: CaseStatus;
  classification: Classification | null;
  correction_note: string | null;
  scope: RemediationScope | null;
  scope_rationale: string | null;
  triage_approved_at: string | null;
  triage_reviewer_label: string | null;
  approved_triage_draft_id: string | null;
  active_plan_id: string | null;
  evidence_revision: number;
  closed_at: string | null;
  close_note: string | null;
  // ---- case planning (0018): human fields, honestly null until set
  owner_role: string | null;
  due_date: string | null; // ISO date
  closure_criterion: string | null;
  planning_revision: number;
  planning_updated_at: string | null;
  planning_editor_label: string | null; // free text, explicitly unverified
  created_at: string;
  updated_at: string;
  finding_links: CaseFindingLink[];
  workflow: CaseWorkflowSummary;
}

export interface RemediationCaseDetail extends RemediationCase {
  triage_drafts: TriageDraft[];
  plans: RemediationPlan[];
  events: RemediationEvent[];
}

export interface LinkSuggestion {
  finding_id: string;
  assessment_id: string;
  requirement_id: string;
  requirement_fr: string | null;
  domain: string | null;
  human_verdict: Verdict;
  human_rationale: string | null;
  same_domain: boolean;
}

export interface Reassessment {
  id: string;
  case_id: string;
  planned_assessment_id: string;
  assessment_id: string | null;
  selected_action_ids: string[];
  included_requirement_ids: string[];
  excluded_holdout_ids: string[];
  status: "PENDING" | "LAUNCHED" | "LAUNCH_FAILED";
  error: string | null;
  actor_label: string | null;
  created_at: string;
}

// M7b document versions + anchored patch flow
export interface DocumentVersionSummary {
  id: string;
  document_id: string;
  version_number: number;
  state: "PENDING_INDEX" | "ACTIVE" | "SUPERSEDED" | "INDEX_FAILED" | "ABANDONED";
  origin: "upload" | "patch";
  canonical_format: "pdf" | "docx" | "txt" | "md";
  filename: string;
  page_count: number;
  source_checksum: string | null;
  text_checksum: string;
  parser_version: string;
  chunker_version: string;
  chunk_id_scheme: string;
  supersedes_version_id: string | null;
  source_artifact_id: string | null;
  abandoned_reason: string | null;
  activation_error: string | null;
  created_at: string;
}

export interface PatchProposalView {
  id: string;
  case_id: string;
  action_id: string;
  document_id: string;
  document_version_id: string;
  base_text_checksum: string;
  status: "DRAFTING" | "VERIFIED" | "ABSTAINED";
  abstain_reason: string | null;
  verifier_errors: string[] | null;
  operation: "insert_after" | "replace" | null;
  anchor_page: number | null;
  new_text_fr: string | null;
  rationale: string | null;
  attempts: number;
  requirement_ids: string[];
  created_at: string;
  anchor_char_start: number | null;
  anchor_char_end: number | null;
  anchor_slice: string | null;
  context_before: string | null;
  context_after: string | null;
  decision: {
    id: string;
    decision: "approve" | "edit" | "reject";
    final_text_fr: string | null;
    result_version_id: string | null;
    actor_label: string | null;
    created_at: string;
    result_state?: string;
    result_abandoned_reason?: string | null;
    result_activation_error?: string | null;
  } | null;
}

export interface RemediationArtifactView {
  id: string;
  case_id: string;
  action_id: string;
  document_id: string;
  document_version_id: string;
  canonical_format: "pdf" | "docx" | "txt" | "md";
  status: "DRAFTING" | "VERIFIED" | "ABSTAINED";
  abstain_reason: string | null;
  verifier_errors: string[] | null;
  filename: string | null;
  content_md: string | null;
  rationale: string | null;
  attempts: number;
  requirement_ids: string[];
  created_at: string;
}

// Outcome of a patch decision / superseding-upload activation.
export interface ActivationResult {
  outcome: string; // "activated" | "already_active" | "rejected" | "pending" | "assessment_conflict" | "index_failed" | "abandoned:<reason>"
  decision_id: string | null;
  version_id: string | null;
  detail?: string;
}

// ------------------------------------------------------------ reporting (M8)

export interface ReportingScopeMeta {
  mode: "organization" | "assessment";
  assessment_id: string | null;
  assessment_status: AssessmentStatus | null;
  scoring_policy_version: string;
  corpus_versions: string[];
  generated_at: string;
  // snapshot instant: review decisions after it are not in this report
  review_cutoff: string;
  // the exact denominator, independently auditable
  requirement_universe: string[];
  included_assessment_ids: string[];
  excluded_preliminary_assessment_ids: string[];
  legacy_manifest_missing_ids: string[];
  scope_complete: boolean;
  is_preliminary: boolean;
  is_official: boolean;
  official_blockers: string[];
  kb_total_requirements: number;
}

export interface ConformityDomain {
  domain: string;
  domain_title_fr: string;
  total_in_scope: number;
  scored: number;
  pending_review: number;
  not_assessed: number;
  verdict_counts: Record<Verdict, number>;
  pct: number | null;
}

export interface ConformityReport {
  scope: ReportingScopeMeta;
  global_pct: number | null;
  scored: number;
  total_in_scope: number;
  coverage_pct: number | null;
  verdict_counts: Record<Verdict, number>;
  domains: ConformityDomain[];
}

export interface TrustPanel {
  scope: ReportingScopeMeta;
  gate: {
    drafts_total: number;
    drafts_parsed: number;
    drafts_schema_invalid: number;
    drafts_provider_failure: number;
    legacy_unclassified: number;
    drafts_with_unsupported_citation: number;
    unsupported_draft_rate_pct: number | null;
    verifier_error_code_counts: Record<string, number>;
    findings_verified: number;
    findings_abstained: number;
    findings_abstained_by_verifier: number;
    abstentions_by_reason: Record<string, number>;
    unsupported_citations_displayed: 0;
  };
  review: {
    review_events: number;
    approve_events: number;
    edit_or_override_events: number;
    override_events: number;
    intervention_rate_pct: number | null;
    verdict_override_rate_pct: number | null;
  };
  chat: {
    metric_scope: "organization";
    messages: number;
    answered: number;
    abstained: number;
    stripped_citation_count: number;
  };
  m6_benchmark: Record<string, string | number>;
}

export type Severity = "low" | "medium" | "high";

export interface RiskRow {
  requirement_id: string;
  domain: string;
  domain_title_fr: string;
  requirement_fr: string | null;
  human_verdict: Verdict;
  gap_factor: number;
  weight: number | null;
  weight_source: "policy" | "unscored_weight";
  severity_score: number | null;
  severity: Severity | null;
  // SoA declaration on this control — annotates the row, never filters it
  applicable: boolean;
  applicability_justification_fr: string | null;
  risk_statement_fr: string;
  finding_id: string;
  assessment_id: string;
  reviewed_at: string | null;
  treatment: {
    active_case_id: string | null;
    active_case_status: string | null;
    approved_action_count: number;
    closed_case_ids: string[];
  } | null;
}

export interface RiskRegister {
  scope: ReportingScopeMeta;
  rows: RiskRow[];
  counts: { high: number; medium: number; low: number; unscored: number };
}

export interface ReportingParams {
  assessmentId?: string;
  scoringPolicyVersion?: string;
  includePreliminary?: boolean;
}

export interface SoaControlRow {
  control_id: string;
  domain: string;
  domain_title_fr: string;
  requirement_fr: string | null;
  applicable: boolean;
  justification_fr: string | null;
  editor_label: string | null;
  decision_count: number;
  updated_at: string | null;
  is_default: boolean;
  status: "conforme" | "ecart" | "non_evalue";
  human_verdict: Verdict | null;
  in_scope: boolean;
  finding_id: string | null;
  assessment_id: string | null;
  weight: number | null;
  weight_source: "policy" | "unscored_weight";
}

export interface SoaTable {
  scope: ReportingScopeMeta;
  applicability_scope: "organization_current";
  controls: SoaControlRow[];
  domains: {
    domain: string;
    domain_title_fr: string;
    controls: number;
    applicable: number;
    conforme: number;
    ecart: number;
    non_evalue: number;
  }[];
}

export interface SoaDecision {
  sequence: number;
  applicable: boolean;
  justification_fr: string;
  editor_label: string | null;
  created_at: string;
}

// Abstentions caused by provider infrastructure — rendered as neutral
// service failures, never as amber "needs your judgment".
export const INFRA_ABSTAIN_REASONS = ["llm_error", "rate_limited"] as const;
export const isInfraAbstain = (reason: string | null) =>
  reason !== null && (INFRA_ABSTAIN_REASONS as readonly string[]).includes(reason);
