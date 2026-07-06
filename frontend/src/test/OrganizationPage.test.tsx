import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import OrganizationPage from "../pages/OrganizationPage";
import { makeAssessment, renderWithProviders } from "./helpers";

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listDocuments: vi.fn(),
      listAssessments: vi.fn(),
      createAssessment: vi.fn(),
      resumeAssessment: vi.fn(),
      abandonAssessment: vi.fn(),
      indexOrganization: vi.fn(),
      uploadDocument: vi.fn(),
      deleteDocument: vi.fn(),
    },
  };
});

const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const PARSED_DOC = {
  id: "doc-1",
  organization_id: "org-1",
  filename: "politique_ia.txt",
  content_type: "text/plain",
  status: "parsed" as const,
  error: null,
  page_count: 1,
  created_at: "2026-07-06T09:00:00Z",
};

function renderPage() {
  return renderWithProviders(<OrganizationPage />, {
    route: "/organizations/org-1",
    path: "/organizations/:orgId",
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listDocuments.mockResolvedValue([PARSED_DOC]);
  mocked.listAssessments.mockResolvedValue([]);
});

describe("assessment launch", () => {
  it("launches with the frozen dev-split default and shows the running card", async () => {
    mocked.createAssessment.mockResolvedValue(makeAssessment());
    renderPage();
    const btn = await screen.findByRole("button", { name: "Lancer l'évaluation" });
    mocked.listAssessments.mockResolvedValue([makeAssessment()]);
    await userEvent.click(btn);
    expect(mocked.createAssessment).toHaveBeenCalledWith("org-1", {});
    expect(await screen.findByText("En cours")).toBeInTheDocument();
    // live per-node progress, French labels
    expect(screen.getByText(/Exigence 2\/2 — A\.4\.5 · nœud : jugement/)).toBeInTheDocument();
  });

  it("surfaces the backend's French error on launch conflict", async () => {
    mocked.createAssessment.mockRejectedValue(
      new Error("Une évaluation est déjà en cours pour cette organisation."),
    );
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Lancer l'évaluation" }));
    expect(
      await screen.findByText("Une évaluation est déjà en cours pour cette organisation."),
    ).toBeInTheDocument();
  });

  it("disables launch when no parsed document exists", async () => {
    mocked.listDocuments.mockResolvedValue([]);
    renderPage();
    const btn = await screen.findByRole("button", { name: "Lancer l'évaluation" });
    await waitFor(() => expect(btn).toBeDisabled());
    expect(
      screen.getByText(/Téléversez au moins un document analysé/),
    ).toBeInTheDocument();
  });
});

describe("assessment cards", () => {
  it("shows tallies, review link and abandon confirmation on a running card", async () => {
    mocked.listAssessments.mockResolvedValue([makeAssessment()]);
    mocked.abandonAssessment.mockResolvedValue(
      makeAssessment({ status: "FAILED", cancel_requested: true }),
    );
    renderPage();
    expect(await screen.findByText("1 vérifiés")).toBeInTheDocument();
    expect(screen.getByText("0 confirmés")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ouvrir l'espace de revue/ })).toHaveAttribute(
      "href",
      "/organizations/org-1/assessments/aid-1",
    );
    // abandon requires explicit confirmation
    await userEvent.click(screen.getByRole("button", { name: "Abandonner" }));
    expect(mocked.abandonAssessment).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirmer" }));
    expect(mocked.abandonAssessment).toHaveBeenCalledWith("org-1", "aid-1");
  });

  it("shows pending-cancel state and hides run controls", async () => {
    mocked.listAssessments.mockResolvedValue([
      makeAssessment({ cancel_requested: true }),
    ]);
    renderPage();
    expect(await screen.findByText("Annulation en cours…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Abandonner" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reprendre" })).toBeNull();
  });

  it("marks legacy rows with an incomplete manifest", async () => {
    mocked.listAssessments.mockResolvedValue([
      makeAssessment({ manifest_complete: false, status: "RUNNING", progress: null }),
    ]);
    renderPage();
    expect(await screen.findByText(/manifeste incomplet/)).toBeInTheDocument();
  });
});

describe("polling", () => {
  it("polls the list every 2s while a run is live and stops once terminal", async () => {
    vi.useFakeTimers();
    try {
      mocked.listAssessments.mockResolvedValue([makeAssessment()]);
      renderPage();
      await vi.waitFor(() =>
        expect(mocked.listAssessments).toHaveBeenCalledTimes(1),
      );
      // next tick: run finished — one more poll happens, then polling stops
      mocked.listAssessments.mockResolvedValue([
        makeAssessment({ status: "COMPLETED", progress: null, findings_done: 2 }),
      ]);
      await vi.advanceTimersByTimeAsync(2100);
      await vi.waitFor(() =>
        expect(mocked.listAssessments).toHaveBeenCalledTimes(2),
      );
      await vi.advanceTimersByTimeAsync(6000);
      expect(mocked.listAssessments).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
