import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, Download, ShieldCheck, TriangleAlert, UserCheck } from "lucide-react";
import {
  api,
  Assessment,
  ConformityDomain,
  ConformityReport,
  RemediationCase,
  ReportingScopeMeta,
  RiskRow,
  TrustPanel as TrustPanelData,
  Verdict,
} from "../api";
import { severityDisplay, verdictDisplay } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";
import { MetricLedger } from "@/components/metric-ledger";
import { NextActionPanel } from "@/components/next-action-panel";
import { SectionHeading } from "@/components/section-heading";
import { StatusLabel } from "@/components/status-label";
import { TechnicalDisclosure } from "@/components/technical-disclosure";
import { WorkflowStrip, type WorkflowStep } from "@/components/workflow-strip";
import { PanelSkeleton } from "@/components/data-skeletons";

export default function DashboardPage() {
  const { orgId } = useParams<{ orgId: string }>();
  // "" = organisation (derniers verdicts confirmés)
  const [assessmentId, setAssessmentId] = useState("");
  const [includePreliminary, setIncludePreliminary] = useState(false);

  const assessments = useQuery({
    queryKey: ["assessments", orgId],
    queryFn: () => api.listAssessments(orgId!),
  });
  const selected = (assessments.data ?? []).find((a) => a.id === assessmentId);
  // the checkbox must stay reachable whenever a preliminary result is possible:
  // org mode (fold RUNNING/FAILED manifests in) AND a selected non-COMPLETED
  // assessment (without it the PDF button can only hit the designed 409)
  const preliminaryChoiceVisible = !assessmentId || (selected && selected.status !== "COMPLETED");
  // the TRANSMITTED flag is derived from visibility: a stale checked value
  // must never mark a COMPLETED assessment preliminary after a scope switch
  const effectivePreliminary = preliminaryChoiceVisible ? includePreliminary : false;

  const params = {
    assessmentId: assessmentId || undefined,
    includePreliminary: effectivePreliminary || undefined,
  };
  const conformity = useQuery({
    queryKey: ["conformity", orgId, assessmentId, effectivePreliminary],
    queryFn: () => api.getConformity(orgId!, params),
  });
  const trust = useQuery({
    queryKey: ["trust", orgId, assessmentId, effectivePreliminary],
    queryFn: () => api.getTrustPanel(orgId!, params),
  });
  // Operational sources beyond conformity: the risk register (same reporting
  // scope — one row per latest human-confirmed gap, treatment only annotates)
  // and the remediation cases (org-wide endpoint: no assessment scoping).
  const risks = useQuery({
    queryKey: ["risk-register", orgId, assessmentId, effectivePreliminary],
    queryFn: () => api.getRiskRegister(orgId!, params),
  });
  const cases = useQuery({
    queryKey: ["remediation-cases", orgId],
    queryFn: () => api.listCases(orgId!),
  });
  const documents = useQuery({
    queryKey: ["documents", orgId],
    queryFn: () => api.listDocuments(orgId!),
  });
  const activeCases = (cases.data ?? []).filter((c) => c.status !== "CLOSED").length;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Vue d'ensemble"
        description="Verdicts confirmés par un humain, citations vérifiées par le code."
        actions={
          <Button asChild variant="outline">
            <a href={api.reportDownloadUrl(orgId!, params)} download>
              <Download className="size-4" aria-hidden="true" />
              Exporter le rapport PDF
            </a>
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-4 py-2.5">
        <label htmlFor="scope-select" className="text-sm text-muted-foreground">
          Périmètre
        </label>
        <select
          id="scope-select"
          value={assessmentId}
          onChange={(e) => setAssessmentId(e.target.value)}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30"
        >
          <option value="">Organisation — derniers verdicts confirmés</option>
          {(assessments.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              Évaluation {a.id.slice(0, 8)} ·{" "}
              {a.status === "COMPLETED" ? "terminée" : "en cours (préliminaire)"}
            </option>
          ))}
        </select>
        {preliminaryChoiceVisible && (
          <label className="flex min-h-10 items-center gap-1.5 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={includePreliminary}
              onChange={(e) => setIncludePreliminary(e.target.checked)}
              className="accent-[var(--primary)]"
            />
            {assessmentId
              ? "autoriser un aperçu préliminaire (évaluation non terminée)"
              : "inclure les évaluations préliminaires"}
          </label>
        )}
      </div>

      {conformity.data && <ScopeBanners scope={conformity.data.scope} />}

      <NextAction
        orgId={orgId!}
        assessments={assessments.data}
        cases={cases.data}
        risks={risks.data?.rows}
        documentCount={documents.data?.length}
      />

      <ScoreLedger
        conformity={conformity.data}
        loading={conformity.isLoading}
        error={conformity.isError}
        gapCount={risks.data ? risks.data.rows.length : null}
        gapLoading={risks.isLoading}
        gapError={risks.isError}
        activeCases={cases.data ? activeCases : null}
        casesLoading={cases.isLoading}
        casesError={cases.isError}
        assessmentScoped={!!assessmentId}
      />

      <LifecycleStrip
        documentCount={documents.data?.length}
        assessments={assessments.data}
        risks={risks.data?.rows}
        cases={cases.data}
      />

      {conformity.isLoading && <PanelSkeleton />}
      {conformity.error && (
        <Alert variant="destructive">
          <TriangleAlert aria-hidden="true" />
          <AlertDescription>{(conformity.error as Error).message}</AlertDescription>
        </Alert>
      )}

      {risks.data && risks.data.rows.length > 0 && (
        <PriorityTable orgId={orgId!} rows={risks.data.rows} />
      )}

      {conformity.data && <DomainSection data={conformity.data} />}

      {trust.data && <TrustSection data={trust.data} />}
    </div>
  );
}

function ScopeBanners({ scope }: { scope: ReportingScopeMeta }) {
  return (
    <div className="space-y-2">
      {scope.is_preliminary && (
        <p className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-warning-foreground dark:text-warning">
          Résultat <strong>préliminaire</strong> — il inclut des évaluations non terminées et ne
          constitue pas un état officiel.
        </p>
      )}
      {!scope.scope_complete && (
        <p className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-warning-foreground dark:text-warning">
          Périmètre incomplet : {scope.legacy_manifest_missing_ids.length} évaluation(s) sans
          manifeste d'exigences (antérieures) sont hors du dénominateur — leurs constats ne sont
          pas comptés. Ce rapport ne peut pas être qualifié d'officiel.
        </p>
      )}
    </div>
  );
}

// ------------------------------------------------------------- next action

/** Suggested next-action priority (spec §8.2) — the first matching state wins. */
function NextAction({
  orgId,
  assessments,
  cases,
  risks,
  documentCount,
}: {
  orgId: string;
  assessments: Assessment[] | undefined;
  cases: RemediationCase[] | undefined;
  risks: RiskRow[] | undefined;
  documentCount: number | undefined;
}) {
  const base = `/organizations/${orgId}`;
  const latest = (list: Assessment[]) =>
    [...list].sort((a, b) => b.started_at.localeCompare(a.started_at));

  // 1 — running assessment
  const running = assessments?.find((a) => a.status === "RUNNING");
  if (running) {
    return (
      <NextActionPanel
        title="Une évaluation est en cours"
        description="Le système analyse vos documents exigence par exigence. Vous pourrez confirmer les constats dès la fin du traitement."
        actionLabel="Suivre l'évaluation"
        actionTo={`${base}/evaluations`}
      />
    );
  }
  // 2 — pending human review
  const pendingReview = assessments
    ? latest(
        assessments.filter((a) => a.status === "COMPLETED" && a.reviewed_count < a.findings_done),
      )[0]
    : undefined;
  if (pendingReview) {
    const remaining = pendingReview.findings_done - pendingReview.reviewed_count;
    return (
      <NextActionPanel
        eyebrow="Action prioritaire"
        icon={UserCheck}
        title={`${remaining} constat${remaining > 1 ? "s" : ""} attend${remaining > 1 ? "ent" : ""} votre décision`}
        description="L'IA a proposé des verdicts ; ils ne comptent dans la conformité qu'une fois confirmés par vous."
        actionLabel="Reprendre la revue humaine"
        actionTo={`${base}/assessments/${pendingReview.id}`}
      />
    );
  }
  // 3/4/5 — remediation flow states (list-level view; plan verification
  // details live on the case page)
  const caseByStatus = (status: RemediationCase["status"]) =>
    cases?.find((c) => c.status === status);
  const planReady = caseByStatus("PLAN_READY");
  if (planReady) {
    return (
      <NextActionPanel
        title="Un plan d'action attend votre examen"
        description="Le plan proposé pour un écart confirmé doit être validé action par action avant d'être lancé."
        actionLabel="Examiner le plan"
        actionTo={`${base}/remediation/${planReady.id}`}
      />
    );
  }
  const triage = caseByStatus("TRIAGE") ?? caseByStatus("TRIAGE_APPROVED");
  if (triage) {
    return (
      <NextActionPanel
        title={
          triage.status === "TRIAGE"
            ? "Un écart attend sa qualification"
            : "Un cas attend la rédaction de son plan"
        }
        description="Poursuivez le traitement du cas de remédiation pour avancer vers la clôture."
        actionLabel="Ouvrir le cas"
        actionTo={`${base}/remediation/${triage.id}`}
      />
    );
  }
  const inProgress = caseByStatus("IN_PROGRESS");
  if (inProgress) {
    return (
      <NextActionPanel
        title="Des actions de remédiation sont en cours"
        description="Faites avancer les actions validées, puis vérifiez leur efficacité avant de clôturer le cas."
        actionLabel="Suivre les actions"
        actionTo={`${base}/remediation/${inProgress.id}`}
      />
    );
  }
  // 7 — confirmed risk without treatment
  const untreated = risks?.find((r) => !r.treatment?.active_case_id);
  if (untreated) {
    return (
      <NextActionPanel
        tone="attention"
        title={`L'exigence ${untreated.requirement_id} présente un écart confirmé sans traitement`}
        description="Ouvrez un cas de remédiation pour cet écart, ou documentez la décision de ne pas le traiter."
        actionLabel="Voir les risques"
        actionTo={`${base}/risk-register`}
      />
    );
  }
  // 8 — no prepared evidence
  if (documentCount === 0) {
    return (
      <NextActionPanel
        title="Aucune preuve n'est encore préparée"
        description="Déposez les politiques et procédures de l'organisation : elles constituent la base de toute évaluation."
        actionLabel="Ajouter des preuves"
        actionTo={`${base}/evaluations?vue=preuves`}
      />
    );
  }
  // 9 — no evaluation yet
  if (assessments && assessments.length === 0) {
    return (
      <NextActionPanel
        title="Aucune évaluation n'a encore été lancée"
        description="Lancez une première évaluation : l'IA proposera un constat par exigence, que vous confirmerez ensuite."
        actionLabel="Lancer une évaluation"
        actionTo={`${base}/evaluations`}
      />
    );
  }
  if (!assessments || !cases) return null;
  return (
    <NextActionPanel
      tone="done"
      eyebrow="Aucune action urgente"
      icon={Check}
      title="Tout est à jour"
      description="Les constats confirmés sont traités. Vous pouvez relancer une évaluation après toute mise à jour des documents."
      actionLabel="Voir les évaluations"
      actionTo={`${base}/evaluations`}
    />
  );
}

// ------------------------------------------------------------ score ledger

/** Three DISTINCT denominators, each labelled with what it divides by —
    an evaluated-conformity % must never read as % of the whole standard. */
function ScoreLedger({
  conformity,
  loading,
  error,
  gapCount,
  gapLoading,
  gapError,
  activeCases,
  casesLoading,
  casesError,
  assessmentScoped,
}: {
  conformity: ConformityReport | undefined;
  loading: boolean;
  error: boolean;
  gapCount: number | null;
  gapLoading: boolean;
  gapError: boolean;
  activeCases: number | null;
  casesLoading: boolean;
  casesError: boolean;
  assessmentScoped: boolean;
}) {
  const kbTotal = conformity?.scope.kb_total_requirements;
  return (
    <section aria-label="Scores et couverture" className="space-y-2">
      <MetricLedger
        loading={loading}
        error={error}
        entries={[
          {
            label: "Conformité évaluée",
            value:
              conformity?.global_pct === null || conformity?.global_pct === undefined
                ? "—"
                : `${conformity.global_pct}%`,
            caption: conformity
              ? `Calculée sur les ${conformity.scored} exigence(s) confirmée(s) uniquement — pas sur toute la norme.`
              : undefined,
          },
          {
            label: "Couverture du périmètre",
            value: conformity ? `${conformity.scored}/${conformity.total_in_scope}` : "—",
            caption: "Exigences du périmètre déjà confirmées par un humain.",
          },
          {
            label: "Couverture de la norme",
            value:
              conformity && kbTotal ? `${conformity.total_in_scope}/${kbTotal}` : "—",
            caption: "Part des exigences ISO/IEC 42001 couvertes par le périmètre évalué.",
          },
        ]}
      />
      <MetricLedger
        columns={2}
        entries={[
          {
            label: "Écarts confirmés",
            value: gapLoading ? "…" : gapError ? "—" : (gapCount ?? "—"),
            caption: gapError
              ? "Indisponible"
              : "Écarts confirmés par un humain au registre des risques — un traitement en cours ne retire pas l'écart.",
          },
          {
            label: "Cas de remédiation actifs",
            value: casesLoading ? "…" : casesError ? "—" : (activeCases ?? "—"),
            caption: casesError
              ? "Indisponible"
              : assessmentScoped
                ? "Toute l'organisation — les cas ne sont pas limités au périmètre sélectionné."
                : "Cas non clôturés, toute l'organisation.",
          },
        ]}
      />
      {conformity && (
        <p className="text-xs leading-relaxed text-muted-foreground">
          Conformité calculée sur{" "}
          <strong className="font-medium text-foreground">{conformity.scored}</strong>{" "}
          exigence(s) confirmée(s) /{" "}
          <strong className="font-medium text-foreground">{conformity.total_in_scope}</strong> du
          périmètre
          {conformity.coverage_pct !== null && <> ({conformity.coverage_pct}% couvert)</>}
          {kbTotal ? <> — le périmètre couvre {conformity.total_in_scope}/{kbTotal} exigences de la norme.</> : null}
        </p>
      )}
    </section>
  );
}

// -------------------------------------------------------- lifecycle strip

function LifecycleStrip({
  documentCount,
  assessments,
  risks,
  cases,
}: {
  documentCount: number | undefined;
  assessments: Assessment[] | undefined;
  risks: RiskRow[] | undefined;
  cases: RemediationCase[] | undefined;
}) {
  if (documentCount === undefined || !assessments) return null;
  const hasDocs = documentCount > 0;
  const hasCompleted = assessments.some((a) => a.status === "COMPLETED");
  const running = assessments.some((a) => a.status === "RUNNING");
  const confirmedAll =
    hasCompleted &&
    assessments
      .filter((a) => a.status === "COMPLETED")
      .every((a) => a.reviewed_count >= a.findings_done);
  const someConfirmed = assessments.some((a) => a.reviewed_count > 0);
  const gapCount = risks?.length ?? 0;
  const openCases = (cases ?? []).filter((c) => c.status !== "CLOSED");
  const closedCases = (cases ?? []).filter((c) => c.status === "CLOSED");

  const steps: WorkflowStep[] = [
    {
      key: "prepare",
      label: "Préparer les preuves",
      caption: hasDocs ? `${documentCount} document${documentCount > 1 ? "s" : ""}` : "À faire",
      state: hasDocs ? "done" : "current",
    },
    {
      key: "evaluate",
      label: "Évaluer",
      caption: running ? "En cours" : hasCompleted ? "Fait" : undefined,
      state: running ? "current" : hasCompleted ? "done" : hasDocs ? "current" : "todo",
    },
    {
      key: "confirm",
      label: "Confirmer les constats",
      state: confirmedAll && someConfirmed ? "done" : someConfirmed || hasCompleted ? "current" : "todo",
    },
    {
      key: "prioritize",
      label: "Prioriser les risques",
      caption: gapCount > 0 ? `${gapCount} écart${gapCount > 1 ? "s" : ""}` : undefined,
      state: gapCount > 0 ? "current" : someConfirmed ? "done" : "todo",
    },
    {
      key: "act",
      label: "Agir",
      caption: openCases.length > 0 ? `${openCases.length} cas actif${openCases.length > 1 ? "s" : ""}` : undefined,
      state: openCases.length > 0 ? "current" : closedCases.length > 0 ? "done" : "todo",
    },
    {
      key: "close",
      label: "Vérifier et clôturer",
      caption: closedCases.length > 0 ? `${closedCases.length} clôturé${closedCases.length > 1 ? "s" : ""}` : undefined,
      state: closedCases.length > 0 ? (openCases.length === 0 ? "done" : "current") : "todo",
    },
  ];
  return <WorkflowStrip steps={steps} ariaLabel="Parcours de conformité" />;
}

// -------------------------------------------------- prioritized work table

const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

function PriorityTable({ orgId, rows }: { orgId: string; rows: RiskRow[] }) {
  const top = [...rows]
    .sort(
      (a, b) =>
        (SEVERITY_RANK[a.severity ?? "z"] ?? 3) - (SEVERITY_RANK[b.severity ?? "z"] ?? 3) ||
        (b.severity_score ?? 0) - (a.severity_score ?? 0),
    )
    .slice(0, 5);
  return (
    <section className="space-y-3">
      <SectionHeading
        title="À traiter en priorité"
        description="Les écarts confirmés les plus sévères de ce périmètre."
        actions={
          <Button asChild variant="ghost" size="sm">
            <Link to={`/organizations/${orgId}/risk-register`}>
              Tous les risques
              <ArrowRight className="size-3.5" aria-hidden="true" />
            </Link>
          </Button>
        }
      />
      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Exigence</TableHead>
              <TableHead scope="col">Pourquoi ce risque</TableHead>
              <TableHead scope="col">Sévérité</TableHead>
              <TableHead scope="col">Traitement</TableHead>
              <TableHead scope="col">
                <span className="sr-only">Action</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {top.map((r) => (
              <TableRow key={r.finding_id}>
                <TableCell className="font-mono text-[13px] font-semibold whitespace-nowrap">
                  {r.requirement_id}
                </TableCell>
                <TableCell className="max-w-md">
                  <p className="line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">
                    {r.risk_statement_fr}
                  </p>
                </TableCell>
                <TableCell>
                  <StatusLabel display={severityDisplay(r.severity)} />
                </TableCell>
                <TableCell>
                  {r.treatment?.active_case_id ? (
                    <Link
                      to={`/organizations/${orgId}/remediation/${r.treatment.active_case_id}`}
                      className="text-[13px] font-medium underline-offset-2 hover:underline"
                    >
                      Cas en cours
                    </Link>
                  ) : (r.treatment?.closed_case_ids.length ?? 0) > 0 ? (
                    <Badge variant="neutral">Traitement clôturé</Badge>
                  ) : (
                    <Badge variant="warning">Sans traitement</Badge>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <Button asChild variant="ghost" size="sm">
                    <Link to={`/organizations/${orgId}/risk-register`}>
                      Détails
                      <ArrowRight className="size-3.5" aria-hidden="true" />
                    </Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

// ------------------------------------------------------------ domain bars

function DomainSection({ data }: { data: ConformityReport }) {
  return (
    <section className="space-y-3">
      <SectionHeading
        title="Conformité par domaine"
        description={`Couverture de la norme : ${data.total_in_scope}/${data.scope.kb_total_requirements} exigences.`}
      />
      <div className="space-y-4 rounded-lg border bg-card p-5">
        {data.domains.map((d) => (
          <DomainBar key={d.domain} d={d} />
        ))}
        <VerdictLegend counts={data.verdict_counts} />
      </div>
    </section>
  );
}

function DomainBar({ d }: { d: ConformityDomain }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium">
          {d.domain} · {d.domain_title_fr}
        </span>
        <span className="shrink-0 font-mono text-xs text-muted-foreground">
          {d.pct === null ? "non évalué" : `${d.pct}%`} — {d.scored}/{d.total_in_scope} confirmées
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
        {d.pct !== null && (
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]",
              d.pct >= 80 ? "bg-success" : d.pct >= 50 ? "bg-warning" : "bg-destructive",
            )}
            style={{ width: `${d.pct}%` }}
          />
        )}
      </div>
    </div>
  );
}

function VerdictLegend({ counts }: { counts: Record<Verdict, number> }) {
  const order: Verdict[] = ["compliant", "partial", "non_compliant", "missing"];
  return (
    <ul className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t pt-4 text-xs text-muted-foreground">
      {order.map((v) => (
        <li key={v} className="flex items-center gap-1.5">
          <StatusLabel display={verdictDisplay(v)} />
          <span className="font-mono">{counts[v] ?? 0}</span>
        </li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------- trust panel

function TrustSection({ data }: { data: TrustPanelData }) {
  const { gate, review, chat, m6_benchmark } = data;
  return (
    <section className="space-y-3">
      <TechnicalDisclosure summary="Détails techniques et garanties — « peut-on croire l'IA ? »">
        <div className="space-y-5 pt-1 text-foreground">
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <ShieldCheck className="size-4 shrink-0" aria-hidden="true" />
            Méthodologie et garanties structurelles derrière chaque chiffre affiché.
          </p>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-lg border bg-card p-4">
              <p className="text-sm font-semibold">Barrière de vérification</p>
              <dl className="mt-2 space-y-1.5 text-sm text-muted-foreground">
                <Row k="Brouillons IA" v={gate.drafts_total} />
                <Row k="→ citation non vérifiable" v={gate.drafts_with_unsupported_citation} />
                <Row
                  k="Taux de brouillons non étayés"
                  v={
                    gate.unsupported_draft_rate_pct === null
                      ? "—"
                      : `${gate.unsupported_draft_rate_pct}%`
                  }
                />
                <Row k="Schéma invalide" v={gate.drafts_schema_invalid} />
                <Row k="Échec fournisseur LLM" v={gate.drafts_provider_failure} />
                <Row k="Constats en abstention" v={gate.findings_abstained} />
                {gate.legacy_unclassified > 0 && (
                  <Row k="Anciennes tentatives non classées" v={gate.legacy_unclassified} />
                )}
              </dl>
              <p className="mt-3 rounded-md border border-success/25 bg-success/10 px-2.5 py-1.5 text-xs text-success">
                Citations non étayées affichées : {gate.unsupported_citations_displayed} —{" "}
                <strong>invariant structurel</strong> (vérifié, pas mesuré)
              </p>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <p className="text-sm font-semibold">Revue humaine</p>
              <dl className="mt-2 space-y-1.5 text-sm text-muted-foreground">
                <Row k="Décisions de revue" v={review.review_events} />
                <Row k="Approbations" v={review.approve_events} />
                <Row
                  k="Taux d'intervention (modifier + remplacer)"
                  v={
                    review.intervention_rate_pct === null
                      ? "—"
                      : `${review.intervention_rate_pct}%`
                  }
                />
                <Row
                  k="Taux de remplacement du verdict"
                  v={
                    review.verdict_override_rate_pct === null
                      ? "—"
                      : `${review.verdict_override_rate_pct}%`
                  }
                />
              </dl>
              <p className="mt-3 text-xs text-muted-foreground">
                Calculé sur l'historique immuable des décisions (re-revues comprises).
              </p>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <p className="text-sm font-semibold">Copilote (chat)</p>
              <dl className="mt-2 space-y-1.5 text-sm text-muted-foreground">
                <Row k="Messages" v={chat.messages} />
                <Row k="Réponses citées" v={chat.answered} />
                <Row k="Abstentions" v={chat.abstained} />
                <Row k="Citations retirées par la vérification" v={chat.stripped_citation_count} />
              </dl>
              <p className="mt-3 text-xs text-muted-foreground">
                Portée : organisation entière (les messages ne sont pas liés à une évaluation).
              </p>
            </div>
          </div>
          <div className="rounded-lg border border-dashed bg-muted/30 p-4">
            <p className="text-sm font-medium">{String(m6_benchmark.label)}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Référence statique issue de l'évaluation gelée — jamais des données courantes de
              l'organisation. Artefact : {String(m6_benchmark.source_artifact)} (sha256{" "}
              {String(m6_benchmark.source_artifact_sha256).slice(0, 12)}…)
            </p>
            <dl className="mt-3 grid gap-x-6 gap-y-1.5 text-sm text-muted-foreground sm:grid-cols-2">
              <Row
                k="Justesse des verdicts (pipeline)"
                v={String(m6_benchmark.pipeline_verdict_accuracy)}
              />
              <Row
                k="Brouillons non étayés bloqués"
                v={String(m6_benchmark.gate_blocked_unsupported_first_drafts)}
              />
              <Row
                k="Localisation des citations (chat)"
                v={String(m6_benchmark.chat_citation_location_validity)}
              />
              <Row k="Fidélité des réponses (chat)" v={String(m6_benchmark.chat_faithfulness)} />
            </dl>
          </div>
        </div>
      </TechnicalDisclosure>
    </section>
  );
}

function Row({ k, v }: { k: string; v: string | number }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt>{k}</dt>
      <dd className="font-mono font-medium text-foreground">{v}</dd>
    </div>
  );
}
