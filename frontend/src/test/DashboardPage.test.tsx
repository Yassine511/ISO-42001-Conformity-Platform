import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DashboardPage from "../pages/DashboardPage";
import { renderWithProviders, makeAssessment, makeScope } from "./helpers";
import type { ConformityReport, TrustPanel } from "../api";

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listAssessments: vi.fn(),
      getConformity: vi.fn(),
      getTrustPanel: vi.fn(),
    },
  };
});

import { api } from "../api";
const mocked = api as unknown as {
  listAssessments: ReturnType<typeof vi.fn>;
  getConformity: ReturnType<typeof vi.fn>;
  getTrustPanel: ReturnType<typeof vi.fn>;
};

function makeConformity(over: Partial<ConformityReport> = {}): ConformityReport {
  return {
    scope: makeScope(over.scope),
    global_pct: 75.0,
    scored: 2,
    total_in_scope: 4,
    coverage_pct: 50.0,
    verdict_counts: { compliant: 1, partial: 1, non_compliant: 0, missing: 0 },
    domains: [
      {
        domain: "4",
        domain_title_fr: "Contexte de l'organisation",
        total_in_scope: 4,
        scored: 2,
        pending_review: 1,
        not_assessed: 1,
        verdict_counts: { compliant: 1, partial: 1, non_compliant: 0, missing: 0 },
        pct: 75.0,
      },
    ],
    ...over,
  };
}

function makeTrust(): TrustPanel {
  return {
    scope: makeScope(),
    gate: {
      drafts_total: 5,
      drafts_parsed: 3,
      drafts_schema_invalid: 1,
      drafts_provider_failure: 1,
      legacy_unclassified: 0,
      drafts_with_unsupported_citation: 1,
      unsupported_draft_rate_pct: 25.0,
      verifier_error_code_counts: { citation_not_found: 1 },
      findings_verified: 3,
      findings_abstained: 1,
      findings_abstained_by_verifier: 1,
      abstentions_by_reason: { verification_failed: 1 },
      unsupported_citations_displayed: 0,
    },
    review: {
      review_events: 2,
      approve_events: 1,
      edit_or_override_events: 1,
      override_events: 1,
      intervention_rate_pct: 50.0,
      verdict_override_rate_pct: 50.0,
    },
    chat: {
      metric_scope: "organization",
      messages: 3,
      answered: 2,
      abstained: 1,
      stripped_citation_count: 2,
    },
    m6_benchmark: {
      label: "Référence M6 (corpus v1.2.0, holdout n=14)",
      source_artifact: "eval/m6/rapport_m6.md",
      source_artifact_sha256: "abc123def456abc123def456",
      pipeline_verdict_accuracy: "9/14",
      gate_blocked_unsupported_first_drafts: "3/14",
      unsupported_citations_displayed: 0,
      chat_citation_location_validity: "24/24",
      chat_pair_support_precision: "23/32",
      chat_faithfulness: "7/10",
    },
  };
}

function renderPage() {
  return renderWithProviders(<DashboardPage />, {
    route: "/organizations/org-1/dashboard",
    path: "/organizations/:orgId/dashboard",
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listAssessments.mockResolvedValue([makeAssessment({ status: "COMPLETED" })]);
  mocked.getConformity.mockResolvedValue(makeConformity());
  mocked.getTrustPanel.mockResolvedValue(makeTrust());
});

describe("DashboardPage", () => {
  it("renders global conformity, the coverage caption and domain rows", async () => {
    renderPage();
    expect(await screen.findByText("75%")).toBeTruthy();
    expect(
      screen.getByText(/Conformité calculée sur/).textContent,
    ).toContain("exigence(s) confirmée(s)");
    expect(screen.getByText(/4 · Contexte de l'organisation/)).toBeTruthy();
    expect(screen.getByText(/75% — 2\/4 confirmées/)).toBeTruthy();
  });

  it("renders the trust panel with the structural-invariant label and the M6 card", async () => {
    renderPage();
    expect(await screen.findByText(/invariant structurel/)).toBeTruthy();
    expect(screen.getByText(/Référence M6/)).toBeTruthy();
    expect(screen.getByText(/9\/14/)).toBeTruthy();
    expect(screen.getByText(/organisation entière/)).toBeTruthy();
  });

  it("shows amber banners for preliminary and incomplete scopes", async () => {
    mocked.getConformity.mockResolvedValue(
      makeConformity({
        scope: makeScope({
          is_preliminary: true,
          scope_complete: false,
          legacy_manifest_missing_ids: ["old-1"],
        }),
      }),
    );
    const { container } = renderPage();
    await screen.findByText("75%");
    expect(container.textContent).toContain("Résultat préliminaire");
    expect(container.textContent).toContain("Périmètre incomplet");
    expect(container.textContent).toContain("ne peut pas être qualifié d'officiel");
  });

  it("shows provider failures as their own typed line", async () => {
    renderPage();
    await screen.findByText("75%");
    expect(screen.getByText("Échec fournisseur LLM")).toBeInTheDocument();
    expect(screen.getByText("Schéma invalide")).toBeInTheDocument();
  });

  it("keeps the preliminary opt-in reachable for a non-COMPLETED assessment (PDF path)", async () => {
    mocked.listAssessments.mockResolvedValue([
      makeAssessment({ id: "aid-run", status: "RUNNING" }),
    ]);
    renderPage();
    await screen.findByText("75%");
    await userEvent.selectOptions(screen.getByLabelText("Périmètre"), "aid-run");
    const checkbox = await screen.findByLabelText(/autoriser un aperçu préliminaire/);
    await userEvent.click(checkbox);
    const link = screen.getByRole("link", { name: /Exporter le rapport PDF/ });
    expect(link.getAttribute("href")).toContain("assessment_id=aid-run");
    expect(link.getAttribute("href")).toContain("include_preliminary=true");
  });

  it("refetches with assessment_id when the scope selector changes", async () => {
    renderPage();
    await screen.findByText("75%");
    const select = screen.getByLabelText("Périmètre");
    await userEvent.selectOptions(select, "aid-1");
    await waitFor(() =>
      expect(mocked.getConformity).toHaveBeenLastCalledWith(
        "org-1",
        expect.objectContaining({ assessmentId: "aid-1" }),
      ),
    );
  });
});
