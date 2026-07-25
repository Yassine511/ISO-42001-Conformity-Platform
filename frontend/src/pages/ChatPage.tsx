import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUp,
  BookOpenText,
  FileText,
  History,
  Layers,
  Plus,
  Settings2,
  TriangleAlert,
  X,
} from "lucide-react";
import {
  api,
  isInfraAbstain,
  type AnswerSegment,
  type ChatCitation,
  type ChatMessage,
  type RetrievedItem,
} from "../api";
import { docStatusDisplay, evidenceScopeLabel, verdictDisplay } from "@/lib/labels";
import HighlightedText from "../components/HighlightedText";
import { StatusLabel } from "@/components/status-label";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

const SUGGESTIONS = [
  "Gérons-nous les risques liés aux fournisseurs d'IA ?",
  "Comment les incidents IA sont-ils signalés ?",
  "Quelles exigences de la norme couvrent la supervision humaine ?",
];

/** Copilote — a source-conscious AI workspace (spec §8.5): only the global
    sidebar remains; history opens in a drawer; each answer is a structured
    AI draft with numbered located citations and explicit limitations. */
export default function ChatPage() {
  const { orgId, conversationId } = useParams<{
    orgId: string;
    conversationId?: string;
  }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  // drill-down: ?finding=<id> anchors the next question on one finding
  const findingId = searchParams.get("finding");
  const [question, setQuestion] = useState("");
  const [askError, setAskError] = useState<string | null>(null);
  // «Norme seule» skips the policy retrieval arm server-side (kb_only)
  const [kbOnly, setKbOnly] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const streamRef = useRef<HTMLDivElement>(null);

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
    mutationFn: (q: string) =>
      api.postMessage(orgId!, q, conversationId, findingId ?? undefined, kbOnly),
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

  useEffect(() => {
    const el = streamRef.current;
    if (el && typeof el.scrollTo === "function") el.scrollTo({ top: el.scrollHeight });
  }, [messages.data, ask.isPending]);

  const hasThread = !!conversationId;
  const activeConversation = conversations.data?.find((c) => c.id === conversationId);
  const lastMessage = messages.data?.[messages.data.length - 1];

  const composer = (
    <div className="space-y-2">
      {findingId && (
        <div className="flex items-center gap-2 rounded-lg border border-primary/25 bg-accent px-3 py-2 text-sm text-accent-foreground">
          <span>
            Question ancrée sur le constat{" "}
            <span className="font-mono">{findingId.slice(0, 8)}</span> — le copilote reçoit son
            contexte (non citable).
          </span>
          <button
            type="button"
            aria-label="Retirer le contexte de constat"
            onClick={() => setSearchParams({}, { replace: true })}
            className="ml-auto rounded-full p-1 hover:bg-primary/10 focus-visible:outline-2 focus-visible:outline-ring"
          >
            <X className="size-3.5" aria-hidden="true" />
          </button>
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="rounded-xl border bg-card p-1.5 transition-colors focus-within:border-ring/60"
      >
        <label className="block">
          <span className="px-3 pt-2 text-xs font-medium text-muted-foreground">
            Votre question
          </span>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={2}
            disabled={ask.isPending}
            placeholder="Votre question…"
            className="block max-h-48 w-full resize-none bg-transparent px-3 pt-1.5 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
          />
        </label>
        <div className="flex items-center gap-2 px-1.5 pb-1.5">
          <DocumentsPopover orgId={orgId!} />
          <ModeToggle kbOnly={kbOnly} onChange={setKbOnly} />
          <Button
            type="submit"
            size="icon"
            aria-label="Envoyer"
            disabled={ask.isPending || !question.trim()}
            className="ml-auto size-10 rounded-full"
          >
            <ArrowUp className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </form>
      {askError && <p className="text-sm text-destructive">{askError}</p>}
      {ask.isPending && (
        <p aria-live="polite" className="text-sm text-primary">
          Recherche des preuves et rédaction…
        </p>
      )}
    </div>
  );

  const historyList = (
    <div className="space-y-1">
      <Link
        to={`/organizations/${orgId}/chat`}
        onClick={() => setHistoryOpen(false)}
        className="block rounded-lg border px-3 py-2.5 text-sm font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
      >
        + Nouvelle conversation
      </Link>
      {conversations.data?.map((c) => (
        <Link
          key={c.id}
          to={`/organizations/${orgId}/chat/${c.id}`}
          aria-current={c.id === conversationId}
          onClick={() => setHistoryOpen(false)}
          className={cn(
            "block rounded-lg px-3 py-2.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-ring",
            c.id === conversationId
              ? "bg-accent font-medium text-accent-foreground"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          {c.title}
        </Link>
      ))}
      {conversations.data?.length === 0 && (
        <p className="px-3 py-2 text-sm text-muted-foreground">Aucune conversation.</p>
      )}
    </div>
  );

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      {/* utility row: history drawer + full conversation title */}
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
          <SheetTrigger asChild>
            <Button variant="outline" size="sm" className="min-h-10 shrink-0">
              <History className="size-4" aria-hidden="true" />
              Historique
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-80 overflow-y-auto">
            <SheetHeader>
              <SheetTitle>Conversations</SheetTitle>
            </SheetHeader>
            <div className="px-4 pb-4">{historyList}</div>
          </SheetContent>
        </Sheet>
        <p className="min-w-0 text-sm font-medium break-words" title={activeConversation?.title}>
          {activeConversation?.title ?? "Nouvelle conversation"}
        </p>
      </div>

      {/* screen-reader announcement of newly arrived answers */}
      <p aria-live="polite" className="sr-only">
        {lastMessage
          ? lastMessage.status === "ANSWERED"
            ? "Nouvelle réponse du copilote disponible."
            : "Le copilote n'a pas pu produire de réponse citée."
          : ""}
      </p>

      {hasThread ? (
        <>
          <div ref={streamRef} className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
              <p className="text-center text-xs text-muted-foreground">
                Les réponses sont des brouillons IA : chaque citation est localisée dans vos
                documents par du code déterministe — sa pertinence reste à confirmer par vous.
              </p>
              {messages.data?.map((m) => (
                <MessageThread key={m.id} message={m} onFollowUp={setQuestion} />
              ))}
            </div>
          </div>
          <div className="shrink-0 border-t bg-background">
            <div className="mx-auto w-full max-w-3xl px-4 py-3">{composer}</div>
          </div>
        </>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-4">
          <div className="w-full max-w-2xl space-y-8 py-10">
            <div className="space-y-3 text-center">
              <h1 className="text-3xl font-semibold tracking-tight">
                Copilote — questions sur vos politiques
              </h1>
              <p className="mx-auto max-w-lg text-sm leading-relaxed text-muted-foreground">
                Les réponses sont des brouillons IA : chaque citation est localisée dans vos
                documents par du code déterministe — sa pertinence reste à confirmer par vous.
              </p>
            </div>
            {composer}
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setQuestion(s)}
                  className="min-h-10 rounded-full border px-4 text-xs text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** «Documents + norme» / «Norme seule» — the requested mode; the badge on each
    answer still reflects what actually survived verification. */
function ModeToggle({ kbOnly, onChange }: { kbOnly: boolean; onChange: (v: boolean) => void }) {
  return (
    <div role="group" aria-label="Mode de réponse" className="flex rounded-md border p-0.5 text-xs">
      <button
        type="button"
        aria-pressed={!kbOnly}
        onClick={() => onChange(false)}
        className={cn(
          "flex min-h-9 items-center gap-1 rounded px-2.5 py-1 transition-colors focus-visible:outline-2 focus-visible:outline-ring",
          !kbOnly ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground",
        )}
      >
        <Layers className="size-3" aria-hidden="true" />
        Documents + norme
      </button>
      <button
        type="button"
        aria-pressed={kbOnly}
        onClick={() => onChange(true)}
        className={cn(
          "flex min-h-9 items-center gap-1 rounded px-2.5 py-1 transition-colors focus-visible:outline-2 focus-visible:outline-ring",
          kbOnly ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground",
        )}
      >
        <BookOpenText className="size-3" aria-hidden="true" />
        Norme seule
      </button>
    </div>
  );
}

/** "+" on the composer: upload documents and check parse status without
    leaving the copilot (same API as the évaluations page — both stay). */
function DocumentsPopover({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);

  const docs = useQuery({
    queryKey: ["documents", orgId],
    queryFn: () => api.listDocuments(orgId),
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(orgId, file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents", orgId] }),
  });

  const handleFiles = async (files: FileList | null) => {
    if (!files) return;
    setUploadErrors([]);
    for (const file of Array.from(files)) {
      try {
        await upload.mutateAsync(file);
      } catch (err) {
        setUploadErrors((prev) => [...prev, `${file.name} : ${(err as Error).message}`]);
      }
    }
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label="Ajouter des documents"
          className="size-10 rounded-full"
        >
          <Plus className="size-4" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-3">
        <div className="space-y-1">
          <p className="text-sm font-medium">Documents de politique</p>
          <p className="text-xs text-muted-foreground">
            PDF, DOCX, TXT ou Markdown — 20 Mo maximum par fichier.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => inputRef.current?.click()}
          disabled={upload.isPending}
        >
          <Plus className="size-4" aria-hidden="true" />
          {upload.isPending ? "Téléversement…" : "Téléverser des documents"}
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          aria-label="Téléverser des documents de politique"
          className="sr-only"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
        {uploadErrors.map((msg) => (
          <p key={msg} className="text-xs text-destructive">
            {msg}
          </p>
        ))}
        <ul className="max-h-56 space-y-1.5 overflow-y-auto">
          {docs.data?.length === 0 && (
            <li className="text-xs text-muted-foreground">Aucun document pour le moment.</li>
          )}
          {docs.data?.map((doc) => (
            <li key={doc.id} className="flex items-center gap-2 text-xs">
              <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">{doc.filename}</span>
              <StatusLabel display={docStatusDisplay(doc.status)} dot={false} className="shrink-0" />
            </li>
          ))}
        </ul>
        <p className="border-t pt-2 text-xs text-muted-foreground">
          Gestion complète (suppression, indexation) :{" "}
          <Link to={`/organizations/${orgId}/evaluations`} className="text-primary hover:underline">
            Preuves et évaluations
          </Link>
        </p>
      </PopoverContent>
    </Popover>
  );
}

function MessageThread({
  message: m,
  onFollowUp,
}: {
  message: ChatMessage;
  onFollowUp: (q: string) => void;
}) {
  return (
    <div className="space-y-3">
      {m.finding_context && (
        <div className="ml-auto w-fit max-w-[85%] rounded-full border border-primary/25 bg-accent px-3 py-1 text-xs text-accent-foreground">
          Constat {m.finding_context.requirement_id}
          {m.finding_context.human_verdict && (
            <> — {verdictDisplay(m.finding_context.human_verdict).label}</>
          )}{" "}
          (contexte transmis au copilote, non citable)
        </div>
      )}
      <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-ink px-4 py-2.5 text-sm text-ink-foreground">
        {m.question}
      </div>
      {m.status === "ANSWERED" ? (
        <AnswerCard message={m} />
      ) : isInfraAbstain(m.abstain_reason) ? (
        <InfraNotice message={m} />
      ) : (
        <PotentialGapCard message={m} onFollowUp={onFollowUp} />
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
    <div className="max-w-[95%] space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          aria-hidden="true"
          className="flex size-6 shrink-0 items-center justify-center rounded-[7px] bg-ink font-serif text-xs font-semibold text-ink-foreground"
        >
          C
        </span>
        <p className="text-sm font-semibold">Réponse IA</p>
        {m.evidence_scope && (
          <span className="ml-auto rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
            {evidenceScopeLabel(m.evidence_scope)}
          </span>
        )}
      </div>
      <p className="font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">
        Brouillon IA — citations localisées, pertinence à confirmer
      </p>

      <div className="space-y-2 text-sm leading-relaxed">
        {m.answer_segments.map((seg, i) => (
          <SegmentText
            key={i}
            segment={seg}
            footnotes={footnotes}
            onCitationClick={(id) => setOpenCitation(openCitation === id ? null : id)}
          />
        ))}
      </div>

      {m.answer_citations.length > 0 && (
        <div className="border-t pt-3">
          <p className="font-mono text-[10.5px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
            Sources citées
          </p>
          <ol className="mt-2 space-y-2" aria-label="Sources">
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
        </div>
      )}

      <div className="border-t pt-3">
        <p className="font-mono text-[10.5px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
          Limites de cette réponse
        </p>
        <div className="mt-1 space-y-1 text-xs text-muted-foreground">
          {m.answer_caveat && <p className="italic">{m.answer_caveat}</p>}
          <p>
            Chaque passage cité est localisé mot pour mot dans sa source ; sa pertinence pour
            votre question n'est pas vérifiée automatiquement.
          </p>
        </div>
      </div>

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
            className="ml-0.5 rounded align-super text-xs font-semibold text-primary hover:underline focus-visible:outline-2 focus-visible:outline-ring"
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
    <li className="text-xs text-muted-foreground">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="rounded text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
      >
        <span className="font-semibold text-primary">[{index}]</span>{" "}
        {c.type === "policy" ? (
          c.source_quote ? (
            <>
              « {c.source_quote} » —{" "}
              <span className="text-muted-foreground/80">
                {c.filename}
                {c.page_number ? `, p.${c.page_number}` : ""} · passage localisé
              </span>
            </>
          ) : (
            <span className="font-medium text-amber-700 dark:text-amber-300">
              Provenance non affichable : {c.source_quote_error ?? "extrait source indisponible."}
            </span>
          )
        ) : (
          <>
            <span className="font-medium text-foreground">Exigence ISO {c.requirement_id}</span> —{" "}
            {c.requirement_fr}
          </>
        )}
      </button>
      {open && c.type === "policy" && source && (
        <div className="mt-2 rounded-lg border border-success/25 bg-success/5 p-3">
          <p className="font-medium text-muted-foreground">
            {c.filename}
            {c.page_number ? `, p.${c.page_number}` : ""} — passage en contexte
          </p>
          <p className="mt-1 leading-relaxed whitespace-pre-wrap text-foreground">
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
        <p className="mt-1 text-amber-700 dark:text-amber-300">
          Passage source non retrouvé dans la recherche persistée.
        </p>
      )}
    </li>
  );
}

function PotentialGapCard({
  message: m,
  onFollowUp,
}: {
  message: ChatMessage;
  onFollowUp: (q: string) => void;
}) {
  return (
    <div className="max-w-[95%] space-y-3 rounded-xl border border-warning/40 border-l-[3px] border-l-warning bg-warning/[0.07] p-4">
      <p className="flex items-center gap-1.5 font-mono text-[11px] font-semibold tracking-wide text-warning-foreground uppercase dark:text-warning">
        <TriangleAlert className="size-3.5 shrink-0" aria-hidden="true" />
        Écart potentiel — aucune citation vérifiable
      </p>
      <p className="text-sm whitespace-pre-wrap text-foreground">{m.answer}</p>
      {m.suggested_clause && (
        <div className="space-y-1.5 text-sm">
          <p>
            <span className="rounded-full bg-warning/20 px-2 py-0.5 text-xs font-medium text-warning-foreground dark:text-warning">
              Clause à examiner : {m.suggested_clause.requirement_id}
            </span>
            <span className="ml-2 text-xs text-muted-foreground">
              {m.suggested_clause.requirement_fr}
            </span>
          </p>
          <button
            type="button"
            onClick={() =>
              onFollowUp(
                `Que demande l'exigence ${m.suggested_clause!.requirement_id} de la norme ?`,
              )
            }
            className="min-h-9 rounded-md border px-3 text-xs font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
          >
            Poser la question sur cette exigence
          </button>
        </div>
      )}
      {(m.retrieval_notes?.length ?? 0) > 0 && (
        <details>
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground select-none [&::-webkit-details-marker]:hidden">
            Passages examinés ({m.retrieval_notes!.length}) — commentaires du modèle, non
            vérifiés
          </summary>
          <ul className="mt-2 space-y-2">
            {m.retrieval_notes!.map((note) => {
              const source = m.searched.find((s) => s.result_id === note.result_id);
              return (
                <li
                  key={note.result_id}
                  className="rounded-lg border border-amber-600/25 p-2 text-xs dark:border-amber-400/25"
                >
                  {source && (
                    <p className="text-foreground">
                      {source.filename}
                      {source.page_number ? `, p.${source.page_number}` : ""} : «{" "}
                      {source.text.length > 220 ? source.text.slice(0, 220) + "…" : source.text} »
                    </p>
                  )}
                  <p className="mt-1 text-muted-foreground">
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
    <div className="max-w-[95%] rounded-lg border bg-muted p-4">
      <p className="flex items-center gap-1.5 font-mono text-[10.5px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
        <Settings2 className="size-3.5 shrink-0" aria-hidden="true" />
        Service indisponible
      </p>
      <p className="mt-2 text-sm whitespace-pre-wrap">{m.answer}</p>
    </div>
  );
}

function ProvenanceDetails({ message: m }: { message: ChatMessage }) {
  const dropped = m.claims.filter((c) => !c.citations_verified);
  if (m.stripped_citations.length === 0 && dropped.length === 0) return null;
  return (
    <details className="text-xs text-muted-foreground">
      <summary className="cursor-pointer font-medium select-none [&::-webkit-details-marker]:hidden">
        Détails techniques — éléments écartés ({m.stripped_citations.length + dropped.length})
      </summary>
      <div className="mt-2 space-y-2">
        {dropped.map((claim, i) => (
          <p key={`claim-${i}`}>
            Affirmation écartée (citations non vérifiées) : « {claim.text} »
          </p>
        ))}
        {m.stripped_citations.map((s, i) => (
          <p key={`cit-${i}`}>Citation écartée{s.error ? ` — ${s.error}` : ""}</p>
        ))}
      </div>
    </details>
  );
}
