import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
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
  type Doc,
  type RetrievedItem,
} from "../api";
import HighlightedText from "../components/HighlightedText";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

const DOC_STATUS_LABELS: Record<Doc["status"], string> = {
  parsed: "Analysé",
  uploaded: "Téléversé",
  failed: "Échec",
};

const DOC_STATUS_CLASSES: Record<Doc["status"], string> = {
  parsed:
    "bg-emerald-100 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-300",
  uploaded: "bg-amber-100 text-amber-700 dark:bg-amber-400/10 dark:text-amber-300",
  failed: "bg-red-100 text-red-700 dark:bg-red-400/10 dark:text-red-300",
};

const SUGGESTIONS = [
  "Gérons-nous les risques liés aux fournisseurs d'IA ?",
  "Comment les incidents IA sont-ils signalés ?",
  "Quelles exigences de la norme couvrent la supervision humaine ?",
];

export default function ChatPage() {
  const { orgId, conversationId } = useParams<{
    orgId: string;
    conversationId?: string;
  }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  // M8 drill-down: ?finding=<id> anchors the next question on one finding
  const findingId = searchParams.get("finding");
  const [question, setQuestion] = useState("");
  const [askError, setAskError] = useState<string | null>(null);
  // «Norme seule» skips the policy retrieval arm server-side (kb_only)
  const [kbOnly, setKbOnly] = useState(false);
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
        className="rounded-2xl border bg-card shadow-sm focus-within:border-ring/60"
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
            rows={2}
            disabled={ask.isPending}
            placeholder="Votre question…"
            className="block max-h-48 w-full resize-none bg-transparent px-4 pt-3.5 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
          />
        </label>
        <div className="flex items-center gap-2 px-2.5 pb-2.5">
          <DocumentsPopover orgId={orgId!} />
          <ModeToggle kbOnly={kbOnly} onChange={setKbOnly} />
          <Button
            type="submit"
            size="icon"
            aria-label="Envoyer"
            disabled={ask.isPending || !question.trim()}
            className="ml-auto rounded-full"
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

  return (
    <div className="flex h-full min-h-0">
      {/* conversations rail (desktop) */}
      <aside className="hidden w-64 shrink-0 flex-col border-r lg:flex">
        <div className="p-3">
          <Button asChild variant="outline" className="w-full justify-start">
            <Link to={`/organizations/${orgId}/chat`}>+ Nouvelle conversation</Link>
          </Button>
        </div>
        <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-3" aria-label="Conversations">
          {conversations.data?.map((c) => (
            <li key={c.id}>
              <Link
                to={`/organizations/${orgId}/chat/${c.id}`}
                aria-current={c.id === conversationId}
                className={cn(
                  "block truncate rounded-lg px-3 py-2 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-ring",
                  c.id === conversationId
                    ? "bg-accent font-medium text-accent-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {c.title}
              </Link>
            </li>
          ))}
        </ul>
      </aside>

      {/* main column */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* mobile: conversations in a sheet */}
        <div className="flex items-center gap-2 border-b px-4 py-2 lg:hidden">
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="ghost" size="sm">
                <History className="size-4" aria-hidden="true" />
                Conversations
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-80">
              <SheetHeader>
                <SheetTitle>Conversations</SheetTitle>
              </SheetHeader>
              <div className="space-y-1 overflow-y-auto px-4 pb-4">
                <Link
                  to={`/organizations/${orgId}/chat`}
                  className="block rounded-lg border px-3 py-2 text-sm font-medium"
                >
                  + Nouvelle conversation
                </Link>
                {conversations.data?.map((c) => (
                  <Link
                    key={c.id}
                    to={`/organizations/${orgId}/chat/${c.id}`}
                    className="block truncate rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
                  >
                    {c.title}
                  </Link>
                ))}
              </div>
            </SheetContent>
          </Sheet>
        </div>

        {hasThread ? (
          <>
            <div ref={streamRef} className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
                <p className="text-center text-xs text-muted-foreground">
                  Les réponses sont des brouillons IA : chaque citation est localisée dans vos
                  documents par du code déterministe — sa pertinence reste à confirmer par vous.
                </p>
                {messages.data?.map((m) => (
                  <MessageThread key={m.id} message={m} />
                ))}
              </div>
            </div>
            <div className="shrink-0 border-t bg-background/80 backdrop-blur">
              <div className="mx-auto w-full max-w-3xl px-4 py-3">{composer}</div>
            </div>
          </>
        ) : (
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-4">
            <div className="w-full max-w-2xl space-y-6 py-10">
              <div className="space-y-2 text-center">
                <h1 className="text-2xl font-semibold tracking-tight">
                  Copilote — questions sur vos politiques
                </h1>
                <p className="mx-auto max-w-lg text-sm text-muted-foreground">
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
                    className="rounded-full border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** «Documents + norme» / «Norme seule» — the requested mode; the badge on each
    answer still reflects what actually survived verification. */
function ModeToggle({
  kbOnly,
  onChange,
}: {
  kbOnly: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Mode de réponse"
      className="flex rounded-full border p-0.5 text-xs"
    >
      <button
        type="button"
        aria-pressed={!kbOnly}
        onClick={() => onChange(false)}
        className={cn(
          "flex items-center gap-1 rounded-full px-2.5 py-1 transition-colors focus-visible:outline-2 focus-visible:outline-ring",
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
          "flex items-center gap-1 rounded-full px-2.5 py-1 transition-colors focus-visible:outline-2 focus-visible:outline-ring",
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
          className="rounded-full"
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
              <span
                className={cn(
                  "shrink-0 rounded-full px-1.5 py-0.5 font-medium",
                  DOC_STATUS_CLASSES[doc.status],
                )}
              >
                {DOC_STATUS_LABELS[doc.status]}
              </span>
            </li>
          ))}
        </ul>
        <p className="border-t pt-2 text-xs text-muted-foreground">
          Gestion complète (suppression, indexation) :{" "}
          <Link to={`/organizations/${orgId}/evaluations`} className="text-primary hover:underline">
            Évaluations & documents
          </Link>
        </p>
      </PopoverContent>
    </Popover>
  );
}

function MessageThread({ message: m }: { message: ChatMessage }) {
  return (
    <div className="space-y-3">
      {m.finding_context && (
        <div className="ml-auto w-fit max-w-[85%] rounded-full border border-primary/25 bg-accent px-3 py-1 text-xs text-accent-foreground">
          Constat {m.finding_context.requirement_id}
          {m.finding_context.human_verdict && <> — {m.finding_context.human_verdict}</>} (contexte
          transmis au copilote, non citable)
        </div>
      )}
      <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
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

const SCOPE_LABELS: Record<string, string> = {
  policy: "Documents",
  kb_only: "Norme seule",
  mixed: "Documents + norme",
};

function AnswerCard({ message: m }: { message: ChatMessage }) {
  const [openCitation, setOpenCitation] = useState<string | null>(null);
  const footnotes = useMemo(() => footnoteIndex(m.answer_citations), [m.answer_citations]);

  return (
    <div className="max-w-[95%] space-y-3 rounded-2xl rounded-bl-sm border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Brouillon IA — citations localisées, pertinence à confirmer
        </p>
        {m.evidence_scope && SCOPE_LABELS[m.evidence_scope] && (
          <span className="ml-auto rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
            {SCOPE_LABELS[m.evidence_scope]}
          </span>
        )}
      </div>

      <div className="space-y-2 text-sm leading-relaxed">
        {m.answer_segments.map((seg, i) => (
          <SegmentText
            key={i}
            segment={seg}
            footnotes={footnotes}
            onCitationClick={(id) => setOpenCitation(openCitation === id ? null : id)}
          />
        ))}
        {m.answer_caveat && (
          <p className="border-l-2 border-border pl-3 text-xs italic text-muted-foreground">
            {m.answer_caveat}
          </p>
        )}
      </div>

      {m.answer_citations.length > 0 && (
        <ol className="space-y-2 border-t pt-3" aria-label="Sources">
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
                {c.page_number ? `, p.${c.page_number}` : ""}
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
        <div className="mt-2 rounded-lg border border-emerald-600/20 bg-emerald-50/60 p-3 dark:border-emerald-400/20 dark:bg-emerald-400/5">
          <p className="font-medium text-muted-foreground">
            {c.filename}
            {c.page_number ? `, p.${c.page_number}` : ""} — passage en contexte
          </p>
          <p className="mt-1 whitespace-pre-wrap leading-relaxed text-foreground">
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

function PotentialGapCard({ message: m }: { message: ChatMessage }) {
  return (
    <div className="max-w-[95%] space-y-3 rounded-2xl rounded-bl-sm border border-amber-600/40 bg-amber-50 p-4 dark:border-amber-400/30 dark:bg-amber-400/10">
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-200">
        <TriangleAlert className="size-3.5 shrink-0" aria-hidden="true" />
        Écart potentiel — aucune citation vérifiable
      </p>
      <p className="whitespace-pre-wrap text-sm text-foreground">{m.answer}</p>
      {m.suggested_clause && (
        <p className="text-sm">
          <span className="rounded-full bg-amber-200 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-400/20 dark:text-amber-200">
            Clause à examiner : {m.suggested_clause.requirement_id}
          </span>
          <span className="ml-2 text-xs text-muted-foreground">
            {m.suggested_clause.requirement_fr}
          </span>
        </p>
      )}
      {(m.retrieval_notes?.length ?? 0) > 0 && (
        <details>
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
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
                      {source.text.length > 220
                        ? source.text.slice(0, 220) + "…"
                        : source.text}{" "}
                      »
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
    <div className="max-w-[95%] rounded-2xl rounded-bl-sm border bg-muted p-4">
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <Settings2 className="size-3.5 shrink-0" aria-hidden="true" />
        Service indisponible
      </p>
      <p className="mt-2 whitespace-pre-wrap text-sm">{m.answer}</p>
    </div>
  );
}

function ProvenanceDetails({ message: m }: { message: ChatMessage }) {
  const dropped = m.claims.filter((c) => !c.citations_verified);
  if (m.stripped_citations.length === 0 && dropped.length === 0) return null;
  return (
    <details className="text-xs text-muted-foreground">
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
          <p key={`cit-${i}`}>Citation écartée{s.error ? ` — ${s.error}` : ""}</p>
        ))}
      </div>
    </details>
  );
}
