export interface Organization {
  id: string;
  name: string;
  created_at: string;
}

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
  document_manifest: {
    documents: {
      document_id: string;
      filename: string;
      checksum: string | null;
      parser_version: string;
      page_count: number;
    }[];
    chunker_version: string;
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

export interface ChatMessage {
  id: string;
  conversation_id: string;
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
  created_at: string;
  updated_at: string;
  finding_links: CaseFindingLink[];
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

// Abstentions caused by provider infrastructure — rendered as neutral
// service failures, never as amber "needs your judgment".
export const INFRA_ABSTAIN_REASONS = ["llm_error", "rate_limited"] as const;
export const isInfraAbstain = (reason: string | null) =>
  reason !== null && (INFRA_ABSTAIN_REASONS as readonly string[]).includes(reason);

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Erreur ${res.status}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  listOrganizations: () => fetch("/api/organizations").then((r) => json<Organization[]>(r)),
  createOrganization: (name: string) =>
    post("/api/organizations", { name }).then((r) => json<Organization>(r)),
  listDocuments: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/documents`).then((r) => json<Doc[]>(r)),
  uploadDocument: (orgId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`/api/organizations/${orgId}/documents`, { method: "POST", body: form }).then(
      (r) => json<Doc>(r),
    );
  },
  deleteDocument: (docId: string) =>
    fetch(`/api/documents/${docId}`, { method: "DELETE" }).then((r) => json<void>(r)),
  indexOrganization: (orgId: string) =>
    post(`/api/organizations/${orgId}/index`).then((r) => json<IndexReport>(r)),

  // assessments
  createAssessment: (orgId: string, body: { requirement_ids?: string[]; k?: number }) =>
    post(`/api/organizations/${orgId}/assessments`, body).then((r) => json<Assessment>(r)),
  listAssessments: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/assessments`).then((r) => json<Assessment[]>(r)),
  getAssessment: (orgId: string, assessmentId: string) =>
    fetch(`/api/organizations/${orgId}/assessments/${assessmentId}`).then((r) =>
      json<AssessmentDetail>(r),
    ),
  resumeAssessment: (orgId: string, assessmentId: string) =>
    post(`/api/organizations/${orgId}/assessments/${assessmentId}/resume`).then((r) =>
      json<Assessment>(r),
    ),
  abandonAssessment: (orgId: string, assessmentId: string) =>
    post(`/api/organizations/${orgId}/assessments/${assessmentId}/abandon`).then((r) =>
      json<Assessment>(r),
    ),
  listKbRequirements: () =>
    fetch("/api/kb/requirements").then((r) => json<KbRequirement[]>(r)),

  // findings / review
  getFinding: (orgId: string, assessmentId: string, findingId: string) =>
    fetch(`/api/organizations/${orgId}/assessments/${assessmentId}/findings/${findingId}`).then(
      (r) => json<FindingDetail>(r),
    ),
  reviewFinding: (
    orgId: string,
    assessmentId: string,
    findingId: string,
    decision: ReviewDecision,
  ) =>
    post(
      `/api/organizations/${orgId}/assessments/${assessmentId}/findings/${findingId}/review`,
      decision,
    ).then((r) => json<FindingDetail>(r)),

  // remediation
  listCases: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/remediation-cases`).then((r) =>
      json<RemediationCase[]>(r),
    ),
  getCase: (orgId: string, caseId: string) =>
    fetch(`/api/organizations/${orgId}/remediation-cases/${caseId}`).then((r) =>
      json<RemediationCaseDetail>(r),
    ),
  createCase: (orgId: string, body: { finding_id: string; title?: string }) =>
    post(`/api/organizations/${orgId}/remediation-cases`, body).then((r) =>
      json<RemediationCaseDetail>(r),
    ),
  linkSuggestions: (orgId: string, caseId: string) =>
    fetch(`/api/organizations/${orgId}/remediation-cases/${caseId}/link-suggestions`).then(
      (r) => json<LinkSuggestion[]>(r),
    ),
  linkFinding: (
    orgId: string,
    caseId: string,
    body: {
      finding_id: string;
      decision: "link" | "reject";
      link_source?: "search_suggested" | "manual";
      link_note?: string;
    },
  ) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/findings`, body).then(
      (r) => json<RemediationCaseDetail>(r),
    ),
  unlinkFinding: (orgId: string, caseId: string, findingId: string) =>
    fetch(`/api/organizations/${orgId}/remediation-cases/${caseId}/findings/${findingId}`, {
      method: "DELETE",
    }).then((r) => json<RemediationCaseDetail>(r)),
  redraftTriage: (orgId: string, caseId: string) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/triage/redraft`, {}).then(
      (r) => json<TriageDraft>(r),
    ),
  approveTriage: (
    orgId: string,
    caseId: string,
    body: {
      triage_draft_id: string;
      classification?: Classification;
      correction_note?: string;
      scope?: RemediationScope;
      scope_rationale?: string;
      reviewer_label?: string;
    },
  ) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/triage/approve`, body).then(
      (r) => json<RemediationCaseDetail>(r),
    ),
  reopenTriage: (orgId: string, caseId: string) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/triage/reopen`, {}).then(
      (r) => json<RemediationCaseDetail>(r),
    ),
  draftPlan: (orgId: string, caseId: string) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/plans`, {}).then((r) =>
      json<RemediationPlan>(r),
    ),
  reviewAction: (
    orgId: string,
    caseId: string,
    actionId: string,
    body: {
      action: "approve" | "edit" | "reject";
      description?: string;
      rationale?: string;
      owner_role?: string;
      success_criterion?: string;
      priority?: "haute" | "normale" | "basse";
      impacted_requirement_ids?: string[];
      review_note?: string;
      reviewer_label?: string;
    },
  ) =>
    post(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/actions/${actionId}/review`,
      body,
    ).then((r) => json<RemediationAction>(r)),
  changeLifecycle: (
    orgId: string,
    caseId: string,
    actionId: string,
    lifecycle: "IN_PROGRESS" | "DONE" | "CANCELLED",
  ) =>
    post(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/actions/${actionId}/lifecycle`,
      { lifecycle },
    ).then((r) => json<RemediationAction>(r)),
  recordEffectiveness: (
    orgId: string,
    caseId: string,
    actionId: string,
    body: {
      effectiveness: "EFFECTIVE" | "PARTIALLY_EFFECTIVE" | "INEFFECTIVE";
      note: string;
      reassessment_id?: string | null;
    },
  ) =>
    post(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/actions/${actionId}/effectiveness`,
      body,
    ).then((r) => json<RemediationAction>(r)),
  launchReassessment: (orgId: string, caseId: string, selectedActionIds: string[]) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/reassessments`, {
      selected_action_ids: selectedActionIds,
    }).then((r) => json<Reassessment>(r)),
  listReassessments: (orgId: string, caseId: string) =>
    fetch(`/api/organizations/${orgId}/remediation-cases/${caseId}/reassessments`).then((r) =>
      json<Reassessment[]>(r),
    ),
  closeCase: (orgId: string, caseId: string, closeNote: string) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/close`, {
      close_note: closeNote,
    }).then((r) => json<RemediationCaseDetail>(r)),
  reopenCase: (orgId: string, caseId: string) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/reopen`, {}).then((r) =>
      json<RemediationCaseDetail>(r),
    ),

  // chat
  listConversations: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/chat/conversations`).then((r) =>
      json<Conversation[]>(r),
    ),
  listMessages: (orgId: string, conversationId: string) =>
    fetch(`/api/organizations/${orgId}/chat/conversations/${conversationId}/messages`).then(
      (r) => json<ChatMessage[]>(r),
    ),
  postMessage: (orgId: string, question: string, conversationId?: string) =>
    post(`/api/organizations/${orgId}/chat/messages`, {
      question,
      conversation_id: conversationId ?? null,
    }).then((r) => json<ChatMessage>(r)),
};
