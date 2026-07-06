import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  isInfraAbstain,
  type AnswerSegment,
  type ChatCitation,
  type ChatMessage,
  type RetrievedItem,
} from "../api";
import HighlightedText from "../components/HighlightedText";

export default function ChatPage() {
  const { orgId, conversationId } = useParams<{
    orgId: string;
    conversationId?: string;
  }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [askError, setAskError] = useState<string | null>(null);

  const conversations = useQuery({
    queryKey: ["conversations", orgId],
    queryFn: () => api.listConversations(orgId!),
  });

  const messages = useQuery({
    queryKey: ["messages", orgId, conversationId],
    queryFn: () => api.listMessages(orgId!, conversationId!),
    enabled: !!conversationId,
  });

  const ask = useMutation({
    mutationFn: (q: string) => api.postMessage(orgId!, q, conversationId),
    onSuccess: (message) => {
      setQuestion("");
      setAskError(null);
      queryClient.invalidateQueries({ queryKey: ["conversations", orgId] });
      queryClient.invalidateQueries({
        queryKey: ["messages", orgId, message.conversation_id],
      });
      if (!conversationId) {
        navigate(`/organizations/${orgId}/chat/${message.conversation_id}`);
      }
    },
    onError: (err) => setAskError((err as Error).message),
  });

  const submit = () => {
    const q = question.trim();
    if (q && !ask.isPending) ask.mutate(q);
  };

  return (
    <div className="space-y-6">
      <Link to={`/organizations/${orgId}`} className="text-sm text-indigo-600 hover:underline">
        ← Organisation
      </Link>

      <div>
        <h1 className="text-2xl font-semibold">Copilote — questions sur vos politiques</h1>
        <p className="mt-1 text-sm text-slate-500">
          Les réponses sont des brouillons IA : chaque citation est localisée dans vos documents
          par du code déterministe — sa pertinence reste à confirmer par vous.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <aside className="space-y-2">
          <Link
            to={`/organizations/${orgId}/chat`}
            className={`block rounded-lg border px-3 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 ${
              !conversationId
                ? "border-indigo-400 bg-indigo-50 text-indigo-700"
                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            + Nouvelle conversation
          </Link>
          <ul className="max-h-[60vh] space-y-1 overflow-y-auto" aria-label="Conversations">
            {conversations.data?.map((c) => (
              <li key={c.id}>
                <Link
                  to={`/organizations/${orgId}/chat/${c.id}`}
                  aria-current={c.id === conversationId}
                  className={`block truncate rounded-lg border px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 ${
                    c.id === conversationId
                      ? "border-indigo-400 bg-indigo-50"
                      : "border-slate-200 bg-white hover:bg-slate-50"
                  }`}
                >
                  {c.title}
                </Link>
              </li>
            ))}
          </ul>
        </aside>

        <div className="space-y-4">
          <div className="space-y-4">
            {conversationId &&
              messages.data?.map((m) => <MessageThread key={m.id} message={m} />)}
            {!conversationId && (
              <p className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
                Posez une question sur les politiques de l'organisation — par exemple :
                « Gérons-nous les risques liés aux fournisseurs d'IA ? »
              </p>
            )}
            {ask.isPending && (
              <p aria-live="polite" className="text-sm text-indigo-600">
                Recherche des preuves et rédaction…
              </p>
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            className="space-y-2"
          >
            <label className="block">
              <span className="sr-only">Votre question</span>
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submit();
                  }
                }}
                rows={3}
                disabled={ask.isPending}
                placeholder="Votre question…"
                className="block w-full rounded-xl border border-slate-300 px-4 py-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 disabled:bg-slate-50"
              />
            </label>
            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={ask.isPending || !question.trim()}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500"
              >
                Envoyer
              </button>
              {askError && <p className="text-sm text-red-600">{askError}</p>}
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

function MessageThread({ message: m }: { message: ChatMessage }) {
  return (
    <div className="space-y-3">
      <div className="ml-auto max-w-[85%] rounded-xl bg-indigo-600 px-4 py-3 text-sm text-white">
        {m.question}
      </div>
      {m.status === "ANSWERED" ? (
        <AnswerCard message={m} />
      ) : isInfraAbstain(m.abstain_reason) ? (
        <InfraNotice message={m} />
      ) : (
        <PotentialGapCard message={m} />
      )}
    </div>
  );
}

// footnote number per citation id, in answer_citations (claim-reference) order
function footnoteIndex(citations: ChatCitation[]): Map<string, number> {
  const map = new Map<string, number>();
  citations.forEach((c, i) => map.set(c.id, i + 1));
  return map;
}

function AnswerCard({ message: m }: { message: ChatMessage }) {
  const [openCitation, setOpenCitation] = useState<string | null>(null);
  const footnotes = useMemo(() => footnoteIndex(m.answer_citations), [m.answer_citations]);

  return (
    <div className="max-w-[95%] space-y-3 rounded-xl border border-slate-200 bg-white p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Brouillon IA — citations localisées, pertinence à confirmer
      </p>

      <div className="space-y-2 text-sm leading-relaxed text-slate-800">
        {m.answer_segments.map((seg, i) => (
          <SegmentText
            key={i}
            segment={seg}
            footnotes={footnotes}
            onCitationClick={(id) => setOpenCitation(openCitation === id ? null : id)}
          />
        ))}
        {m.answer_caveat && (
          <p className="border-l-2 border-slate-300 pl-3 text-xs italic text-slate-500">
            {m.answer_caveat}
          </p>
        )}
      </div>

      {m.answer_citations.length > 0 && (
        <ol className="space-y-2 border-t border-slate-100 pt-3" aria-label="Sources">
          {m.answer_citations.map((c) => (
            <Footnote
              key={c.id}
              citation={c}
              index={footnotes.get(c.id)!}
              open={openCitation === c.id}
              onToggle={() => setOpenCitation(openCitation === c.id ? null : c.id)}
              searched={m.searched}
            />
          ))}
        </ol>
      )}

      <ProvenanceDetails message={m} />
    </div>
  );
}

function SegmentText({
  segment,
  footnotes,
  onCitationClick,
}: {
  segment: AnswerSegment;
  footnotes: Map<string, number>;
  onCitationClick: (id: string) => void;
}) {
  return (
    <p>
      {segment.text}
      {segment.citation_ids.map((cid) =>
        footnotes.has(cid) ? (
          <button
            key={cid}
            onClick={() => onCitationClick(cid)}
            aria-label={`Voir la source ${footnotes.get(cid)}`}
            className="ml-0.5 rounded align-super text-xs font-semibold text-indigo-600 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
          >
            [{footnotes.get(cid)}]
          </button>
        ) : null,
      )}
    </p>
  );
}

function Footnote({
  citation: c,
  index,
  open,
  onToggle,
  searched,
}: {
  citation: ChatCitation;
  index: number;
  open: boolean;
  onToggle: () => void;
  searched: RetrievedItem[];
}) {
  const source = c.chunk_id ? searched.find((s) => s.result_id === c.chunk_id) : undefined;
  return (
    <li className="text-xs text-slate-600">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="rounded text-left hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
      >
        <span className="font-semibold text-indigo-600">[{index}]</span>{" "}
        {c.type === "policy" ? (
          c.source_quote ? (
            <>
              « {c.source_quote} » —{" "}
              <span className="text-slate-500">
                {c.filename}
                {c.page_number ? `, p.${c.page_number}` : ""}
              </span>
            </>
          ) : (
            <span className="font-medium text-amber-700">
              Provenance non affichable : {c.source_quote_error ?? "extrait source indisponible."}
            </span>
          )
        ) : (
          <>
            <span className="font-medium">Exigence ISO {c.requirement_id}</span> —{" "}
            {c.requirement_fr}
          </>
        )}
      </button>
      {open && c.type === "policy" && source && (
        <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50/50 p-3">
          <p className="font-medium text-slate-500">
            {c.filename}
            {c.page_number ? `, p.${c.page_number}` : ""} — passage en contexte
          </p>
          <p className="mt-1 whitespace-pre-wrap leading-relaxed text-slate-800">
            <HighlightedText
              text={source.text}
              start={
                c.match_start != null && !c.source_quote_error
                  ? c.match_start - (source.char_start ?? 0)
                  : null
              }
              end={
                c.match_end != null && !c.source_quote_error
                  ? c.match_end - (source.char_start ?? 0)
                  : null
              }
            />
          </p>
        </div>
      )}
      {open && c.type === "policy" && !source && (
        <p className="mt-1 text-amber-700">
          Passage source non retrouvé dans la recherche persistée.
        </p>
      )}
    </li>
  );
}

function PotentialGapCard({ message: m }: { message: ChatMessage }) {
  return (
    <div className="max-w-[95%] space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">
        ⚠ Écart potentiel — aucune citation vérifiable
      </p>
      <p className="whitespace-pre-wrap text-sm text-slate-800">{m.answer}</p>
      {m.suggested_clause && (
        <p className="text-sm">
          <span className="rounded-full bg-amber-200 px-2 py-0.5 text-xs font-medium text-amber-900">
            Clause à examiner : {m.suggested_clause.requirement_id}
          </span>
          <span className="ml-2 text-xs text-slate-600">
            {m.suggested_clause.requirement_fr}
          </span>
        </p>
      )}
      {(m.retrieval_notes?.length ?? 0) > 0 && (
        <details>
          <summary className="cursor-pointer text-xs font-medium text-slate-600">
            Passages examinés ({m.retrieval_notes!.length}) — commentaires du modèle, non
            vérifiés
          </summary>
          <ul className="mt-2 space-y-2">
            {m.retrieval_notes!.map((note) => {
              const source = m.searched.find((s) => s.result_id === note.result_id);
              return (
                <li key={note.result_id} className="rounded-lg border border-amber-200 p-2 text-xs">
                  {source && (
                    <p className="text-slate-700">
                      {source.filename}
                      {source.page_number ? `, p.${source.page_number}` : ""} : «{" "}
                      {source.text.length > 220
                        ? source.text.slice(0, 220) + "…"
                        : source.text}{" "}
                      »
                    </p>
                  )}
                  <p className="mt-1 text-slate-500">
                    Commentaire du modèle — non vérifié : {note.reason}
                  </p>
                </li>
              );
            })}
          </ul>
        </details>
      )}
      <ProvenanceDetails message={m} />
    </div>
  );
}

function InfraNotice({ message: m }: { message: ChatMessage }) {
  return (
    <div className="max-w-[95%] rounded-xl border border-slate-300 bg-slate-100 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        ⚙ Service indisponible
      </p>
      <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{m.answer}</p>
    </div>
  );
}

function ProvenanceDetails({ message: m }: { message: ChatMessage }) {
  const dropped = m.claims.filter((c) => !c.citations_verified);
  if (m.stripped_citations.length === 0 && dropped.length === 0) return null;
  return (
    <details className="text-xs text-slate-500">
      <summary className="cursor-pointer font-medium">
        Provenance — éléments écartés ({m.stripped_citations.length + dropped.length})
      </summary>
      <div className="mt-2 space-y-2">
        {dropped.map((claim, i) => (
          <p key={`claim-${i}`}>
            Affirmation écartée (citations non vérifiées) : « {claim.text} »
          </p>
        ))}
        {m.stripped_citations.map((s, i) => (
          <p key={`cit-${i}`}>
            Citation écartée{s.error ? ` — ${s.error}` : ""}
          </p>
        ))}
      </div>
    </details>
  );
}
