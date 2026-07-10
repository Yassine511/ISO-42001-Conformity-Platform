import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type RemediationCaseDetail } from "../api";
import RemediationListPage from "../pages/RemediationListPage";
import RemediationCasePage from "../pages/RemediationCasePage";
import { renderWithProviders } from "./helpers";

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listCases: vi.fn(),
      getCase: vi.fn(),
      linkSuggestions: vi.fn(),
      linkFinding: vi.fn(),
      unlinkFinding: vi.fn(),
      approveTriage: vi.fn(),
      redraftTriage: vi.fn(),
      reopenTriage: vi.fn(),
      draftPlan: vi.fn(),
      reviewAction: vi.fn(),
      changeLifecycle: vi.fn(),
      recordEffectiveness: vi.fn(),
      launchReassessment: vi.fn(),
      listReassessments: vi.fn(),
      closeCase: vi.fn(),
      reopenCase: vi.fn(),
    },
  };
});

const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const LINK = {
  finding_id: "fid-1",
  is_primary: true,
  link_source: "creation" as const,
  link_note: null,
  linker_label: null,
  finding_review_count: 1,
  finding_human_verdict: "partial" as const,
  finding_human_rationale: "Couverture partielle.",
  finding_requirement_id: "A.9.2",
  finding_requirement_fr: "Processus de signalement des incidents IA.",
  finding_domain: "Incidents",
  created_at: "2026-07-10T09:00:00Z",
};

const TRIAGE_DRAFT = {
  id: "td-1",
  sequence: 1,
  status: "VERIFIED" as const,
  abstain_reason: null,
  ai_classification: "evidence_gap" as const,
  ai_correction_note: "Documenter la preuve manquante.",
  ai_scope: "local" as const,
  ai_scope_rationale: "Écart isolé.",
  input_evidence_revision: 0,
  input_finding_links: [],
  similar_findings: [],
  similar_corpus: [],
  draft_attempts: 1,
  prompt_version: "remed-1",
  corpus_version: "1.2.0",
  final_model: "fake-model-v1",
  final_provider: "fake",
  created_at: "2026-07-10T09:00:10Z",
};

const ACTION = {
  id: "act-1",
  plan_id: "plan-1",
  position: 1,
  action_type: "document_amendment" as const,
  ai_description: "Compléter la politique d'incident.",
  ai_rationale: "Couvrir l'exigence.",
  ai_owner_role: "Responsable conformité",
  ai_success_criterion: "La politique décrit le signalement sous 48 h.",
  ai_impacted_requirement_ids: ["A.9.2"],
  policy_quote: null,
  matched_chunk_id: null,
  match_start: null,
  match_end: null,
  match_method: null,
  match_score: null,
  review_status: "PENDING" as const,
  review_action: null,
  description: null,
  rationale: null,
  owner_role: null,
  success_criterion: null,
  priority: null,
  review_note: null,
  reviewer_label: null,
  reviewed_at: null,
  review_count: 0,
  lifecycle: "PROPOSED" as const,
  effectiveness: "NOT_CHECKED" as const,
  effectiveness_note: null,
  effectiveness_recorded_at: null,
  created_at: "2026-07-10T09:01:00Z",
};

const PLAN = {
  id: "plan-1",
  case_id: "case-1",
  sequence: 1,
  status: "VERIFIED" as const,
  abstain_reason: null,
  superseded_at: null,
  superseded_by_plan_id: null,
  gap_restatement: "La preuve de signalement est partielle.",
  root_cause_hypotheses: [{ label: "H1", hypothesis: "Processus non défini." }],
  draft_attempts: 1,
  prompt_version: "remed-1",
  corpus_version: "1.2.0",
  final_model: "fake-model-v1",
  final_provider: "fake",
  input_finding_links: [],
  input_triage_snapshot: {},
  allowed_requirement_ids: ["A.9.2"],
  input_kb: { "A.9.2": { requirement_fr: "Exigence.", domain: "Incidents" } },
  created_at: "2026-07-10T09:01:00Z",
  actions: [ACTION],
};

function makeCase(over: Partial<RemediationCaseDetail> = {}): RemediationCaseDetail {
  return {
    id: "case-1",
    organization_id: "org-1",
    title: "Remédiation A.9.2 — partial",
    status: "TRIAGE",
    classification: null,
    correction_note: null,
    scope: null,
    scope_rationale: null,
    triage_approved_at: null,
    triage_reviewer_label: null,
    approved_triage_draft_id: null,
    active_plan_id: null,
    evidence_revision: 0,
    closed_at: null,
    close_note: null,
    created_at: "2026-07-10T09:00:00Z",
    updated_at: "2026-07-10T09:00:00Z",
    finding_links: [LINK],
    triage_drafts: [TRIAGE_DRAFT],
    plans: [],
    events: [
      {
        sequence: 1,
        event_type: "case_created",
        payload: {},
        payload_version: 1,
        actor_label: null,
        created_at: "2026-07-10T09:00:00Z",
      },
    ],
    ...over,
  };
}

function renderCase() {
  return renderWithProviders(<RemediationCasePage />, {
    route: "/organizations/org-1/remediation/case-1",
    path: "/organizations/:orgId/remediation/:caseId",
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listReassessments.mockResolvedValue([]);
  mocked.linkSuggestions.mockResolvedValue([]);
});

describe("RemediationListPage", () => {
  it("lists cases with status badges", async () => {
    mocked.listCases.mockResolvedValue([makeCase()]);
    renderWithProviders(<RemediationListPage />, {
      route: "/organizations/org-1/remediation",
      path: "/organizations/:orgId/remediation",
    });
    expect(await screen.findByText("Remédiation A.9.2 — partial")).toBeInTheDocument();
    expect(screen.getByText("Triage")).toBeInTheDocument();
  });
});

describe("triage panel", () => {
  it("labels the AI draft as a proposal awaiting human approval and approves the explicit draft", async () => {
    mocked.getCase.mockResolvedValue(makeCase());
    mocked.approveTriage.mockResolvedValue(makeCase({ status: "TRIAGE_APPROVED" }));
    renderCase();
    expect(
      await screen.findByText(/Proposition IA \(brouillon n°1\) — à valider par un humain/),
    ).toBeInTheDocument();
    expect(screen.getByText("en attente d'approbation humaine")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approuver le triage" }));
    await waitFor(() =>
      expect(mocked.approveTriage).toHaveBeenCalledWith("org-1", "case-1", {
        triage_draft_id: "td-1",
      }),
    );
  });

  it("renders an abstained draft neutrally when it is an operational abort", async () => {
    mocked.getCase.mockResolvedValue(
      makeCase({
        triage_drafts: [
          { ...TRIAGE_DRAFT, status: "ABSTAINED", abstain_reason: "retrieval_error",
            ai_classification: null, ai_correction_note: null, ai_scope: null,
            ai_scope_rationale: null },
        ],
      }),
    );
    renderCase();
    expect(await screen.findByText(/retrieval_error/)).toBeInTheDocument();
  });
});

describe("plan panel", () => {
  it("shows per-action review controls and requires priority via the form", async () => {
    mocked.getCase.mockResolvedValue(
      makeCase({
        status: "PLAN_READY",
        classification: "evidence_gap",
        scope: "local",
        scope_rationale: "Écart isolé.",
        triage_approved_at: "2026-07-10T09:00:30Z",
        approved_triage_draft_id: "td-1",
        active_plan_id: "plan-1",
        plans: [PLAN],
      }),
    );
    mocked.reviewAction.mockResolvedValue({ ...ACTION, lifecycle: "APPROVED" });
    renderCase();
    expect(await screen.findByText(/Brouillon IA n°1/)).toBeInTheDocument();
    expect(screen.getByText(/H1/)).toBeInTheDocument(); // labeled hypothesis
    await userEvent.click(screen.getByRole("button", { name: "Approuver" }));
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer la décision" }));
    await waitFor(() =>
      expect(mocked.reviewAction).toHaveBeenCalledWith("org-1", "case-1", "act-1", {
        action: "approve",
        priority: "normale",
      }),
    );
  });

  it("distinguishes operational aborts from agent abstentions", async () => {
    mocked.getCase.mockResolvedValue(
      makeCase({
        status: "PLAN_READY",
        classification: "evidence_gap",
        scope: "local",
        scope_rationale: "r",
        triage_approved_at: "2026-07-10T09:00:30Z",
        approved_triage_draft_id: "td-1",
        active_plan_id: "plan-2",
        plans: [
          {
            ...PLAN,
            id: "plan-2",
            status: "ABSTAINED",
            abstain_reason: "draft_interrupted",
            actions: [],
          },
        ],
      }),
    );
    renderCase();
    expect(
      await screen.findByText("Rédaction interrompue (incident technique)"),
    ).toBeInTheDocument();
  });
});

describe("reassessments", () => {
  it("shows explicit holdout exclusions, never silent filtering", async () => {
    mocked.getCase.mockResolvedValue(
      makeCase({
        status: "IN_PROGRESS",
        classification: "evidence_gap",
        scope: "local",
        scope_rationale: "r",
        triage_approved_at: "2026-07-10T09:00:30Z",
        approved_triage_draft_id: "td-1",
        active_plan_id: "plan-1",
        plans: [PLAN],
      }),
    );
    mocked.listReassessments.mockResolvedValue([
      {
        id: "re-1",
        case_id: "case-1",
        planned_assessment_id: "aid-9",
        assessment_id: "aid-9",
        selected_action_ids: ["act-1"],
        included_requirement_ids: ["A.9.2"],
        excluded_holdout_ids: ["A.8.1"],
        status: "LAUNCHED",
        error: null,
        actor_label: null,
        created_at: "2026-07-10T10:00:00Z",
      },
    ]);
    renderCase();
    expect(await screen.findByText(/Exigences réévaluées : A\.9\.2/)).toBeInTheDocument();
    expect(
      screen.getByText(/Exclues \(réservées au jeu de test M6, jamais réévaluées ici\) : A\.8\.1/),
    ).toBeInTheDocument();
  });
});

describe("closure", () => {
  it("requires a note and shows reopen on a closed case", async () => {
    mocked.getCase.mockResolvedValue(
      makeCase({
        status: "CLOSED",
        classification: "evidence_gap",
        scope: "local",
        scope_rationale: "r",
        triage_approved_at: "2026-07-10T09:00:30Z",
        approved_triage_draft_id: "td-1",
        closed_at: "2026-07-10T11:00:00Z",
        close_note: "Traité.",
      }),
    );
    mocked.reopenCase.mockResolvedValue(makeCase({ status: "TRIAGE_APPROVED" }));
    renderCase();
    await userEvent.click(await screen.findByRole("button", { name: "Rouvrir le cas" }));
    await waitFor(() => expect(mocked.reopenCase).toHaveBeenCalledWith("org-1", "case-1"));
  });
});
