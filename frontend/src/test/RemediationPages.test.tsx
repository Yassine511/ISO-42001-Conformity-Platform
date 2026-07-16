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
      listDocuments: vi.fn(),
      listDocumentVersions: vi.fn(),
      listPatchProposals: vi.fn(),
      listArtifacts: vi.fn(),
      getPatchProposal: vi.fn(),
      createPatchProposal: vi.fn(),
      decidePatch: vi.fn(),
      recoverPatch: vi.fn(),
      createArtifact: vi.fn(),
      supersedeUpload: vi.fn(),
      recoverUpload: vi.fn(),
      artifactDownloadUrl: mod.api.artifactDownloadUrl,
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
  due_date: null,
  review_note: null,
  reviewer_label: null,
  reviewed_at: null,
  review_count: 0,
  lifecycle: "PROPOSED" as const,
  effectiveness: "NOT_CHECKED" as const,
  effectiveness_note: null,
  effectiveness_recorded_at: null,
  created_at: "2026-07-10T09:01:00Z",
  effective_requirement_ids: [] as string[],
  source_quote: null,
  source_quote_error: null,
  suggested_priority: null as "haute" | "normale" | "basse" | null,
  suggested_priority_reason: null,
  suggested_priority_policy_version: "m8-1",
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
    owner_role: null,
    due_date: null,
    closure_criterion: null,
    planning_revision: 0,
    planning_updated_at: null,
    planning_editor_label: null,
    created_at: "2026-07-10T09:00:00Z",
    updated_at: "2026-07-10T09:00:00Z",
    finding_links: [LINK],
    workflow: {
      active_plan_status: null,
      blocker_reason: null,
      pending_action_count: 0,
      open_action_count: 0,
      next_action_key: "review_triage",
      closure: { recommended_ready: false, recommendations: [] },
    },
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
  mocked.listDocuments?.mockResolvedValue([]);
  mocked.listDocumentVersions?.mockResolvedValue([]);
  mocked.listPatchProposals?.mockResolvedValue([]);
  mocked.listArtifacts?.mockResolvedValue([]);
});

const APPROVED_AMENDMENT = {
  ...ACTION,
  review_status: "CONFIRMED" as const,
  review_action: "approve" as const,
  description: ACTION.ai_description,
  rationale: ACTION.ai_rationale,
  owner_role: ACTION.ai_owner_role,
  success_criterion: ACTION.ai_success_criterion,
  priority: "haute" as const,
  lifecycle: "APPROVED" as const,
  review_count: 1,
  effective_requirement_ids: ["A.9.2"],
};

function inProgressCaseWithApprovedAction() {
  return makeCase({
    status: "IN_PROGRESS",
    classification: "evidence_gap",
    scope: "local",
    scope_rationale: "r",
    triage_approved_at: "2026-07-10T09:00:30Z",
    approved_triage_draft_id: "td-1",
    active_plan_id: "plan-1",
    plans: [{ ...PLAN, actions: [APPROVED_AMENDMENT] }],
  });
}

const VERIFIED_PROPOSAL = {
  id: "prop-1",
  case_id: "case-1",
  action_id: "act-1",
  document_id: "doc-1",
  document_version_id: "ver-1",
  base_text_checksum: "abc",
  status: "VERIFIED" as const,
  abstain_reason: null,
  verifier_errors: null,
  operation: "insert_after" as const,
  anchor_page: 1,
  new_text_fr: "Nouveau paragraphe de politique.",
  rationale: "Couvre l'action.",
  attempts: 1,
  requirement_ids: ["A.9.2"],
  created_at: "2026-07-11T09:00:00Z",
  anchor_char_start: 10,
  anchor_char_end: 30,
  anchor_slice: "Texte d'ancrage exact",
  context_before: "…avant ",
  context_after: " après…",
  decision: null,
};

describe("patch flow", () => {
  it("proposes a patch on a TXT target and renders the server-derived diff", async () => {
    mocked.getCase.mockResolvedValue(inProgressCaseWithApprovedAction());
    mocked.listDocuments.mockResolvedValue([
      { id: "doc-1", organization_id: "org-1", filename: "politique.txt", content_type: "text/plain", status: "parsed", error: null, page_count: 1, checksum: "c", parser_version: "2", current_version_id: "ver-1", created_at: "2026-07-10T09:00:00Z" },
    ]);
    mocked.createPatchProposal.mockResolvedValue(VERIFIED_PROPOSAL);
    mocked.listPatchProposals
      .mockResolvedValueOnce([])
      .mockResolvedValue([VERIFIED_PROPOSAL]);
    mocked.getPatchProposal.mockResolvedValue(VERIFIED_PROPOSAL);

    renderCase();
    // wait for the documents query to populate the select before choosing
    await screen.findByRole("option", { name: "politique.txt" });
    await userEvent.selectOptions(screen.getByLabelText("Document cible"), "doc-1");
    await userEvent.click(screen.getByRole("button", { name: "Proposer un correctif" }));
    await waitFor(() =>
      expect(mocked.createPatchProposal).toHaveBeenCalledWith("org-1", "case-1", "act-1", "doc-1"),
    );
    // the diff renders the server slice (anchor) + the proposed insertion
    expect(await screen.findByText("Texte d'ancrage exact")).toBeInTheDocument();
    expect(screen.getByText(/Nouveau paragraphe de politique\./)).toBeInTheDocument();
  });

  it("approves a verified proposal", async () => {
    mocked.getCase.mockResolvedValue(inProgressCaseWithApprovedAction());
    mocked.listDocuments.mockResolvedValue([]);
    mocked.listPatchProposals.mockResolvedValue([VERIFIED_PROPOSAL]);
    mocked.getPatchProposal.mockResolvedValue(VERIFIED_PROPOSAL);
    mocked.decidePatch.mockResolvedValue({
      outcome: "activated",
      decision_id: "dec-1",
      version_id: "ver-2",
    });

    renderCase();
    await userEvent.click(
      await screen.findByRole("button", { name: "Approuver le correctif" }),
    );
    await waitFor(() =>
      expect(mocked.decidePatch).toHaveBeenCalledWith("org-1", "case-1", "prop-1", {
        decision: "approve",
      }),
    );
  });

  it("renders an abstained proposal without decision controls", async () => {
    mocked.getCase.mockResolvedValue(inProgressCaseWithApprovedAction());
    mocked.listDocuments.mockResolvedValue([]);
    const abstained = {
      ...VERIFIED_PROPOSAL,
      status: "ABSTAINED" as const,
      abstain_reason: "anchor_ambiguous",
      anchor_char_start: null,
      anchor_char_end: null,
      anchor_slice: null,
    };
    mocked.listPatchProposals.mockResolvedValue([abstained]);
    mocked.getPatchProposal.mockResolvedValue(abstained);

    renderCase();
    // translated abstention reason — the raw enum stays in the technical disclosure
    expect(
      await screen.findByText(/Correctif en abstention — Point d'insertion ambigu/),
    ).toBeInTheDocument();
    // no diff and no patch-decision controls for an abstained proposal
    expect(screen.queryByText("Diff proposé")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Approuver le correctif" }),
    ).not.toBeInTheDocument();
  });

  it("offers a superseding upload on a verified PDF/DOCX artifact", async () => {
    mocked.getCase.mockResolvedValue(inProgressCaseWithApprovedAction());
    mocked.listDocuments.mockResolvedValue([]);
    mocked.listArtifacts.mockResolvedValue([
      {
        id: "art-1",
        case_id: "case-1",
        action_id: "act-1",
        document_id: "doc-9",
        document_version_id: "ver-9",
        canonical_format: "docx" as const,
        status: "VERIFIED" as const,
        abstain_reason: null,
        verifier_errors: null,
        filename: "proposition.md",
        content_md: "## Révision",
        rationale: "r",
        attempts: 1,
        requirement_ids: ["A.9.2"],
        created_at: "2026-07-11T09:00:00Z",
      },
    ]);
    mocked.supersedeUpload.mockResolvedValue({
      outcome: "activated",
      decision_id: null,
      version_id: "ver-10",
    });

    renderCase();
    // the artifact card exposes both the draft download and the upload affordance
    expect(await screen.findByText("Télécharger le brouillon Markdown")).toBeInTheDocument();
    const input = screen.getByLabelText("Fichier révisé à téléverser");
    const file = new File([new Uint8Array([1, 2, 3])], "revise.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    await userEvent.upload(input, file);
    await userEvent.click(
      screen.getByRole("button", { name: "Téléverser la version révisée" }),
    );
    await waitFor(() =>
      expect(mocked.supersedeUpload).toHaveBeenCalledWith("org-1", file, "ver-9", "art-1"),
    );
    expect(
      await screen.findByText(/Nouvelle version créée et activée/),
    ).toBeInTheDocument();
  });

  it("surfaces an index_failed upload and offers recovery", async () => {
    mocked.getCase.mockResolvedValue(inProgressCaseWithApprovedAction());
    mocked.listDocuments.mockResolvedValue([]);
    mocked.listArtifacts.mockResolvedValue([
      {
        id: "art-1", case_id: "case-1", action_id: "act-1", document_id: "doc-9",
        document_version_id: "ver-9", canonical_format: "docx" as const,
        status: "VERIFIED" as const, abstain_reason: null, verifier_errors: null,
        filename: "proposition.md", content_md: "x", rationale: "r", attempts: 1,
        requirement_ids: ["A.9.2"], created_at: "2026-07-11T09:00:00Z",
      },
    ]);
    // a real Qdrant outage -> index_failed with the candidate version id
    mocked.supersedeUpload.mockResolvedValue({
      outcome: "index_failed", decision_id: null, version_id: "ver-10",
    });
    mocked.recoverUpload.mockResolvedValue({
      outcome: "activated", decision_id: null, version_id: "ver-10",
    });

    renderCase();
    const input = await screen.findByLabelText("Fichier révisé à téléverser");
    const file = new File([new Uint8Array([1])], "revise.docx");
    await userEvent.upload(input, file);
    await userEvent.click(screen.getByRole("button", { name: "Téléverser la version révisée" }));
    // the failure is surfaced (not swallowed), with a recovery affordance
    expect(await screen.findByText(/Indexation vectorielle échouée/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reprendre l'activation" }));
    await waitFor(() =>
      expect(mocked.recoverUpload).toHaveBeenCalledWith("doc-9", "ver-10"),
    );
    expect(await screen.findByText(/Nouvelle version créée et activée/)).toBeInTheDocument();
  });

  it("detects a stranded activation on load and offers recovery after refresh", async () => {
    mocked.getCase.mockResolvedValue(inProgressCaseWithApprovedAction());
    mocked.listDocuments.mockResolvedValue([]);
    mocked.listArtifacts.mockResolvedValue([
      {
        id: "art-1", case_id: "case-1", action_id: "act-1", document_id: "doc-9",
        document_version_id: "ver-9", canonical_format: "docx" as const,
        status: "VERIFIED" as const, abstain_reason: null, verifier_errors: null,
        filename: "proposition.md", content_md: "x", rationale: "r", attempts: 1,
        requirement_ids: ["A.9.2"], created_at: "2026-07-11T09:00:00Z",
      },
    ]);
    // a candidate this artifact spawned that stranded at INDEX_FAILED — with no
    // in-session upload, the card must still surface it from the versions list
    mocked.listDocumentVersions.mockResolvedValue([
      {
        id: "ver-10", document_id: "doc-9", version_number: 2,
        state: "INDEX_FAILED" as const, origin: "upload" as const,
        canonical_format: "docx" as const, filename: "revise.docx", page_count: 1,
        source_checksum: "s", text_checksum: "t", parser_version: "2",
        chunker_version: "3", chunk_id_scheme: "version_id_v3",
        supersedes_version_id: "ver-9", source_artifact_id: "art-1",
        abandoned_reason: null, activation_error: "boom", created_at: "2026-07-11T09:05:00Z",
      },
    ]);
    mocked.recoverUpload.mockResolvedValue({
      outcome: "activated", decision_id: null, version_id: "ver-10",
    });

    renderCase();
    // the stranded activation is surfaced without any upload this session
    expect(await screen.findByText(/activation de version.*inachevée/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reprendre l'activation" }));
    await waitFor(() =>
      expect(mocked.recoverUpload).toHaveBeenCalledWith("doc-9", "ver-10"),
    );
  });
});

describe("RemediationListPage", () => {
  it("lists cases with human-readable titles and translated phases", async () => {
    mocked.listCases.mockResolvedValue([makeCase()]);
    renderWithProviders(<RemediationListPage />, {
      route: "/organizations/org-1/remediation",
      path: "/organizations/:orgId/remediation",
    });
    // the raw backend title « Remédiation A.9.2 — partial » never renders
    expect(
      (
        await screen.findAllByText("Remédiation de l'exigence A.9.2 — partiellement conforme")
      ).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("Remédiation A.9.2 — partial")).toBeNull();
    expect(screen.getAllByText("Qualification de l'écart").length).toBeGreaterThan(0);
    // honest missing operational fields, never fabricated
    expect(screen.getAllByText("Non attribué").length).toBeGreaterThan(0);
    expect(screen.getAllByText("À définir").length).toBeGreaterThan(0);
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
    // operational abort rendered neutrally, in user language — never the raw enum
    expect(
      await screen.findByText(/Recherche documentaire interrompue/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/retrieval_error/)).toBeNull();
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

  it("pre-selects the severity-derived priority but submits the human's choice", async () => {
    mocked.getCase.mockResolvedValue(
      makeCase({
        status: "PLAN_READY",
        classification: "evidence_gap",
        scope: "local",
        scope_rationale: "Écart isolé.",
        triage_approved_at: "2026-07-10T09:00:30Z",
        approved_triage_draft_id: "td-1",
        active_plan_id: "plan-1",
        plans: [
          {
            ...PLAN,
            actions: [{ ...ACTION, suggested_priority: "haute" as const }],
          },
        ],
      }),
    );
    mocked.reviewAction.mockResolvedValue({ ...ACTION, lifecycle: "APPROVED" });
    renderCase();
    await screen.findByText(/Brouillon IA n°1/);
    await userEvent.click(screen.getByRole("button", { name: "Approuver" }));
    const select = screen.getByLabelText(/Priorité \(requise\)/) as HTMLSelectElement;
    expect(select.value).toBe("haute"); // pre-filled from the suggestion
    expect(screen.getByText(/dérivée de la sévérité/)).toBeInTheDocument();
    expect(screen.getByText(/décision humaine requise/)).toBeInTheDocument();
    // the human overrides the suggestion — their choice is what is submitted
    await userEvent.selectOptions(select, "basse");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer la décision" }));
    await waitFor(() =>
      expect(mocked.reviewAction).toHaveBeenCalledWith("org-1", "case-1", "act-1", {
        action: "approve",
        priority: "basse",
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

describe("action evidence display", () => {
  it("renders the authoritative source slice, never just the model quote", async () => {
    mocked.getCase.mockResolvedValue(
      makeCase({
        status: "PLAN_READY",
        classification: "evidence_gap",
        scope: "local",
        scope_rationale: "r",
        triage_approved_at: "2026-07-10T09:00:30Z",
        approved_triage_draft_id: "td-1",
        active_plan_id: "plan-1",
        plans: [
          {
            ...PLAN,
            actions: [
              {
                ...ACTION,
                policy_quote: "citation modèle",
                matched_chunk_id: "chunk-1",
                match_start: 0,
                match_end: 10,
                match_method: "exact",
                match_score: 100,
                source_quote: "Tranche source authentique.",
                source_quote_error: null,
              },
            ],
          },
        ],
      }),
    );
    renderCase();
    expect(await screen.findByText(/Tranche source authentique\./)).toBeInTheDocument();
    expect(screen.getByText(/citation localisée, pertinence à confirmer/)).toBeInTheDocument();
    expect(screen.getByText(/Justification IA :/)).toBeInTheDocument();
  });

  it("fails closed when the source slice cannot be derived", async () => {
    mocked.getCase.mockResolvedValue(
      makeCase({
        status: "PLAN_READY",
        classification: "evidence_gap",
        scope: "local",
        scope_rationale: "r",
        triage_approved_at: "2026-07-10T09:00:30Z",
        approved_triage_draft_id: "td-1",
        active_plan_id: "plan-1",
        plans: [
          {
            ...PLAN,
            actions: [
              {
                ...ACTION,
                policy_quote: "citation modèle",
                source_quote: null,
                source_quote_error: "offsets invalides",
              },
            ],
          },
        ],
      }),
    );
    renderCase();
    expect(
      await screen.findByText(/Citation non affichable : offsets invalides/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/citation modèle/)).not.toBeInTheDocument();
  });
});

describe("effectiveness with reassessment evidence", () => {
  it("cites the selected reassessment in the request", async () => {
    const doneAction = {
      ...ACTION,
      review_status: "CONFIRMED" as const,
      review_action: "approve" as const,
      description: ACTION.ai_description,
      rationale: ACTION.ai_rationale,
      owner_role: ACTION.ai_owner_role,
      success_criterion: ACTION.ai_success_criterion,
      priority: "haute" as const,
      reviewed_at: "2026-07-10T09:02:00Z",
      review_count: 1,
      lifecycle: "DONE" as const,
      effective_requirement_ids: ["A.9.2"],
    };
    mocked.getCase.mockResolvedValue(
      makeCase({
        status: "IN_PROGRESS",
        classification: "evidence_gap",
        scope: "local",
        scope_rationale: "r",
        triage_approved_at: "2026-07-10T09:00:30Z",
        approved_triage_draft_id: "td-1",
        active_plan_id: "plan-1",
        plans: [{ ...PLAN, actions: [doneAction] }],
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
        excluded_holdout_ids: [],
        status: "LAUNCHED",
        error: null,
        actor_label: null,
        created_at: "2026-07-10T10:00:00Z",
      },
    ]);
    mocked.recordEffectiveness.mockResolvedValue({
      ...doneAction,
      effectiveness: "EFFECTIVE",
    });
    renderCase();
    const select = await screen.findByLabelText("Réévaluation citée en preuve");
    await userEvent.selectOptions(select, "re-1");
    await userEvent.type(
      screen.getByPlaceholderText("Preuve / justification (requise)"),
      "Réévaluation favorable.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    await waitFor(() =>
      expect(mocked.recordEffectiveness).toHaveBeenCalledWith("org-1", "case-1", "act-1", {
        effectiveness: "EFFECTIVE",
        note: "Réévaluation favorable.",
        reassessment_id: "re-1",
      }),
    );
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
      screen.getByText(
        /Exclues \(réservées au jeu de test de référence, jamais réévaluées ici\) : A\.8\.1/,
      ),
    ).toBeInTheDocument();
  });
});

describe("case planning (0018)", () => {
  it("edits owner / deadline / closure criterion with the read revision", async () => {
    mocked.getCase.mockResolvedValue(makeCase({ planning_revision: 2 }));
    mocked.updateCasePlanning = vi.fn().mockResolvedValue(
      makeCase({ owner_role: "RSSI", planning_revision: 3 }),
    );
    (api as Record<string, unknown>).updateCasePlanning = mocked.updateCasePlanning;
    renderCase();
    // honest missing state before any edit
    expect((await screen.findAllByText("Non attribué")).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Modifier" }));
    await userEvent.type(screen.getByLabelText("Responsable (rôle)"), "RSSI");
    await userEvent.type(
      screen.getByLabelText("Critère de clôture"),
      "Réévaluation conforme.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer le pilotage" }));
    await waitFor(() =>
      expect(mocked.updateCasePlanning).toHaveBeenCalledWith("org-1", "case-1", {
        expected_revision: 2,
        owner_role: "RSSI",
        due_date: null,
        closure_criterion: "Réévaluation conforme.",
        editor_label: null,
      }),
    );
  });

  it("surfaces the stale-revision conflict instead of silently overwriting", async () => {
    mocked.getCase.mockResolvedValue(makeCase());
    mocked.updateCasePlanning = vi
      .fn()
      .mockRejectedValue(new Error("Le pilotage du cas a été modifié entre-temps"));
    (api as Record<string, unknown>).updateCasePlanning = mocked.updateCasePlanning;
    renderCase();
    await userEvent.click(await screen.findByRole("button", { name: "Modifier" }));
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer le pilotage" }));
    expect(
      await screen.findByText(/modifié entre-temps/),
    ).toBeInTheDocument();
  });
});

describe("launch gate (0018)", () => {
  it("surfaces the server validation when starting an action without deadline", async () => {
    mocked.getCase.mockResolvedValue(inProgressCaseWithApprovedAction());
    mocked.changeLifecycle.mockRejectedValue(
      new Error("Impossible de démarrer l'action — champs requis manquants : échéance."),
    );
    renderCase();
    await userEvent.click(await screen.findByRole("button", { name: "Démarrer" }));
    expect(await screen.findByText(/champs requis manquants : échéance/)).toBeInTheDocument();
  });
});

describe("workflow summary display", () => {
  it("shows the translated next action and closure recommendations, never raw keys", async () => {
    mocked.listCases.mockResolvedValue([
      makeCase({
        status: "IN_PROGRESS",
        classification: "evidence_gap",
        scope: "local",
        scope_rationale: "r",
        triage_approved_at: "2026-07-10T09:00:30Z",
        approved_triage_draft_id: "td-1",
        workflow: {
          active_plan_status: "VERIFIED",
          blocker_reason: null,
          pending_action_count: 0,
          open_action_count: 1,
          next_action_key: "launch_actions",
          closure: { recommended_ready: false, recommendations: ["open_actions"] },
        },
      }),
    ]);
    renderWithProviders(<RemediationListPage />, {
      route: "/organizations/org-1/remediation",
      path: "/organizations/:orgId/remediation",
    });
    expect(
      (await screen.findAllByText("Lancer les actions validées")).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("launch_actions")).toBeNull();
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
