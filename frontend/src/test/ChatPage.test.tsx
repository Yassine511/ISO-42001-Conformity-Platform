import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ChatMessage } from "../api";
import ChatPage from "../pages/ChatPage";
import { renderWithProviders } from "./helpers";

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listConversations: vi.fn(),
      listMessages: vi.fn(),
      postMessage: vi.fn(),
      listDocuments: vi.fn(),
      uploadDocument: vi.fn(),
    },
  };
});

const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const SOURCE_QUOTE = "Les incidents sont signalés au comité IA sous 48 heures.";
const CHUNK_TEXT = `Contexte. ${SOURCE_QUOTE} Fin.`;

function makeAnswered(over: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "msg-1",
    conversation_id: "conv-1",
    finding_id: null,
    finding_context: null,
    question: "Gérons-nous les incidents IA ?",
    status: "ANSWERED",
    abstain_reason: null,
    answer: "Oui, la politique prévoit un signalement sous 48 heures.",
    evidence_scope: "policy",
    claims: [
      {
        text: "Oui, la politique prévoit un signalement sous 48 heures.",
        kind: "organization",
        citation_ids: ["c1"],
        citations_verified: true,
      },
      {
        text: "Affirmation écartée sans preuve.",
        kind: "organization",
        citation_ids: ["c9"],
        citations_verified: false,
      },
    ],
    answer_segments: [
      {
        text: "Oui, la politique prévoit un signalement sous 48 heures.",
        citation_ids: ["c1"],
      },
    ],
    answer_caveat: null,
    answer_citations: [
      {
        id: "c1",
        type: "policy",
        quote: "quote modèle — jamais affichée",
        source_quote: SOURCE_QUOTE,
        source_quote_error: null,
        chunk_id: "chunk-1",
        document_id: "doc-1",
        filename: "politique_ia.txt",
        page_number: 2,
        match_start: CHUNK_TEXT.indexOf(SOURCE_QUOTE),
        match_end: CHUNK_TEXT.indexOf(SOURCE_QUOTE) + SOURCE_QUOTE.length,
        match_method: "exact",
        match_score: 100,
      },
    ],
    citations: [],
    stripped_citations: [
      { citation: { id: "c9" }, error: "citation introuvable dans les extraits.", match: null },
    ],
    retrieval_notes: null,
    searched: [
      {
        result_id: "chunk-1",
        source_type: "policy",
        text: CHUNK_TEXT,
        rrf_score: 0.03,
        vector_rank: 1,
        bm25_rank: 1,
        document_id: "doc-1",
        filename: "politique_ia.txt",
        page_number: 2,
        char_start: 0,
        char_end: CHUNK_TEXT.length,
        requirement_id: null,
        domain: null,
      },
    ],
    suggested_clause: null,
    final_model: "fake-model",
    final_provider: "fake",
    created_at: "2026-07-06T10:00:00Z",
    ...over,
  };
}

function makeAbstained(over: Partial<ChatMessage> = {}): ChatMessage {
  return makeAnswered({
    id: "msg-2",
    status: "ABSTAINED",
    abstain_reason: "model_abstained",
    answer:
      "Aucune preuve vérifiable parmi les passages consultés. La clause A.8.3 est à examiner.",
    evidence_scope: null,
    claims: [],
    answer_segments: [],
    answer_citations: [],
    stripped_citations: [],
    retrieval_notes: [
      { result_id: "chunk-1", reason: "traite du signalement, pas des fournisseurs" },
    ],
    suggested_clause: {
      requirement_id: "A.8.3",
      requirement_fr: "Maîtriser les risques liés aux fournisseurs de systèmes d'IA.",
      domain: "Fournisseurs",
    },
    ...over,
  });
}

function renderChat(conversationId?: string) {
  return renderWithProviders(<ChatPage />, {
    route: `/organizations/org-1/chat${conversationId ? `/${conversationId}` : ""}`,
    path: "/organizations/:orgId/chat/:conversationId?",
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listConversations.mockResolvedValue([
    {
      id: "conv-1",
      organization_id: "org-1",
      title: "Gérons-nous les incidents IA ?",
      created_at: "2026-07-06T10:00:00Z",
      updated_at: "2026-07-06T10:00:00Z",
    },
  ]);
  mocked.listMessages.mockResolvedValue([makeAnswered()]);
  mocked.listDocuments.mockResolvedValue([]);
});

describe("answered rendering", () => {
  it("renders segments with footnotes and the authoritative source quote only", async () => {
    renderChat("conv-1");
    expect(
      await screen.findByText(/Brouillon IA — citations localisées, pertinence à confirmer/),
    ).toBeInTheDocument();
    // footnote marker on the segment
    expect(screen.getByRole("button", { name: "Voir la source 1" })).toBeInTheDocument();
    // footnote text uses source_quote, never the model quote
    expect(screen.getByText(new RegExp(SOURCE_QUOTE.slice(0, 30)))).toBeInTheDocument();
    expect(screen.queryByText(/quote modèle/)).toBeNull();
  });

  it("opens the in-context source panel with the slice highlighted", async () => {
    renderChat("conv-1");
    await userEvent.click(
      await screen.findByRole("button", { name: "Voir la source 1" }),
    );
    expect(screen.getByText(/passage en contexte/)).toBeInTheDocument();
    const mark = screen.getByText(SOURCE_QUOTE, { selector: "mark" });
    expect(mark).toBeInTheDocument();
  });

  it("renders a provenance warning instead of a quote when derivation failed", async () => {
    mocked.listMessages.mockResolvedValue([
      makeAnswered({
        answer_citations: [
          {
            id: "c1",
            type: "policy",
            source_quote: null,
            source_quote_error: "incohérence de provenance.",
            chunk_id: "chunk-1",
            filename: "politique_ia.txt",
            page_number: 2,
          },
        ],
      }),
    ]);
    renderChat("conv-1");
    expect(await screen.findByText(/Provenance non affichable/)).toBeInTheDocument();
  });

  it("renders the kb_only caveat as a distinct line and lists dropped elements", async () => {
    mocked.listMessages.mockResolvedValue([
      makeAnswered({ answer_caveat: "Réponse fondée sur la norme uniquement." }),
    ]);
    renderChat("conv-1");
    expect(
      await screen.findByText("Réponse fondée sur la norme uniquement."),
    ).toBeInTheDocument();
    // dropped claim + stripped citation in the collapsed provenance
    expect(screen.getByText(/éléments écartés \(2\)/)).toBeInTheDocument();
  });
});

describe("abstention rendering", () => {
  it("renders the amber potential-gap card with suggested clause and unverified notes", async () => {
    mocked.listMessages.mockResolvedValue([makeAbstained()]);
    renderChat("conv-1");
    expect(await screen.findByText(/Écart potentiel/)).toBeInTheDocument();
    expect(screen.getByText("Clause à examiner : A.8.3")).toBeInTheDocument();
    expect(screen.getByText(/commentaires du modèle, non\s+vérifiés/)).toBeInTheDocument();
  });

  it("renders infrastructure abstentions as a neutral service notice", async () => {
    mocked.listMessages.mockResolvedValue([
      makeAbstained({
        abstain_reason: "llm_error",
        answer: "Le service de génération est momentanément indisponible.",
        retrieval_notes: null,
        suggested_clause: null,
      }),
    ]);
    renderChat("conv-1");
    expect(await screen.findByText(/Service indisponible/)).toBeInTheDocument();
    expect(screen.queryByText(/Écart potentiel/)).toBeNull();
  });
});

describe("composer", () => {
  it("posts a question and surfaces French errors", async () => {
    mocked.postMessage.mockRejectedValue(new Error("Index vectoriel indisponible : down"));
    renderChat("conv-1");
    const box = await screen.findByPlaceholderText("Votre question…");
    await userEvent.type(box, "Question test");
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(mocked.postMessage).toHaveBeenCalledWith(
      "org-1",
      "Question test",
      "conv-1",
      undefined,
      false,
    );
    expect(
      await screen.findByText("Index vectoriel indisponible : down"),
    ).toBeInTheDocument();
  });

  it("sends kb_only when «Norme seule» is selected and false by default", async () => {
    mocked.postMessage.mockResolvedValue(makeAnswered());
    renderChat("conv-1");
    const box = await screen.findByPlaceholderText("Votre question…");
    await userEvent.click(screen.getByRole("button", { name: /Norme seule/ }));
    await userEvent.type(box, "Que dit la norme ?");
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(mocked.postMessage).toHaveBeenCalledWith(
      "org-1",
      "Que dit la norme ?",
      "conv-1",
      undefined,
      true,
    );
    // switching back restores the default documents+standard mode
    await userEvent.click(screen.getByRole("button", { name: /Documents \+ norme/ }));
    await userEvent.type(box, "Et nos politiques ?");
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(mocked.postMessage).toHaveBeenLastCalledWith(
      "org-1",
      "Et nos politiques ?",
      "conv-1",
      undefined,
      false,
    );
  });
});

describe("finding drill-down (M8)", () => {
  const CONTEXT = {
    finding_id: "fid-1",
    assessment_id: "aid-1",
    requirement_id: "A.9.2",
    requirement_fr: "Encadrer l'utilisation responsable des systèmes d'IA.",
    domain: "A.9",
    ai_status: "VERIFIED" as const,
    ai_verdict: "partial" as const,
    abstain_reason: null,
    ai_rationale: "Couverture partielle.",
    review_status: "CONFIRMED" as const,
    review_action: "edit" as const,
    human_verdict: "partial" as const,
    human_rationale: "Confirmé.",
    review_count: 1,
    reviewed_at: "2026-07-12T10:00:00Z",
    evidence: {
      matched_chunk_id: "chunk-1",
      match_start: 0,
      match_end: 10,
      match_method: "exact" as const,
    },
  };

  it("shows a removable context chip from ?finding= and sends finding_id", async () => {
    mocked.postMessage.mockResolvedValue(makeAnswered());
    renderWithProviders(<ChatPage />, {
      route: "/organizations/org-1/chat/conv-1?finding=fid-12345678",
      path: "/organizations/:orgId/chat/:conversationId?",
    });
    expect(await screen.findByText(/Question ancrée sur le constat/)).toBeInTheDocument();
    const box = await screen.findByPlaceholderText("Votre question…");
    await userEvent.type(box, "Pourquoi ?");
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(mocked.postMessage).toHaveBeenCalledWith(
      "org-1",
      "Pourquoi ?",
      "conv-1",
      "fid-12345678",
      false,
    );
    // removable: the chip disappears and later questions are unanchored
    await userEvent.click(
      screen.getByRole("button", { name: "Retirer le contexte de constat" }),
    );
    expect(screen.queryByText(/Question ancrée sur le constat/)).toBeNull();
  });

  it("renders the persisted snapshot chip on messages that carried a context", async () => {
    mocked.listMessages.mockResolvedValue([
      makeAnswered({ finding_id: null, finding_context: CONTEXT }),
    ]);
    renderChat("conv-1");
    // snapshot-based: renders even though the live pointer is gone (deletion)
    expect(await screen.findByText(/Constat A\.9\.2/)).toBeInTheDocument();
    expect(screen.getByText(/non citable/)).toBeInTheDocument();
  });
});
