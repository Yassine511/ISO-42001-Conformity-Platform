import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type CaseStatus } from "../api";

export const CASE_STATUS_LABELS: Record<CaseStatus, string> = {
  TRIAGE: "Triage",
  TRIAGE_APPROVED: "Triage approuvé",
  PLANNING: "Plan en rédaction",
  PLAN_READY: "Plan prêt",
  IN_PROGRESS: "En cours",
  CLOSED: "Clôturé",
};

const STATUS_STYLES: Record<CaseStatus, string> = {
  TRIAGE: "bg-amber-100 text-amber-800",
  TRIAGE_APPROVED: "bg-sky-100 text-sky-800",
  PLANNING: "bg-indigo-100 text-indigo-800",
  PLAN_READY: "bg-indigo-100 text-indigo-800",
  IN_PROGRESS: "bg-emerald-100 text-emerald-800",
  CLOSED: "bg-slate-200 text-slate-600",
};

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}
    >
      {CASE_STATUS_LABELS[status]}
    </span>
  );
}

export default function RemediationListPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const cases = useQuery({
    queryKey: ["remediation-cases", orgId],
    queryFn: () => api.listCases(orgId!),
  });

  if (cases.isError) {
    return <p className="text-sm text-red-600">{(cases.error as Error).message}</p>;
  }

  return (
    <div className="space-y-6">
      <Link to={`/organizations/${orgId}`} className="text-sm text-indigo-600 hover:underline">
        ← Organisation
      </Link>
      <div>
        <h1 className="text-xl font-semibold">Cas de remédiation</h1>
        <p className="mt-1 text-sm text-slate-500">
          Un cas s'ouvre depuis un constat confirmé comme écart dans l'espace de revue
          d'une évaluation.
        </p>
      </div>
      {!cases.data ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : cases.data.length === 0 ? (
        <p className="text-sm text-slate-500">Aucun cas de remédiation pour le moment.</p>
      ) : (
        <ul className="space-y-2">
          {cases.data.map((c) => (
            <li key={c.id}>
              <Link
                to={`/organizations/${orgId}/remediation/${c.id}`}
                className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 hover:border-indigo-300"
              >
                <span className="font-medium">{c.title}</span>
                <CaseStatusBadge status={c.status} />
                <span className="text-xs text-slate-500">
                  {c.finding_links.length} constat(s) lié(s) · créé le{" "}
                  {new Date(c.created_at).toLocaleDateString("fr-FR")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
