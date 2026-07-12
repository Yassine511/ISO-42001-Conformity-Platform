import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { Assessment, FindingDetail, FindingSummary, ReportingScopeMeta } from "../api";

export function renderWithProviders(ui: ReactElement, { route = "/", path = "*" } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export function makeScope(over: Partial<ReportingScopeMeta> = {}): ReportingScopeMeta {
  return {
    mode: "organization",
    assessment_id: null,
    assessment_status: null,
    scoring_policy_version: "m8-1",
    corpus_versions: ["1.3.0"],
    generated_at: "2026-07-12T12:00:00Z",
    included_assessment_ids: ["aid-1"],
    excluded_preliminary_assessment_ids: [],
    legacy_manifest_missing_ids: [],
    scope_complete: true,
    is_preliminary: false,
    is_official: true,
    official_blockers: [],
    kb_total_requirements: 65,
    ...over,
  };
}

export function makeAssessment(over: Partial<Assessment> = {}): Assessment {
  return {
    id: "aid-1",
    organization_id: "org-1",
    corpus_version: "1.2.0",
    status: "RUNNING",
    requirement_ids: ["A.9.2", "A.4.5"],
    retrieval_k: 6,
    document_manifest: {
      documents: [],
      chunker_version: "2",
      chunk_count: 12,
      indexed_at: "2026-07-06T10:00:00Z",
    },
    cancel_requested: false,
    error: null,
    started_at: "2026-07-06T10:00:00Z",
    finished_at: null,
    total: 2,
    findings_done: 1,
    verified_count: 1,
    abstained_count: 0,
    reviewed_count: 0,
    manifest_complete: true,
    progress: { requirement_id: "A.4.5", node: "judge", done: 1, total: 2 },
    ...over,
  };
}

export function makeFindingSummary(over: Partial<FindingSummary> = {}): FindingSummary {
  return {
    id: "fid-1",
    requirement_id: "A.9.2",
    status: "VERIFIED",
    verdict: "compliant",
    abstain_reason: null,
    confidence: 0.9,
    domain: "Signalement des incidents",
    review_status: "PENDING",
    review_action: null,
    human_verdict: null,
    created_at: "2026-07-06T10:01:00Z",
    ...over,
  };
}

const SOURCE_QUOTE = "Les collaborateurs doivent signaler tout incident sous 48 heures.";
const CHUNK_TEXT = `Préambule. ${SOURCE_QUOTE} Suite.`;

export function makeFindingDetail(over: Partial<FindingDetail> = {}): FindingDetail {
  return {
    ...makeFindingSummary(),
    assessment_id: "aid-1",
    policy_quote: SOURCE_QUOTE,
    clause_ref: "A.9.2",
    rationale: "La politique couvre l'exigence.",
    matched_chunk_id: "chunk-1",
    match_start: CHUNK_TEXT.indexOf(SOURCE_QUOTE),
    match_end: CHUNK_TEXT.indexOf(SOURCE_QUOTE) + SOURCE_QUOTE.length,
    match_method: "exact",
    match_score: 100,
    attempts: 1,
    final_model: "fake-model-v1",
    final_provider: "fake",
    requirement_fr: "L'organisation doit définir un processus de signalement des incidents IA.",
    corpus_mismatch: false,
    source_quote: SOURCE_QUOTE,
    source_quote_error: null,
    source_quote_kind: "verified",
    retrieved: [
      {
        result_id: "chunk-1",
        source_type: "policy",
        text: CHUNK_TEXT,
        rrf_score: 0.03,
        vector_rank: 1,
        bm25_rank: 1,
        document_id: "doc-1",
        filename: "politique_ia.txt",
        page_number: 1,
        char_start: 0,
        char_end: CHUNK_TEXT.length,
        requirement_id: null,
        domain: null,
      },
    ],
    audit_log: [{ node: "verify", event: "verified" }],
    attempt_history: [
      {
        attempt_number: 1,
        prompt_version: "v7",
        parsed_ok: true,
        verifier_errors: null,
        llm_calls: [
          {
            call_number: 1,
            provider: "fake",
            requested_model: "fake-model",
            reported_model: "fake-model-v1",
            status: "SUCCESS",
            http_status: null,
            error: null,
          },
        ],
      },
    ],
    human_rationale: null,
    review_note: null,
    reviewed_at: null,
    review_count: 0,
    reviews: [],
    ...over,
  };
}
