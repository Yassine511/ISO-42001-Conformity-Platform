import { useState } from "react";
import { Link, useParams } from "react-router-dom";
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
  high: "bg-red-100 text-red-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-emerald-100 text-emerald-700",
};

export function SeverityBadge({ severity, score }: { severity: Severity | null; score: number | null }) {
  if (severity === null) {
    return (
      <span
        className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500"
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

export default function RiskRegisterPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const [filter, setFilter] = useState<SeverityFilter>("all");

  const register = useQuery({
    queryKey: ["risk-register", orgId],
    queryFn: () => api.getRiskRegister(orgId!),
  });

  const rows = (register.data?.rows ?? []).filter(
    (r) => filter === "all" || r.severity === filter,
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link to={`/organizations/${orgId}`} className="text-sm text-indigo-600 hover:underline">
          ← Organisation
        </Link>
        <Link
          to={`/organizations/${orgId}/dashboard`}
          className="text-sm text-indigo-600 hover:underline"
        >
          📊 Tableau de bord
        </Link>
      </div>

      <div>
        <h1 className="text-xl font-semibold tracking-tight">Registre des écarts et des risques IA</h1>
        <p className="mt-1 text-sm text-slate-500">
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
                  ? "bg-indigo-600 text-white"
                  : "border border-slate-300 text-slate-600 hover:bg-slate-100"
              }`}
            >
              {f === "all"
                ? `Tous (${register.data.rows.length})`
                : `${SEVERITY_LABELS[f]} (${register.data.counts[f]})`}
            </button>
          ))}
        </div>
      )}

      {register.isLoading && <p className="text-sm text-slate-500">Chargement…</p>}
      {register.error && (
        <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {(register.error as Error).message}
        </p>
      )}
      {register.data && rows.length === 0 && (
        <p className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">
          Aucun écart confirmé dans ce périmètre.
        </p>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="border-b bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Exigence</th>
                <th className="px-4 py-3">Verdict</th>
                <th className="px-4 py-3">Sévérité</th>
                <th className="px-4 py-3">Énoncé de risque</th>
                <th className="px-4 py-3">Provenance</th>
                <th className="px-4 py-3">Traitement</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
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
        <span className="font-medium text-slate-800">{row.requirement_id}</span>
        <p className="text-xs text-slate-500">{row.domain_title_fr}</p>
      </td>
      <td className="px-4 py-3">
        <VerdictBadge verdict={row.human_verdict as Verdict} />
      </td>
      <td className="px-4 py-3">
        <SeverityBadge severity={row.severity} score={row.severity_score} />
        {row.weight !== null && (
          <p className="mt-1 text-xs text-slate-500">
            écart {row.gap_factor} × poids {row.weight}
          </p>
        )}
      </td>
      <td className="max-w-md px-4 py-3 text-slate-700">
        {row.risk_statement_fr}
        {row.requirement_fr && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-indigo-600">Exigence évaluée</summary>
            <p className="mt-1 text-xs text-slate-500">{row.requirement_fr}</p>
          </details>
        )}
      </td>
      <td className="px-4 py-3">
        <Link
          to={`/organizations/${orgId}/assessments/${row.assessment_id}`}
          className="text-xs text-indigo-600 hover:underline"
        >
          Constat confirmé
          {row.reviewed_at && <> le {new Date(row.reviewed_at).toLocaleDateString("fr-FR")}</>}
        </Link>
      </td>
      <td className="px-4 py-3">
        {row.treatment?.active_case_id ? (
          <div className="text-xs">
            <Link
              to={`/organizations/${orgId}/remediation/${row.treatment.active_case_id}`}
              className="font-medium text-indigo-600 hover:underline"
            >
              Cas en cours ({row.treatment.active_case_status})
            </Link>
            <p className="text-slate-500">
              {row.treatment.approved_action_count} action(s) approuvée(s) au plan actif
            </p>
          </div>
        ) : (
          <>
            <OpenRemediationCaseButton orgId={orgId} findingId={row.finding_id} />
            {row.treatment && row.treatment.closed_case_ids.length > 0 && (
              <p className="mt-1 text-xs text-slate-500">
                {row.treatment.closed_case_ids.length} cas clôturé(s)
              </p>
            )}
          </>
        )}
      </td>
    </tr>
  );
}
