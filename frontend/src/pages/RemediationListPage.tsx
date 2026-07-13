import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Search, Wrench } from "lucide-react";
import { api, type CaseStatus } from "../api";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";

export const CASE_STATUS_LABELS: Record<CaseStatus, string> = {
  TRIAGE: "Triage",
  TRIAGE_APPROVED: "Triage approuvé",
  PLANNING: "Plan en rédaction",
  PLAN_READY: "Plan prêt",
  IN_PROGRESS: "En cours",
  CLOSED: "Clôturé",
};

const STATUS_VARIANTS: Record<
  CaseStatus,
  "warning" | "outline" | "success" | "neutral"
> = {
  TRIAGE: "warning",
  TRIAGE_APPROVED: "outline",
  PLANNING: "outline",
  PLAN_READY: "outline",
  IN_PROGRESS: "success",
  CLOSED: "neutral",
};

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  return <Badge variant={STATUS_VARIANTS[status]}>{CASE_STATUS_LABELS[status]}</Badge>;
}

const SUMMARY_GROUPS: { label: string; statuses: CaseStatus[] }[] = [
  { label: "En triage", statuses: ["TRIAGE", "TRIAGE_APPROVED"] },
  { label: "En planification", statuses: ["PLANNING", "PLAN_READY"] },
  { label: "En exécution", statuses: ["IN_PROGRESS"] },
  { label: "Clôturés", statuses: ["CLOSED"] },
];

export default function RemediationListPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const [search, setSearch] = useState("");
  const cases = useQuery({
    queryKey: ["remediation-cases", orgId],
    queryFn: () => api.listCases(orgId!),
  });

  const filtered = useMemo(
    () =>
      (cases.data ?? []).filter((c) =>
        c.title.toLowerCase().includes(search.trim().toLowerCase()),
      ),
    [cases.data, search],
  );

  if (cases.isError) {
    return <p className="text-sm text-destructive">{(cases.error as Error).message}</p>;
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Cas de remédiation"
        description="Un cas s'ouvre depuis un constat confirmé comme écart dans l'espace de revue d'une évaluation."
      />

      {cases.data && cases.data.length > 0 && (
        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {SUMMARY_GROUPS.map(({ label, statuses }) => (
            <div key={label} className="rounded-2xl border bg-card px-5 py-4 shadow-xs">
              <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
              <dd className="mt-0.5 font-mono text-2xl font-semibold tracking-tight">
                {cases.data!.filter((c) => statuses.includes(c.status)).length}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {(cases.data?.length ?? 0) > 3 && (
        <div className="relative max-w-sm">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher un cas…"
            aria-label="Rechercher un cas de remédiation"
            className="h-10 rounded-full pl-9"
          />
        </div>
      )}

      {!cases.data ? (
        <p className="text-sm text-muted-foreground">Chargement…</p>
      ) : cases.data.length === 0 ? (
        <EmptyState
          icon={Wrench}
          title="Aucun cas de remédiation pour le moment."
          description="Ouvrez un cas depuis un constat confirmé comme écart dans l'espace de revue."
        />
      ) : (
        <ul className="space-y-3">
          {filtered.map((c) => (
            <li key={c.id}>
              <Link
                to={`/organizations/${orgId}/remediation/${c.id}`}
                className="group flex flex-wrap items-center gap-3 rounded-2xl border bg-card p-5 shadow-xs transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_12px_30px_-14px_rgba(0,0,0,0.18)] focus-visible:outline-2 focus-visible:outline-ring"
              >
                <span className="text-sm font-semibold">{c.title}</span>
                <CaseStatusBadge status={c.status} />
                <span className="text-xs text-muted-foreground">
                  {c.finding_links.length} constat(s) lié(s) · créé le{" "}
                  {new Date(c.created_at).toLocaleDateString("fr-FR")}
                </span>
                <span className="ml-auto flex size-8 shrink-0 items-center justify-center rounded-full border bg-background transition-transform duration-300 group-hover:translate-x-0.5">
                  <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
