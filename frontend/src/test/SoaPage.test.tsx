import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SoaPage from "../pages/SoaPage";
import { renderWithProviders, makeScope } from "./helpers";
import type { SoaControlRow, SoaTable } from "../api";

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      getSoa: vi.fn(),
      putSoaControl: vi.fn(),
      getSoaHistory: vi.fn(),
    },
  };
});

import { api } from "../api";
const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function makeControl(over: Partial<SoaControlRow> = {}): SoaControlRow {
  return {
    control_id: "A.9.2",
    domain: "A.9",
    domain_title_fr: "Utilisation des systèmes d'IA",
    requirement_fr: null,
    applicable: true,
    justification_fr: null,
    editor_label: null,
    decision_count: 0,
    updated_at: null,
    is_default: true,
    status: "non_evalue",
    human_verdict: null,
    in_scope: false,
    finding_id: null,
    assessment_id: null,
    weight: 3,
    weight_source: "policy",
    ...over,
  };
}

function makeSoa(controls: SoaControlRow[]): SoaTable {
  return {
    scope: makeScope(),
    applicability_scope: "organization_current",
    controls,
    domains: [
      {
        domain: "A.9",
        domain_title_fr: "Utilisation des systèmes d'IA",
        controls: controls.length,
        applicable: controls.filter((c) => c.applicable).length,
        conforme: 0,
        ecart: 0,
        non_evalue: controls.length,
      },
    ],
  };
}

function renderPage() {
  return renderWithProviders(<SoaPage />, {
    route: "/organizations/org-1/soa",
    path: "/organizations/:orgId/soa",
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SoaPage", () => {
  it("renders per-control rows with default applicability and status chips", async () => {
    mocked.getSoa.mockResolvedValue(
      makeSoa([
        makeControl(),
        makeControl({
          control_id: "A.9.4",
          status: "ecart",
          human_verdict: "partial",
          requirement_fr: "Texte du constat A.9.4",
          finding_id: "fid-1",
          assessment_id: "aid-1",
        }),
      ]),
    );
    renderPage();
    expect(await screen.findByText("A.9.2")).toBeInTheDocument();
    expect(screen.getAllByText("(par défaut)")).toHaveLength(2);
    // evaluation status renders in user language, never the raw enum value
    expect(screen.getByText("Écart confirmé")).toBeInTheDocument();
    // « applicable » (SoA) must never be presented as « conforme »
    expect(screen.getAllByText("applicable").length).toBeGreaterThan(0);
    expect(screen.getByText("Texte du constat A.9.4")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Constat associé" }).getAttribute("href")).toContain(
      "/assessments/aid-1",
    );
    // annotate-not-filter posture stated
    expect(screen.getByText(/ne modifie jamais les scores/)).toBeInTheDocument();
  });

  it("saves a decision with a required justification", async () => {
    mocked.getSoa.mockResolvedValue(makeSoa([makeControl()]));
    mocked.putSoaControl.mockResolvedValue({
      control_id: "A.9.2",
      applicable: false,
      justification_fr: "Hors périmètre.",
      decision_count: 1,
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Modifier" }));
    const submit = screen.getByRole("button", { name: "Enregistrer la décision" });
    expect(submit).toBeDisabled(); // justification required
    await userEvent.click(screen.getByLabelText(/Contrôle applicable/));
    await userEvent.type(screen.getByLabelText(/Justification/), "Hors périmètre.");
    await userEvent.click(submit);
    await waitFor(() =>
      expect(mocked.putSoaControl).toHaveBeenCalledWith("org-1", "A.9.2", {
        applicable: false,
        justification_fr: "Hors périmètre.",
      }),
    );
  });

  it("shows the append-only decision history on demand", async () => {
    mocked.getSoa.mockResolvedValue(
      makeSoa([
        makeControl({
          decision_count: 2,
          is_default: false,
          applicable: true,
          justification_fr: "Finalement applicable.",
        }),
      ]),
    );
    mocked.getSoaHistory.mockResolvedValue([
      {
        sequence: 1,
        applicable: false,
        justification_fr: "Non applicable.",
        editor_label: "Yas",
        created_at: "2026-07-12T10:00:00Z",
      },
      {
        sequence: 2,
        applicable: true,
        justification_fr: "Finalement applicable.",
        editor_label: null,
        created_at: "2026-07-12T11:00:00Z",
      },
    ]);
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Historique (2)" }));
    expect(await screen.findByText(/n°1 — non applicable : Non applicable\./)).toBeInTheDocument();
    expect(screen.getByText(/n°2 — applicable : Finalement applicable\./)).toBeInTheDocument();
  });
});
