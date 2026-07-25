import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ChevronLeft, ChevronRight, ListChecks, MessageSquareText } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  isInfraAbstain,
  type FindingDetail,
  type FindingSummary,
  type ReviewAction,
  type Verdict,
} from "../api";
import { reviewActionDisplay, verdictDisplay } from "@/lib/labels";
import AbstainReasonLabel from "../components/AbstainReasonLabel";
import HighlightedText from "../components/HighlightedText";
import { ReviewStatusBadge } from "../components/StatusBadge";
import VerdictBadge from "../components/VerdictBadge";
import OpenRemediationCaseButton from "../components/OpenRemediationCaseButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

type Filter = "all" | "pending" | "abstained" | "confirmed";

const FILTER_LABELS: Record<Filter, string> = {
  all: "Tous",
  pending: "À examiner",
  abstained: "Abstentions",
  confirmed: "Confirmés",
};

const VERDICT_OPTIONS: { value: Verdict; label: string }[] = (
  ["compliant", "partial", "non_compliant", "missing"] as Verdict[]
).map((v) => ({ value: v, label: verdictDisplay(v).label }));

/** Revue humaine — desktop: finding queue | AI proposal | evidence, with a
    sticky decision dock always in view; mobile: queue drawer + proposal /
    evidence tabs (spec §8.4). The AI draft is immutable; the human decision
    is recorded beside it, never in its place. */
export default function ReviewWorkspacePage() {
  const { orgId, assessmentId } = useParams<{ orgId: string; assessmentId: string }>();
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [queueOpen, setQueueOpen] = useState(false);
  const isMobile = useIsMobile();

  const detail = useQuery({
    queryKey: ["assessment", orgId, assessmentId],
    queryFn: () => api.getAssessment(orgId!, assessmentId!),
    refetchInterval: (query) => (query.state.data?.status === "RUNNING" ? 2000 : false),
  });

  const findings = detail.data?.findings ?? [];
  const filtered = useMemo(
    () =>
      findings.filter((f) => {
        if (filter === "pending") return f.review_status === "PENDING";
        if (filter === "confirmed") return f.review_status === "CONFIRMED";
        if (filter === "abstained") return f.status === "ABSTAINED";
        return true;
      }),
    [findings, filter],
  );
  // resolve the selection against the FILTERED list: a finding excluded by
  // the active filter must never stay displayed in the detail panel
  const selected =
    (selectedId && filtered.find((f) => f.id === selectedId)) || filtered[0] || null;
  const selectedIndex = selected ? filtered.findIndex((f) => f.id === selected.id) : -1;

  const finding = useQuery({
    queryKey: ["finding", orgId, assessmentId, selected?.id],
    queryFn: () => api.getFinding(orgId!, assessmentId!, selected!.id),
    enabled: !!selected,
  });

  if (detail.isError) {
    return <p className="text-sm text-destructive">{(detail.error as Error).message}</p>;
  }
  if (!detail.data) {
    return <p className="text-sm text-muted-foreground">Chargement…</p>;
  }
  const a = detail.data;
  const reviewPct = a.total > 0 ? Math.round((a.reviewed_count / a.total) * 100) : 0;

  const selectFinding = (id: string) => {
    setSelectedId(id);
    setQueueOpen(false); // drawers close after navigation
  };

  const statusBadge =
    a.status === "RUNNING" ? (
      <Badge variant="info" className="gap-1.5">
        <span aria-hidden className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
        En cours
      </Badge>
    ) : a.status === "COMPLETED" ? (
      <Badge variant="success">Terminée</Badge>
    ) : (
      <Badge variant="danger">Échouée</Badge>
    );

  const queue = (
    <FindingList findings={filtered} selectedId={selected?.id ?? null} onSelect={selectFinding} />
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3 border-b pb-4">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Revue humaine</h1>
        {statusBadge}
        <span aria-live="polite" className="text-sm text-muted-foreground tabular-nums">
          {a.reviewed_count} / {a.total} confirmés
        </span>
        <div
          className="h-1.5 w-32 overflow-hidden rounded-full bg-muted"
          role="presentation"
          aria-hidden="true"
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-500"
            style={{ width: `${reviewPct}%` }}
          />
        </div>
        {a.status === "RUNNING" && (
          <span className="text-sm text-muted-foreground">
            évaluation en cours — les constats apparaissent au fil de l'eau
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filtres">
          {(Object.keys(FILTER_LABELS) as Filter[]).map((key) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              aria-pressed={filter === key}
              className={cn(
                "min-h-10 rounded-md px-4 text-xs font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-ring",
                filter === key
                  ? "bg-ink text-ink-foreground"
                  : "border border-input bg-card text-muted-foreground hover:bg-muted/60",
              )}
            >
              {FILTER_LABELS[key]}
            </button>
          ))}
        </div>
        {/* mobile: the finding queue lives in a drawer */}
        <Sheet open={queueOpen} onOpenChange={setQueueOpen}>
          <SheetTrigger asChild>
            <Button variant="outline" size="sm" className="ml-auto min-h-10 lg:hidden">
              <ListChecks className="size-3.5" aria-hidden="true" />
              Constats ({filtered.length})
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-[300px] overflow-y-auto p-4">
            <SheetHeader className="p-0 pb-3">
              <SheetTitle>Constats</SheetTitle>
            </SheetHeader>
            {queue}
          </SheetContent>
        </Sheet>
      </div>

      {/* announce selection changes for screen readers */}
      <p aria-live="polite" className="sr-only">
        {selected
          ? `Constat sélectionné : exigence ${selected.requirement_id}`
          : "Aucun constat sélectionné"}
      </p>

      <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)] lg:items-start">
        <div className="hidden lg:block">{queue}</div>

        {selected ? (
          <div className="min-w-0 space-y-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground">
                Constat{" "}
                <span className="font-mono font-medium text-foreground">{selectedIndex + 1}</span>{" "}
                sur <span className="font-mono font-medium text-foreground">{filtered.length}</span>
              </p>
              <div className="flex gap-1.5">
                <Button
                  variant="outline"
                  size="icon"
                  className="size-10"
                  aria-label="Constat précédent"
                  disabled={selectedIndex <= 0}
                  onClick={() => selectFinding(filtered[selectedIndex - 1].id)}
                >
                  <ChevronLeft className="size-4" aria-hidden="true" />
                </Button>
                <Button
                  variant="outline"
                  size="icon"
                  className="size-10"
                  aria-label="Constat suivant"
                  disabled={selectedIndex >= filtered.length - 1}
                  onClick={() => selectFinding(filtered[selectedIndex + 1].id)}
                >
                  <ChevronRight className="size-4" aria-hidden="true" />
                </Button>
              </div>
            </div>

            {finding.isError && (
              <p className="text-sm text-destructive">{(finding.error as Error).message}</p>
            )}
            {!finding.data && !finding.isError && (
              <p className="text-sm text-muted-foreground">Chargement…</p>
            )}
            {finding.data && (
              <>
                {isMobile ? (
                  <Tabs defaultValue="proposal">
                    <TabsList className="w-full">
                      <TabsTrigger value="proposal" className="flex-1">
                        Proposition IA
                      </TabsTrigger>
                      <TabsTrigger value="evidence" className="flex-1">
                        Preuves
                      </TabsTrigger>
                    </TabsList>
                    <TabsContent value="proposal">
                      <RequirementPane finding={finding.data} />
                    </TabsContent>
                    <TabsContent value="evidence">
                      <EvidencePane finding={finding.data} />
                    </TabsContent>
                  </Tabs>
                ) : (
                  <div className="grid gap-5 xl:grid-cols-2">
                    <RequirementPane finding={finding.data} />
                    <EvidencePane finding={finding.data} />
                  </div>
                )}
                <DecisionDock
                  orgId={orgId!}
                  assessmentId={assessmentId!}
                  finding={finding.data}
                />
              </>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Aucun constat pour ce filtre.</p>
        )}
      </div>
    </div>
  );
}

function FindingList({
  findings,
  selectedId,
  onSelect,
}: {
  findings: FindingSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <ul
      className="space-y-1.5 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-14rem)] lg:overflow-y-auto lg:pr-1"
      aria-label="Constats"
    >
      {findings.map((f) => {
        const infra = isInfraAbstain(f.abstain_reason);
        return (
          <li key={f.id}>
            <button
              onClick={() => onSelect(f.id)}
              aria-current={f.id === selectedId}
              className={cn(
                "w-full rounded-lg border p-3 text-left text-sm transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-ring",
                f.id === selectedId
                  ? "border-primary/50 bg-accent"
                  : "border-border bg-card hover:bg-muted/50",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[13px] font-semibold">{f.requirement_id}</span>
                <ReviewStatusBadge status={f.review_status} />
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {f.status === "VERIFIED" ? (
                  <VerdictBadge verdict={f.verdict} />
                ) : infra ? (
                  <Badge variant="neutral">Échec technique — relancez l'évaluation</Badge>
                ) : (
                  <Badge variant="warning">Nécessite votre jugement</Badge>
                )}
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function RequirementPane({ finding: f }: { finding: FindingDetail }) {
  const infra = isInfraAbstain(f.abstain_reason);
  return (
    <section className="space-y-4 rounded-lg border bg-card p-5">
      <h2 className="font-mono text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
        Exigence ISO
      </h2>
      <div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-lg font-semibold">{f.requirement_id}</span>
          {f.domain && <span className="text-xs text-muted-foreground">{f.domain}</span>}
        </div>
        {f.requirement_fr ? (
          <p className="mt-2 text-sm leading-relaxed text-foreground/90">{f.requirement_fr}</p>
        ) : (
          <p className="mt-2 text-sm text-warning-foreground dark:text-warning">
            Texte de l'exigence indisponible : constat antérieur aux instantanés et version de
            corpus différente ({f.corpus_mismatch ? "corpus modifié depuis" : ""}).
          </p>
        )}
      </div>

      <div
        className={cn(
          "rounded-lg border p-4",
          f.status === "VERIFIED"
            ? "border-border bg-muted/50"
            : infra
              ? "border-border bg-muted"
              : "border-warning/40 bg-warning/10",
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[10.5px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
            {f.status === "VERIFIED"
              ? "Brouillon IA — citation localisée, pertinence à confirmer"
              : "Brouillon IA — abstention"}
          </span>
          {f.status === "VERIFIED" ? (
            <VerdictBadge verdict={f.verdict} />
          ) : (
            <AbstainReasonLabel reason={f.abstain_reason} />
          )}
        </div>
        {f.rationale && (
          <p className="mt-2 text-sm leading-relaxed text-foreground/90">{f.rationale}</p>
        )}
        {f.status === "ABSTAINED" && !infra && (
          <p className="mt-2 text-xs text-warning-foreground dark:text-warning">
            Le système n'a pas pu produire de citation vérifiable — ce constat nécessite votre
            jugement (« choisir un autre verdict »).
          </p>
        )}
      </div>

      <ProvenanceDisclosure finding={f} />
    </section>
  );
}

function ProvenanceDisclosure({ finding: f }: { finding: FindingDetail }) {
  return (
    <details className="rounded-lg border border-dashed bg-muted/30 p-3 text-sm">
      <summary className="cursor-pointer font-medium text-muted-foreground select-none [&::-webkit-details-marker]:hidden">
        Détails techniques (provenance IA)
      </summary>
      <div className="mt-3 space-y-3 text-xs text-muted-foreground">
        <p>
          {f.attempts} tentative{f.attempts > 1 ? "s" : ""}
          {f.final_model ? ` · modèle ${f.final_model}` : ""}
          {f.confidence !== null ? ` · confiance déclarée ${f.confidence.toFixed(2)}` : ""}
        </p>
        {f.policy_quote && (
          <p>
            Citation déclarée par le modèle (audit — le texte affiché comme preuve est l'extrait
            source) : « {f.policy_quote} »
          </p>
        )}
        {f.attempt_history.map((att) => (
          <div key={att.attempt_number} className="rounded-md border border-border/60 p-2">
            <p className="font-medium">
              Tentative {att.attempt_number} ({att.prompt_version}) —{" "}
              {att.parsed_ok ? "analysée" : "non analysable"}
            </p>
            {att.llm_calls.map((c) => (
              <p key={c.call_number}>
                appel {c.call_number} : {c.provider}/{c.requested_model} → {c.status}
                {c.http_status ? ` (${c.http_status})` : ""}
                {c.error ? ` — ${c.error}` : ""}
              </p>
            ))}
            {att.verifier_errors?.map((e, i) => (
              <p key={i} className="text-warning-foreground dark:text-warning">
                vérif ✗ {e}
              </p>
            ))}
          </div>
        ))}
        {(f.audit_log ?? []).length > 0 && (
          <p>Trace : {(f.audit_log ?? []).map((e) => `${e.node}/${e.event}`).join(" → ")}</p>
        )}
      </div>
    </details>
  );
}

function EvidencePane({ finding: f }: { finding: FindingDetail }) {
  const matched = f.retrieved.find((r) => r.result_id === f.matched_chunk_id) ?? null;
  const others = f.retrieved.filter((r) => r.result_id !== f.matched_chunk_id);
  const localStart =
    matched && f.match_start !== null ? f.match_start - (matched.char_start ?? 0) : null;
  const localEnd =
    matched && f.match_end !== null ? f.match_end - (matched.char_start ?? 0) : null;

  return (
    <section className="space-y-4 rounded-lg border bg-card p-5">
      <h2 className="font-mono text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
        Preuves (documents de l'organisation)
      </h2>

      {matched && (
        <div
          className={cn(
            "rounded-lg border p-4",
            f.source_quote_kind === "candidate"
              ? "border-warning/40 bg-warning/10"
              : "border-success/30 bg-success/5",
          )}
        >
          <p className="text-xs font-medium text-muted-foreground">
            {matched.filename}
            {matched.page_number ? `, p.${matched.page_number}` : ""} —{" "}
            {f.source_quote_kind === "candidate"
              ? "passage candidat (correspondance approximative)"
              : "citation localisée et vérifiée par le code"}
          </p>
          <p className="mt-2 text-sm leading-relaxed text-foreground">
            <HighlightedText
              text={matched.text}
              start={f.source_quote_error ? null : localStart}
              end={f.source_quote_error ? null : localEnd}
            />
          </p>
          {f.source_quote && f.source_quote_kind === "verified" && (
            <>
              <p className="mt-2 text-xs text-muted-foreground">
                Extrait source (autoritatif) : « {f.source_quote} »
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Le code garantit que ce passage existe mot pour mot — sa pertinence pour
                l'exigence reste votre jugement.
              </p>
            </>
          )}
          {f.source_quote && f.source_quote_kind === "candidate" && (
            <p className="mt-2 text-xs font-medium text-warning-foreground dark:text-warning">
              Localisation approximative retenue pour votre revue — ce n'est pas une citation
              vérifiée.
            </p>
          )}
          {f.source_quote_error && (
            <p className="mt-2 text-xs font-medium text-warning-foreground dark:text-warning">
              Provenance non affichable : {f.source_quote_error}
            </p>
          )}
        </div>
      )}
      {!matched && (
        <p className="text-sm text-muted-foreground">
          Aucun passage cité — extraits récupérés ci-dessous.
        </p>
      )}

      {others.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm font-medium text-muted-foreground select-none [&::-webkit-details-marker]:hidden">
            Autres extraits récupérés ({others.length})
          </summary>
          <ul className="mt-3 space-y-3">
            {others.map((r) => (
              <li key={r.result_id} className="rounded-lg border border-border p-3">
                <p className="text-xs font-medium text-muted-foreground">
                  {r.source_type === "policy"
                    ? `${r.filename ?? "document"}${r.page_number ? `, p.${r.page_number}` : ""}`
                    : `Exigence ISO ${r.requirement_id}`}
                </p>
                <p className="mt-1 text-sm leading-relaxed whitespace-pre-wrap text-foreground/90">
                  {r.text}
                </p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/** Sticky decision dock — the human decision stays reachable without
    scrolling. Approve = confirm the AI verdict; edit = change the human
    rationale; override = choose another verdict (the only path for
    abstentions). */
function DecisionDock({
  orgId,
  assessmentId,
  finding: f,
}: {
  orgId: string;
  assessmentId: string;
  finding: FindingDetail;
}) {
  const queryClient = useQueryClient();
  const [action, setAction] = useState<ReviewAction | null>(null);
  const [humanVerdict, setHumanVerdict] = useState<Verdict>("partial");
  const [rationale, setRationale] = useState("");
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState("");

  const review = useMutation({
    mutationFn: () =>
      api.reviewFinding(orgId, assessmentId, f.id, {
        action: action!,
        human_verdict: action === "override" ? humanVerdict : undefined,
        human_rationale: rationale || undefined,
        review_note: note || undefined,
        reviewer_label: reviewer || undefined,
      }),
    onSuccess: () => {
      setAction(null);
      setRationale("");
      setNote("");
      queryClient.invalidateQueries({ queryKey: ["finding", orgId, assessmentId, f.id] });
      queryClient.invalidateQueries({ queryKey: ["assessment", orgId, assessmentId] });
    },
  });

  const abstained = f.status === "ABSTAINED";
  const needsRationale = action === "edit" || action === "override";
  const submitDisabled = review.isPending || (needsRationale && !rationale.trim());
  const approveLabel = f.verdict
    ? `Confirmer « ${verdictDisplay(f.verdict).label} »`
    : "Confirmer le verdict IA";

  return (
    <section className="sticky bottom-0 z-10 -mx-1 space-y-4 rounded-t-lg border bg-card p-5 pb-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-mono text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
          Votre décision
        </h2>
        <ReviewStatusBadge status={f.review_status} />
        <Link
          to={`/organizations/${orgId}/chat?finding=${f.id}`}
          className="ml-auto inline-flex min-h-10 items-center gap-1 text-xs font-medium underline-offset-4 hover:underline"
        >
          <MessageSquareText className="size-3.5" aria-hidden="true" />
          Expliquer via le copilote
        </Link>
      </div>

      {f.review_status === "CONFIRMED" && (
        <div className="rounded-lg border border-success/30 bg-success/5 p-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{reviewActionDisplay(f.review_action).label}</span>
            <VerdictBadge verdict={f.human_verdict} />
            <span className="text-xs text-muted-foreground">
              le {f.reviewed_at ? new Date(f.reviewed_at).toLocaleString("fr-FR") : ""}
            </span>
          </div>
          {f.human_rationale && <p className="mt-2 text-foreground/90">{f.human_rationale}</p>}
          {f.review_note && (
            <p className="mt-1 text-xs text-muted-foreground">Note : {f.review_note}</p>
          )}
          <p className="mt-2 text-xs text-muted-foreground">
            Le brouillon IA reste affiché tel quel ci-dessus — votre décision est enregistrée à
            côté, jamais à sa place. Vous pouvez réviser votre décision : l'historique conserve
            chaque version.
          </p>
          {["partial", "non_compliant", "missing"].includes(f.human_verdict ?? "") && (
            <OpenRemediationCaseButton orgId={orgId} findingId={f.id} />
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2" role="group" aria-label="Actions de revue">
        <button
          onClick={() => setAction("approve")}
          disabled={abstained}
          aria-pressed={action === "approve"}
          title={
            abstained
              ? "Un constat en abstention nécessite votre verdict (« choisir un autre verdict »)"
              : undefined
          }
          className={cn(
            "min-h-10 rounded-md px-4 text-sm font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-success",
            action === "approve"
              ? "bg-success text-success-foreground"
              : "border border-success/40 text-success hover:bg-success/10 disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          {approveLabel}
        </button>
        <button
          onClick={() => setAction("edit")}
          disabled={abstained}
          aria-pressed={action === "edit"}
          title={
            abstained
              ? "Un constat en abstention nécessite votre verdict (« choisir un autre verdict »)"
              : undefined
          }
          className={cn(
            "min-h-10 rounded-md px-4 text-sm font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-ring",
            action === "edit"
              ? "bg-primary text-primary-foreground"
              : "border border-input text-foreground hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          Modifier la justification
        </button>
        <button
          onClick={() => setAction("override")}
          aria-pressed={action === "override"}
          className={cn(
            "min-h-10 rounded-md px-4 text-sm font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-warning",
            action === "override"
              ? "bg-warning text-warning-foreground"
              : "border border-warning/50 text-warning-foreground hover:bg-warning/10 dark:text-warning",
          )}
        >
          Choisir un autre verdict
        </button>
        {abstained && (
          <span className="self-center text-xs text-warning-foreground dark:text-warning">
            Abstention : seul « Choisir un autre verdict » est possible — le verdict vous
            appartient.
          </span>
        )}
      </div>

      {action && (
        <form
          className="max-h-[45dvh] space-y-3 overflow-y-auto rounded-lg border bg-muted/30 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            review.mutate();
          }}
        >
          {action === "override" && (
            <label className="block text-sm">
              <span className="font-medium">Votre verdict</span>
              <select
                value={humanVerdict}
                onChange={(e) => setHumanVerdict(e.target.value as Verdict)}
                className="mt-1 block rounded-md border border-input bg-card px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
              >
                {VERDICT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="block text-sm">
            <span className="font-medium">
              Justification{needsRationale ? " (requise)" : " (facultative)"}
            </span>
            <textarea
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              rows={3}
              className="mt-1 block w-full rounded-md border border-input bg-card px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="font-medium">Note (facultative)</span>
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="mt-1 block w-full rounded-md border border-input bg-card px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium">Votre nom (facultatif, non vérifié)</span>
              <input
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                className="mt-1 block w-full rounded-md border border-input bg-card px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
              />
            </label>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitDisabled}
              className="min-h-10 rounded-md bg-primary px-5 text-sm font-semibold text-primary-foreground transition-colors duration-150 hover:bg-primary/90 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              {review.isPending ? "Enregistrement…" : "Enregistrer la décision"}
            </button>
            {review.isError && (
              <p className="text-sm text-destructive">{(review.error as Error).message}</p>
            )}
          </div>
        </form>
      )}

      {f.reviews.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer font-medium text-muted-foreground select-none [&::-webkit-details-marker]:hidden">
            Historique des décisions ({f.reviews.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {f.reviews.map((r) => (
              <li key={r.sequence} className="rounded-lg border border-border p-3 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">#{r.sequence}</span>
                  <span>{reviewActionDisplay(r.action).label}</span>
                  <VerdictBadge verdict={r.human_verdict} />
                  <span className="text-muted-foreground">
                    {new Date(r.created_at).toLocaleString("fr-FR")}
                  </span>
                  {r.reviewer_label && (
                    <span className="text-muted-foreground">
                      par {r.reviewer_label} (non vérifié)
                    </span>
                  )}
                </div>
                {r.human_rationale && (
                  <p className="mt-1 text-muted-foreground">{r.human_rationale}</p>
                )}
                {r.review_note && <p className="mt-1 text-muted-foreground">Note : {r.review_note}</p>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
