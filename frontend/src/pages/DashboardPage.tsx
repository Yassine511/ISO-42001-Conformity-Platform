import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCheck,
  Download,
  Gauge,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { Cell, Pie, PieChart } from "recharts";
import {
  api,
  ConformityDomain,
  ConformityReport,
  ReportingScopeMeta,
  RiskRow,
  TrustPanel as TrustPanelData,
  Verdict,
} from "../api";
import { SeverityBadge } from "./RiskRegisterPage";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/page-header";
import { KpiCard } from "@/components/kpi-card";
import { PanelSkeleton } from "@/components/data-skeletons";
import { StaggerGroup, StaggerItem } from "@/components/motion";

const VERDICT_LABELS: Record<Verdict, string> = {
  compliant: "conforme",
  partial: "partiel",
  non_compliant: "non conforme",
  missing: "absent",
};

// tokenized verdict colors — semantic accents resolved by the theme
const VERDICT_COLORS: Record<Verdict, string> = {
  compliant: "var(--success)",
  partial: "var(--warning)",
  non_compliant: "var(--destructive)",
  missing: "var(--chart-4)",
};

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
  // KPI sources beyond conformity: the risk register (same reporting scope —
  // one row per latest human-confirmed gap, treatment only annotates) and the
  // remediation cases (org-wide endpoint: no assessment scoping exists).
  const risks = useQuery({
    queryKey: ["risk-register", orgId, assessmentId, effectivePreliminary],
    queryFn: () => api.getRiskRegister(orgId!, params),
  });
  const cases = useQuery({
    queryKey: ["remediation-cases", orgId],
    queryFn: () => api.listCases(orgId!),
  });
  const activeCases = (cases.data ?? []).filter((c) => c.status !== "CLOSED").length;

  return (
    <div className="space-y-10">
      <PageHeader
        title="Tableau de bord de conformité"
        description="Verdicts confirmés par un humain, citations vérifiées par le code."
        actions={
          <Button asChild variant="outline" className="rounded-full">
            <a href={api.reportDownloadUrl(orgId!, params)} download>
              <Download className="size-4" aria-hidden="true" />
              Exporter le rapport PDF
            </a>
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-card px-4 py-3 shadow-xs">
        <Label htmlFor="scope-select" className="text-muted-foreground">
          Périmètre
        </Label>
        <select
          id="scope-select"
          value={assessmentId}
          onChange={(e) => setAssessmentId(e.target.value)}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30"
        >
          <option value="">Organisation — derniers verdicts confirmés</option>
          {(assessments.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              Évaluation {a.id.slice(0, 8)} ·{" "}
              {a.status === "COMPLETED" ? "terminée" : `${a.status} (préliminaire)`}
            </option>
          ))}
        </select>
        {preliminaryChoiceVisible && (
          <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
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

      <StaggerGroup className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StaggerItem>
          <KpiCard
            icon={Gauge}
            label="Conformité globale"
            value={
              conformity.data?.global_pct === null || conformity.data?.global_pct === undefined
                ? "—"
                : `${conformity.data.global_pct}%`
            }
            caption={
              conformity.data?.coverage_pct !== null && conformity.data?.coverage_pct !== undefined
                ? `${conformity.data.coverage_pct}% du périmètre couvert`
                : undefined
            }
            loading={conformity.isLoading}
            error={conformity.isError}
          />
        </StaggerItem>
        <StaggerItem>
          <KpiCard
            icon={CheckCheck}
            label="Constats confirmés"
            value={
              conformity.data ? `${conformity.data.scored}/${conformity.data.total_in_scope}` : "—"
            }
            caption="Exigences notées après revue humaine"
            loading={conformity.isLoading}
            error={conformity.isError}
          />
        </StaggerItem>
        <StaggerItem>
          <KpiCard
            icon={ShieldAlert}
            label="Écarts ouverts"
            value={risks.data ? risks.data.rows.length : "—"}
            caption="Écarts confirmés au registre des risques"
            loading={risks.isLoading}
            error={risks.isError}
          />
        </StaggerItem>
        <StaggerItem>
          <KpiCard
            icon={Wrench}
            label="Cas de remédiation actifs"
            value={cases.data ? activeCases : "—"}
            caption={assessmentId ? "Ensemble de l'organisation" : "Cas non clôturés"}
            loading={cases.isLoading}
            error={cases.isError}
          />
        </StaggerItem>
      </StaggerGroup>

      {conformity.isLoading && <PanelSkeleton />}
      {conformity.error && (
        <Alert variant="destructive">
          <TriangleAlert aria-hidden="true" />
          <AlertDescription>{(conformity.error as Error).message}</AlertDescription>
        </Alert>
      )}
      {conformity.data && <ConformitySection data={conformity.data} />}
      {risks.data && risks.data.rows.length > 0 && (
        <PrioritySection orgId={orgId!} rows={risks.data.rows} />
      )}
      {trust.data && <TrustSection data={trust.data} />}
    </div>
  );
}

function ScopeBanners({ scope }: { scope: ReportingScopeMeta }) {
  return (
    <div className="space-y-2">
      {scope.is_preliminary && (
        <p className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-sm text-warning-foreground dark:text-warning">
          Résultat <strong>préliminaire</strong> — il inclut des évaluations non terminées et ne
          constitue pas un état officiel.
        </p>
      )}
      {!scope.scope_complete && (
        <p className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-sm text-warning-foreground dark:text-warning">
          Périmètre incomplet : {scope.legacy_manifest_missing_ids.length} évaluation(s) sans
          manifeste d'exigences (antérieures) sont hors du dénominateur — leurs constats ne sont
          pas comptés. Ce rapport ne peut pas être qualifié d'officiel.
        </p>
      )}
    </div>
  );
}

// ------------------------------------------------------------- conformity

function ConformitySection({ data }: { data: ConformityReport }) {
  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Conformité actuelle</h2>
        <p className="text-sm text-muted-foreground">
          Couverture de la norme : {data.total_in_scope}/{data.scope.kb_total_requirements}{" "}
          exigences · politique {data.scope.scoring_policy_version}
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card className="justify-center">
          <CardContent>
            <Donut pct={data.global_pct} />
            <p className="mt-4 text-center text-sm leading-relaxed text-muted-foreground">
              Conformité calculée sur <strong className="text-foreground">{data.scored}</strong>{" "}
              exigence(s) confirmée(s) /{" "}
              <strong className="text-foreground">{data.total_in_scope}</strong> du périmètre
              {data.coverage_pct !== null && <> ({data.coverage_pct}% couvert)</>}
            </p>
            <VerdictLegend counts={data.verdict_counts} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Conformité par domaine</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.domains.map((d) => (
              <DomainBar key={d.domain} d={d} />
            ))}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

function Donut({ pct }: { pct: number | null }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const filled = pct === null ? 0 : (pct / 100) * c;
  return (
    <svg
      viewBox="0 0 140 140"
      className="mx-auto block h-44 w-44"
      role="img"
      aria-label={pct === null ? "Conformité globale : non évaluée" : `Conformité globale : ${pct}%`}
    >
      <circle cx="70" cy="70" r={r} fill="none" stroke="var(--muted)" strokeWidth="12" />
      <circle
        cx="70"
        cy="70"
        r={r}
        fill="none"
        stroke="var(--foreground)"
        strokeWidth="12"
        strokeLinecap="round"
        strokeDasharray={`${filled} ${c - filled}`}
        transform="rotate(-90 70 70)"
      />
      <text
        x="70"
        y="77"
        textAnchor="middle"
        fill="var(--foreground)"
        fontSize="26"
        fontWeight="600"
      >
        {pct === null ? "—" : `${pct}%`}
      </text>
    </svg>
  );
}

function VerdictLegend({ counts }: { counts: Record<Verdict, number> }) {
  const entries = (Object.keys(VERDICT_LABELS) as Verdict[]).map((v) => ({
    verdict: v,
    count: counts[v] ?? 0,
  }));
  const total = entries.reduce((s, e) => s + e.count, 0);
  return (
    <div className="mt-4 flex items-center justify-center gap-4">
      {total > 0 && (
        <PieChart width={72} height={72} aria-hidden="true">
          <Pie
            data={entries.filter((e) => e.count > 0)}
            dataKey="count"
            nameKey="verdict"
            innerRadius={22}
            outerRadius={34}
            strokeWidth={0}
            isAnimationActive={false}
          >
            {entries
              .filter((e) => e.count > 0)
              .map((e) => (
                <Cell key={e.verdict} fill={VERDICT_COLORS[e.verdict]} />
              ))}
          </Pie>
        </PieChart>
      )}
      <ul className="space-y-1 text-xs text-muted-foreground">
        {entries.map(({ verdict, count }) => (
          <li key={verdict} className="flex items-center gap-2">
            <span
              aria-hidden
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: VERDICT_COLORS[verdict] }}
            />
            {VERDICT_LABELS[verdict]} : {count}
          </li>
        ))}
      </ul>
    </div>
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
            className="h-full rounded-full bg-foreground transition-[width] duration-700 ease-[cubic-bezier(0.32,0.72,0,1)]"
            style={{ width: `${d.pct}%` }}
          />
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------- priority actions zone

const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

function PrioritySection({ orgId, rows }: { orgId: string; rows: RiskRow[] }) {
  const top = [...rows]
    .sort(
      (a, b) =>
        (SEVERITY_RANK[a.severity ?? "z"] ?? 3) - (SEVERITY_RANK[b.severity ?? "z"] ?? 3) ||
        (b.severity_score ?? 0) - (a.severity_score ?? 0),
    )
    .slice(0, 3);
  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">À traiter en priorité</h2>
          <p className="text-sm text-muted-foreground">
            Les écarts confirmés les plus sévères de ce périmètre.
          </p>
        </div>
        <Button asChild variant="ghost" size="sm" className="rounded-full">
          <Link to={`/organizations/${orgId}/risk-register`}>
            Registre complet
            <ArrowRight className="size-3.5" aria-hidden="true" />
          </Link>
        </Button>
      </div>
      <ul className="grid gap-3 md:grid-cols-3">
        {top.map((r) => (
          <li key={r.finding_id}>
            <Card className="h-full gap-3 py-5">
              <CardContent className="space-y-2 px-5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-sm font-semibold">{r.requirement_id}</span>
                  <SeverityBadge severity={r.severity} score={r.severity_score} />
                </div>
                <p className="line-clamp-3 text-sm leading-relaxed text-muted-foreground">
                  {r.risk_statement_fr}
                </p>
                {r.treatment?.active_case_id ? (
                  <Link
                    to={`/organizations/${orgId}/remediation/${r.treatment.active_case_id}`}
                    className="inline-flex items-center gap-1 text-xs font-medium underline-offset-2 hover:underline"
                  >
                    Cas de remédiation en cours
                    <ArrowRight className="size-3" aria-hidden="true" />
                  </Link>
                ) : (
                  <Badge variant="neutral">Sans traitement actif</Badge>
                )}
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ------------------------------------------------------------- trust panel

function TrustSection({ data }: { data: TrustPanelData }) {
  const { gate, review, chat, m6_benchmark } = data;
  return (
    <section className="space-y-5">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <ShieldCheck className="size-4" aria-hidden="true" />
          Panneau de confiance — « peut-on croire l'IA ? »
        </h2>
        <p className="text-sm text-muted-foreground">
          Méthodologie et garanties structurelles derrière chaque chiffre affiché.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="gap-3">
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Barrière de vérification</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            <dl className="space-y-1.5 text-muted-foreground">
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
          </CardContent>
        </Card>
        <Card className="gap-3">
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Revue humaine</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            <dl className="space-y-1.5 text-muted-foreground">
              <Row k="Décisions de revue" v={review.review_events} />
              <Row k="Approbations" v={review.approve_events} />
              <Row
                k="Taux d'intervention (modifier + remplacer)"
                v={review.intervention_rate_pct === null ? "—" : `${review.intervention_rate_pct}%`}
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
          </CardContent>
        </Card>
        <Card className="gap-3">
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Copilote (chat)</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            <dl className="space-y-1.5 text-muted-foreground">
              <Row k="Messages" v={chat.messages} />
              <Row k="Réponses citées" v={chat.answered} />
              <Row k="Abstentions" v={chat.abstained} />
              <Row k="Citations retirées par la vérification" v={chat.stripped_citation_count} />
            </dl>
            <p className="mt-3 text-xs text-muted-foreground">
              Portée : organisation entière (les messages ne sont pas liés à une évaluation).
            </p>
          </CardContent>
        </Card>
      </div>
      <details className="group rounded-xl border border-dashed bg-muted/30 open:bg-muted/50">
        <summary className="cursor-pointer list-none p-4 text-sm font-medium marker:hidden [&::-webkit-details-marker]:hidden">
          {String(m6_benchmark.label)}
          <span className="ml-2 text-xs font-normal text-muted-foreground group-open:hidden">
            — détails méthodologiques
          </span>
        </summary>
        <div className="px-4 pb-4">
          <p className="text-xs text-muted-foreground">
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
      </details>
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
