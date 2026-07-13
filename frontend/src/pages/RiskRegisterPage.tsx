import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { MessageSquareText, ShieldAlert } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api, RiskRow, Severity, Verdict } from "../api";
import VerdictBadge from "../components/VerdictBadge";
import OpenRemediationCaseButton from "../components/OpenRemediationCaseButton";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/page-header";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

const SEVERITY_LABELS: Record<Severity, string> = {
  high: "Élevée",
  medium: "Moyenne",
  low: "Faible",
};

const SEVERITY_VARIANTS: Record<Severity, "danger" | "warning" | "success"> = {
  high: "danger",
  medium: "warning",
  low: "success",
};

export function SeverityBadge({
  severity,
  score,
}: {
  severity: Severity | null;
  score: number | null;
}) {
  if (severity === null) {
    return (
      <Badge
        variant="neutral"
        title="Poids de contrôle indisponible dans la politique de notation"
      >
        non évaluée
      </Badge>
    );
  }
  return (
    <Badge variant={SEVERITY_VARIANTS[severity]}>
      {SEVERITY_LABELS[severity]} ({score})
    </Badge>
  );
}

type SeverityFilter = "all" | Severity;
type SortKey = "severity" | "requirement" | "verdict";

const SORT_LABELS: Record<SortKey, string> = {
  severity: "Sévérité",
  requirement: "Exigence",
  verdict: "Verdict",
};

const SEVERITY_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };
const VERDICT_ORDER: Record<string, number> = { missing: 0, non_compliant: 1, partial: 2 };

function sortRows(rows: RiskRow[], key: SortKey): RiskRow[] {
  const sorted = [...rows];
  if (key === "severity") {
    sorted.sort(
      (a, b) =>
        (SEVERITY_ORDER[a.severity ?? "z"] ?? 3) - (SEVERITY_ORDER[b.severity ?? "z"] ?? 3) ||
        (b.severity_score ?? 0) - (a.severity_score ?? 0) ||
        a.requirement_id.localeCompare(b.requirement_id),
    );
  } else if (key === "requirement") {
    sorted.sort((a, b) =>
      a.requirement_id.localeCompare(b.requirement_id, "fr", { numeric: true }),
    );
  } else {
    sorted.sort(
      (a, b) =>
        (VERDICT_ORDER[a.human_verdict] ?? 9) - (VERDICT_ORDER[b.human_verdict] ?? 9) ||
        a.requirement_id.localeCompare(b.requirement_id),
    );
  }
  return sorted;
}

export default function RiskRegisterPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const [filter, setFilter] = useState<SeverityFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("severity");
  const isMobile = useIsMobile();

  const register = useQuery({
    queryKey: ["risk-register", orgId],
    queryFn: () => api.getRiskRegister(orgId!),
  });

  const rows = sortRows(
    (register.data?.rows ?? []).filter((r) => filter === "all" || r.severity === filter),
    sortKey,
  );

  return (
    <div className="space-y-8">
      <PageHeader
        title="Registre des écarts et des risques IA"
        description={
          <>
            Dérivé déterministe des constats confirmés par un humain (derniers verdicts) —
            sévérité = facteur d'écart × poids du contrôle
            {register.data && <> · politique {register.data.scope.scoring_policy_version}</>}.
          </>
        }
      />

      {register.data && (
        <div className="grid gap-3 sm:grid-cols-3">
          {(["high", "medium", "low"] as Severity[]).map((s) => (
            <div key={s} className="rounded-2xl border bg-card px-5 py-4 shadow-xs">
              <p className="text-[13px] font-medium text-muted-foreground">
                Sévérité {SEVERITY_LABELS[s].toLowerCase()}
              </p>
              <p className="mt-1 flex items-baseline gap-2 font-mono text-3xl font-semibold tracking-tight">
                {register.data.counts[s]}
                <span
                  aria-hidden
                  className={cn(
                    "inline-block h-2 w-2 rounded-full",
                    s === "high" ? "bg-destructive" : s === "medium" ? "bg-warning" : "bg-success",
                  )}
                />
              </p>
            </div>
          ))}
        </div>
      )}

      {register.data && (
        <div
          className="flex flex-wrap items-center gap-2"
          role="group"
          aria-label="Filtrer par sévérité"
        >
          {(["all", "high", "medium", "low"] as SeverityFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              aria-pressed={filter === f}
              className={cn(
                "min-h-9 rounded-full px-4 text-sm transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-ring",
                filter === f
                  ? "bg-primary font-medium text-primary-foreground shadow-sm"
                  : "border border-input text-muted-foreground hover:bg-muted",
              )}
            >
              {f === "all"
                ? `Tous (${register.data.rows.length})`
                : `${SEVERITY_LABELS[f]} (${register.data.counts[f]})`}
            </button>
          ))}
          <label className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
            Trier par
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="h-9 rounded-lg border border-input bg-card px-2 text-sm"
            >
              {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
                <option key={k} value={k}>
                  {SORT_LABELS[k]}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {register.isLoading && <p className="text-sm text-muted-foreground">Chargement…</p>}
      {register.error && (
        <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {(register.error as Error).message}
        </p>
      )}
      {register.data && rows.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed px-6 py-14 text-center">
          <span className="flex size-11 items-center justify-center rounded-full bg-muted">
            <ShieldAlert className="size-5 text-muted-foreground" aria-hidden="true" />
          </span>
          <p className="text-sm text-muted-foreground">
            Aucun écart confirmé dans ce périmètre.
          </p>
        </div>
      )}

      {rows.length > 0 &&
        (isMobile ? (
          <ul className="space-y-3">
            {rows.map((row) => (
              <RiskCard key={row.finding_id} orgId={orgId!} row={row} />
            ))}
          </ul>
        ) : (
          <div className="overflow-x-auto rounded-2xl border bg-card shadow-xs">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="border-b bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 font-medium">Exigence</th>
                  <th className="px-4 py-3 font-medium">Verdict</th>
                  <th className="px-4 py-3 font-medium">Sévérité</th>
                  <th className="px-4 py-3 font-medium">Énoncé de risque</th>
                  <th className="px-4 py-3 font-medium">Provenance</th>
                  <th className="px-4 py-3 font-medium">Traitement</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {rows.map((row) => (
                  <RegisterRow key={row.finding_id} orgId={orgId!} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}

/** Mobile presentation: one expandable card per risk — no horizontal scroll. */
function RiskCard({ orgId, row }: { orgId: string; row: RiskRow }) {
  return (
    <li className="rounded-2xl border bg-card p-4 shadow-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold">{row.requirement_id}</span>
        <SeverityBadge severity={row.severity} score={row.severity_score} />
        <VerdictBadge verdict={row.human_verdict as Verdict} />
      </div>
      <p className="mt-2 text-sm leading-relaxed text-foreground/90">{row.risk_statement_fr}</p>
      <details className="mt-2 text-xs text-muted-foreground">
        <summary className="min-h-9 cursor-pointer py-2 font-medium">Détails & traitement</summary>
        <div className="space-y-2 pb-1">
          <p>{row.domain_title_fr}</p>
          {!row.applicable && (
            <Badge variant="neutral" title={row.applicability_justification_fr ?? undefined}>
              déclaré non applicable (SoA)
            </Badge>
          )}
          {row.requirement_fr && <p>{row.requirement_fr}</p>}
          <Link
            to={`/organizations/${orgId}/assessments/${row.assessment_id}`}
            className="block font-medium text-foreground underline-offset-2 hover:underline"
          >
            Constat confirmé
            {row.reviewed_at && <> le {new Date(row.reviewed_at).toLocaleDateString("fr-FR")}</>}
          </Link>
          {row.treatment?.active_case_id ? (
            <Link
              to={`/organizations/${orgId}/remediation/${row.treatment.active_case_id}`}
              className="block font-medium text-foreground underline-offset-2 hover:underline"
            >
              Cas en cours ({row.treatment.active_case_status})
            </Link>
          ) : (
            <OpenRemediationCaseButton orgId={orgId} findingId={row.finding_id} />
          )}
        </div>
      </details>
    </li>
  );
}

function RegisterRow({ orgId, row }: { orgId: string; row: RiskRow }) {
  return (
    <tr className="align-top transition-colors hover:bg-muted/30">
      <td className="px-4 py-3.5">
        <span className="font-mono font-medium text-foreground">{row.requirement_id}</span>
        <p className="text-xs text-muted-foreground">{row.domain_title_fr}</p>
        {!row.applicable && (
          <Badge
            variant="neutral"
            className="mt-1"
            title={row.applicability_justification_fr ?? undefined}
          >
            déclaré non applicable (SoA)
          </Badge>
        )}
      </td>
      <td className="px-4 py-3.5">
        <VerdictBadge verdict={row.human_verdict as Verdict} />
      </td>
      <td className="px-4 py-3.5">
        <SeverityBadge severity={row.severity} score={row.severity_score} />
        {row.weight !== null && (
          <p className="mt-1 text-xs text-muted-foreground">
            écart {row.gap_factor} × poids {row.weight}
          </p>
        )}
      </td>
      <td className="max-w-md px-4 py-3.5 leading-relaxed text-foreground/90">
        {row.risk_statement_fr}
        {row.requirement_fr && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
              Exigence évaluée
            </summary>
            <p className="mt-1 text-xs text-muted-foreground">{row.requirement_fr}</p>
          </details>
        )}
      </td>
      <td className="px-4 py-3.5">
        <Link
          to={`/organizations/${orgId}/assessments/${row.assessment_id}`}
          className="text-xs font-medium underline-offset-2 hover:underline"
        >
          Constat confirmé
          {row.reviewed_at && <> le {new Date(row.reviewed_at).toLocaleDateString("fr-FR")}</>}
        </Link>
        <Link
          to={`/organizations/${orgId}/chat?finding=${row.finding_id}`}
          className="mt-1 flex items-center gap-1 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          <MessageSquareText className="size-3" aria-hidden="true" />
          Expliquer via le copilote
        </Link>
      </td>
      <td className="px-4 py-3.5">
        {row.treatment?.active_case_id ? (
          <div className="text-xs">
            <Link
              to={`/organizations/${orgId}/remediation/${row.treatment.active_case_id}`}
              className="font-medium underline-offset-2 hover:underline"
            >
              Cas en cours ({row.treatment.active_case_status})
            </Link>
            <p className="text-muted-foreground">
              {row.treatment.approved_action_count} action(s) approuvée(s) au plan actif
            </p>
          </div>
        ) : (
          <>
            <OpenRemediationCaseButton orgId={orgId} findingId={row.finding_id} />
            {row.treatment && row.treatment.closed_case_ids.length > 0 && (
              <p className="mt-1 text-xs text-muted-foreground">
                {row.treatment.closed_case_ids.length} cas clôturé(s)
              </p>
            )}
          </>
        )}
      </td>
    </tr>
  );
}
