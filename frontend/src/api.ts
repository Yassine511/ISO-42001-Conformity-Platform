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
