import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RiskRegisterPage from "../pages/RiskRegisterPage";
import { renderWithProviders, makeScope } from "./helpers";
import type { RiskRegister, RiskRow } from "../api";

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      getRiskRegister: vi.fn(),
      createCase: vi.fn(),
    },
  };
});

import { api } from "../api";
const mocked = api as unknown as {
  getRiskRegister: ReturnType<typeof vi.fn>;
  createCase: ReturnType<typeof vi.fn>;
};

function makeRow(over: Partial<RiskRow> = {}): RiskRow {
  return {
    requirement_id: "A.7.4",
    domain: "A.7",
    domain_title_fr: "Données pour les systèmes d'IA",
    requirement_fr: "Exigence de qualité des données.",
    human_verdict: "non_compliant",
    gap_factor: 2,
    weight: 3,
    weight_source: "policy",
    severity_score: 6,
    severity: "high",
    risk_statement_fr:
      "Risque de données d'entraînement ou d'exploitation non tracées : exigence A.7.4 en écart.",
    finding_id: "fid-1",
    assessment_id: "aid-1",
    reviewed_at: "2026-07-12T10:00:00Z",
    treatment: null,
    ...over,
  };
}

function makeRegister(rows: RiskRow[]): RiskRegister {
  return {
    scope: makeScope(),
    rows,
    counts: {
      high: rows.filter((r) => r.severity === "high").length,
      medium: rows.filter((r) => r.severity === "medium").length,
      low: rows.filter((r) => r.severity === "low").length,
      unscored: rows.filter((r) => r.severity === null).length,
    },
  };
}

function renderPage() {
  return renderWithProviders(<RiskRegisterPage />, {
    route: "/organizations/org-1/risk-register",
    path: "/organizations/:orgId/risk-register",
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("RiskRegisterPage", () => {
  it("renders severity badges, statements and the treatment case link", async () => {
    mocked.getRiskRegister.mockResolvedValue(
      makeRegister([
        makeRow(),
        makeRow({
          requirement_id: "7.3",
          finding_id: "fid-2",
          human_verdict: "partial",
          gap_factor: 1,
          weight: 1,
          severity_score: 1,
          severity: "low",
          risk_statement_fr: "Risque de moyens insuffisants : exigence 7.3 en écart.",
          treatment: {
            active_case_id: "case-9",
            active_case_status: "IN_PROGRESS",
            approved_action_count: 2,
            closed_case_ids: [],
          },
        }),
      ]),
    );
    renderPage();
    expect(await screen.findByText("Élevée (6)")).toBeInTheDocument();
    expect(screen.getByText(/exigence A.7.4 en écart/)).toBeInTheDocument();
    const caseLink = screen.getByRole("link", { name: /Cas en cours/ });
    expect(caseLink.getAttribute("href")).toContain("/remediation/case-9");
    expect(screen.getByText(/2 action\(s\) approuvée\(s\) au plan actif/)).toBeInTheDocument();
  });

  it("marks an unscored severity explicitly", async () => {
    mocked.getRiskRegister.mockResolvedValue(
      makeRegister([
        makeRow({ weight: null, weight_source: "unscored_weight", severity: null, severity_score: null }),
      ]),
    );
    renderPage();
    expect(await screen.findByText("non évaluée")).toBeInTheDocument();
  });

  it("opens a remediation case from a register row (AI-triage handoff noted)", async () => {
    mocked.getRiskRegister.mockResolvedValue(makeRegister([makeRow()]));
    mocked.createCase.mockResolvedValue({ id: "case-new" });
    renderPage();
    const btn = await screen.findByRole("button", { name: "Ouvrir un cas de remédiation" });
    expect(screen.getByText(/triage assisté par IA/)).toBeInTheDocument();
    await userEvent.click(btn);
    await waitFor(() =>
      expect(mocked.createCase).toHaveBeenCalledWith("org-1", { finding_id: "fid-1" }),
    );
  });

  it("filters rows by severity", async () => {
    mocked.getRiskRegister.mockResolvedValue(
      makeRegister([
        makeRow(),
        makeRow({
          requirement_id: "7.3",
          finding_id: "fid-2",
          human_verdict: "partial",
          severity: "low",
          severity_score: 1,
        }),
      ]),
    );
    renderPage();
    await screen.findByText("A.7.4");
    await userEvent.click(screen.getByRole("button", { name: /Élevée \(1\)/ }));
    expect(screen.queryByText("7.3")).not.toBeInTheDocument();
    expect(screen.getByText("A.7.4")).toBeInTheDocument();
  });
});
