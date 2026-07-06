import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import ReviewWorkspacePage from "../pages/ReviewWorkspacePage";
import {
  makeAssessment,
  makeFindingDetail,
  makeFindingSummary,
  renderWithProviders,
} from "./helpers";

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      getAssessment: vi.fn(),
      getFinding: vi.fn(),
      reviewFinding: vi.fn(),
    },
  };
});

const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function renderPage() {
  return renderWithProviders(<ReviewWorkspacePage />, {
    route: "/organizations/org-1/assessments/aid-1",
    path: "/organizations/:orgId/assessments/:assessmentId",
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getAssessment.mockResolvedValue({
    ...makeAssessment({ status: "COMPLETED", findings_done: 2, reviewed_count: 0 }),
    findings: [
      makeFindingSummary(),
      makeFindingSummary({
        id: "fid-2",
        requirement_id: "A.4.5",
        status: "ABSTAINED",
        verdict: null,
        abstain_reason: "model_abstained",
      }),
    ],
  });
  mocked.getFinding.mockResolvedValue(makeFindingDetail());
});

describe("evidence display", () => {
  it("highlights the source slice and captions the authoritative extract", async () => {
    renderPage();
    const mark = await screen.findByText(
      "Les collaborateurs doivent signaler tout incident sous 48 heures.",
      { selector: "mark" },
    );
    expect(mark).toBeInTheDocument();
    expect(screen.getByText(/Extrait source \(autoritatif\)/)).toBeInTheDocument();
    // the model quote appears only inside the collapsed provenance disclosure
    expect(screen.getByText(/Citation déclarée par le modèle/).closest("details")).not.toBeNull();
  });

  it("shows a provenance warning instead of a quote when derivation failed", async () => {
    mocked.getFinding.mockResolvedValue(
      makeFindingDetail({
        source_quote: null,
        source_quote_error: "offsets de citation invalides : [10:9999) hors des bornes.",
      }),
    );
    renderPage();
    expect(await screen.findByText(/Provenance non affichable/)).toBeInTheDocument();
    expect(screen.queryByText(/Extrait source \(autoritatif\)/)).toBeNull();
    // no highlight when provenance is corrupt
    expect(document.querySelector("mark")).toBeNull();
  });
});

describe("review action rules", () => {
  it("disables approve/edit for abstained findings, keeps override", async () => {
    mocked.getFinding.mockResolvedValue(
      makeFindingDetail({
        id: "fid-2",
        requirement_id: "A.4.5",
        status: "ABSTAINED",
        verdict: null,
        abstain_reason: "model_abstained",
        source_quote: null,
        matched_chunk_id: null,
      }),
    );
    renderPage();
    // select the abstained finding in the list
    await userEvent.click(await screen.findByRole("button", { name: /A\.4\.5/ }));
    const actions = await screen.findByRole("group", { name: "Actions de revue" });
    expect(within(actions).getByRole("button", { name: "Approuver" })).toBeDisabled();
    expect(within(actions).getByRole("button", { name: "Modifier" })).toBeDisabled();
    expect(within(actions).getByRole("button", { name: "Remplacer" })).toBeEnabled();
    expect(screen.getByText(/le verdict vous appartient/)).toBeInTheDocument();
  });

  it("requires a rationale before submitting an edit", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Modifier" }));
    const submit = screen.getByRole("button", { name: "Enregistrer la décision" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Justification/), "Nuance apportée.");
    expect(submit).toBeEnabled();
  });

  it("submits an override with verdict and rationale", async () => {
    mocked.reviewFinding.mockResolvedValue(
      makeFindingDetail({ review_status: "CONFIRMED", review_action: "override" }),
    );
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Remplacer" }));
    await userEvent.selectOptions(screen.getByLabelText(/Votre verdict/), "partial");
    await userEvent.type(screen.getByLabelText(/Justification/), "Couverture partielle.");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer la décision" }));
    expect(mocked.reviewFinding).toHaveBeenCalledWith("org-1", "aid-1", "fid-1", {
      action: "override",
      human_verdict: "partial",
      human_rationale: "Couverture partielle.",
      review_note: undefined,
      reviewer_label: undefined,
    });
  });
});

describe("confirmed state and history", () => {
  it("renders the human decision beside the untouched AI draft, with history", async () => {
    mocked.getFinding.mockResolvedValue(
      makeFindingDetail({
        review_status: "CONFIRMED",
        review_action: "override",
        human_verdict: "non_compliant",
        human_rationale: "Relecture stricte.",
        reviewed_at: "2026-07-06T12:00:00Z",
        review_count: 2,
        reviews: [
          {
            sequence: 1,
            action: "approve",
            human_verdict: "compliant",
            human_rationale: null,
            review_note: null,
            reviewer_label: "Yassine",
            created_at: "2026-07-06T11:00:00Z",
          },
          {
            sequence: 2,
            action: "override",
            human_verdict: "non_compliant",
            human_rationale: "Relecture stricte.",
            review_note: null,
            reviewer_label: null,
            created_at: "2026-07-06T12:00:00Z",
          },
        ],
      }),
    );
    renderPage();
    // appears in both the confirmed card and the history entry
    expect(await screen.findAllByText("Relecture stricte.")).toHaveLength(2);
    // AI draft still visible with its own verdict
    expect(screen.getByText(/Brouillon IA — citation localisée/)).toBeInTheDocument();
    // history lists both decisions with unverified attribution
    expect(screen.getByText(/Historique des décisions \(2\)/)).toBeInTheDocument();
    expect(screen.getByText(/par Yassine \(non vérifié\)/)).toBeInTheDocument();
  });
});

describe("abstention variants in the findings list", () => {
  it("flags evidentiary abstentions amber and infra failures neutral", async () => {
    mocked.getAssessment.mockResolvedValue({
      ...makeAssessment({ status: "COMPLETED" }),
      findings: [
        makeFindingSummary({
          id: "fid-2",
          requirement_id: "A.4.5",
          status: "ABSTAINED",
          verdict: null,
          abstain_reason: "model_abstained",
        }),
        makeFindingSummary({
          id: "fid-3",
          requirement_id: "A.7.2",
          status: "ABSTAINED",
          verdict: null,
          abstain_reason: "llm_error",
        }),
      ],
    });
    mocked.getFinding.mockResolvedValue(
      makeFindingDetail({ id: "fid-2", status: "ABSTAINED", verdict: null }),
    );
    renderPage();
    expect(await screen.findByText("Nécessite votre jugement")).toBeInTheDocument();
    expect(screen.getByText(/Échec technique — relancez l'évaluation/)).toBeInTheDocument();
  });
});
