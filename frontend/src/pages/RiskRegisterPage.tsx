import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { MessageSquareText } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api, RiskRow, Severity, Verdict } from "../api";
import VerdictBadge from "../components/VerdictBadge";
import OpenRemediationCaseButton from "../components/OpenRemediationCaseButton";

const SEVERITY_LABELS: Record<Severity, string> = {
  high: "Élevée",
  medium: "Moyenne",
  low: "Faible",
};

const SEVERITY_CLASSES: Record<Severity, string> = {
  high: "bg-red-100 text-red-700 dark:bg-red-400/15 dark:text-red-300",
  medium: "bg-amber-100 dark:bg-amber-400/15 text-amber-700 dark:text-amber-300",
  low: "bg-emerald-100 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300",
};

export function SeverityBadge({ severity, score }: { severity: Severity | null; score: number | null }) {
  if (severity === null) {
    return (
      <span
        className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
        title="Poids de contrôle indisponible dans la politique de notation"
      >
        non évaluée
      </span>
    );
  }
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${SEVERITY_CLASSES[severity]}`}>
      {SEVERITY_LABELS[severity]} ({score})
    </span>
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

  const register = useQuery({
    queryKey: ["risk-register", orgId],
    queryFn: () => api.getRiskRegister(orgId!),
  });

  const rows = sortRows(
    (register.data?.rows ?? []).filter((r) => filter === "all" || r.severity === filter),
    sortKey,
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Registre des écarts et des risques IA
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Dérivé déterministe des constats confirmés par un humain (derniers verdicts) — sévérité ={" "}
          facteur d'écart × poids du contrôle
          {register.data && <> · politique {register.data.scope.scoring_policy_version}</>}.
        </p>
      </div>

      {register.data && (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filtrer par sévérité">
          {(["all", "high", "medium", "low"] as SeverityFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              aria-pressed={filter === f}
              className={`rounded-full px-3 py-1 text-sm ${
                filter === f
                  ? "bg-primary text-primary-foreground"
                  : "border border-input text-muted-foreground hover:bg-muted"
              }`}
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
              className="rounded-lg border border-input bg-card px-2 py-1 text-sm"
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
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {(register.error as Error).message}
        </p>
      )}
      {register.data && rows.length === 0 && (
        <p className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
          Aucun écart confirmé dans ce périmètre.
        </p>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="border-b bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Exigence</th>
                <th className="px-4 py-3">Verdict</th>
                <th className="px-4 py-3">Sévérité</th>
                <th className="px-4 py-3">Énoncé de risque</th>
                <th className="px-4 py-3">Provenance</th>
                <th className="px-4 py-3">Traitement</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {rows.map((row) => (
                <RegisterRow key={row.finding_id} orgId={orgId!} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RegisterRow({ orgId, row }: { orgId: string; row: RiskRow }) {
  return (
    <tr className="align-top">
      <td className="px-4 py-3">
        <span className="font-medium text-foreground">{row.requirement_id}</span>
        <p className="text-xs text-muted-foreground">{row.domain_title_fr}</p>
        {!row.applicable && (
          <span
            className="mt-1 inline-block rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
            title={row.applicability_justification_fr ?? undefined}
          >
            déclaré non applicable (SoA)
          </span>
        )}
      </td>
      <td className="px-4 py-3">
        <VerdictBadge verdict={row.human_verdict as Verdict} />
      </td>
      <td className="px-4 py-3">
        <SeverityBadge severity={row.severity} score={row.severity_score} />
        {row.weight !== null && (
          <p className="mt-1 text-xs text-muted-foreground">
            écart {row.gap_factor} × poids {row.weight}
          </p>
        )}
      </td>
      <td className="max-w-md px-4 py-3 text-foreground/90">
        {row.risk_statement_fr}
        {row.requirement_fr && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-primary">Exigence évaluée</summary>
            <p className="mt-1 text-xs text-muted-foreground">{row.requirement_fr}</p>
          </details>
        )}
      </td>
      <td className="px-4 py-3">
        <Link
          to={`/organizations/${orgId}/assessments/${row.assessment_id}`}
          className="text-xs text-primary hover:underline"
        >
          Constat confirmé
          {row.reviewed_at && <> le {new Date(row.reviewed_at).toLocaleDateString("fr-FR")}</>}
        </Link>
        <Link
          to={`/organizations/${orgId}/chat?finding=${row.finding_id}`}
          className="mt-1 flex items-center gap-1 text-xs text-primary hover:underline"
        >
          <MessageSquareText className="size-3" aria-hidden="true" />
          Expliquer via le copilote
        </Link>
      </td>
      <td className="px-4 py-3">
        {row.treatment?.active_case_id ? (
          <div className="text-xs">
            <Link
              to={`/organizations/${orgId}/remediation/${row.treatment.active_case_id}`}
              className="font-medium text-primary hover:underline"
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
