import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Wrench } from "lucide-react";
import { api, type CaseStatus, type RemediationCase } from "../api";
import {
  abstainReasonDisplay,
  caseDisplayTitle,
  caseStatusDisplay,
  MISSING,
  nextActionLabel,
  verdictDisplay,
} from "@/lib/labels";
import { FieldState } from "@/components/field-state";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { MetricLedger } from "@/components/metric-ledger";
import { NextActionPanel } from "@/components/next-action-panel";
import { StatusLabel } from "@/components/status-label";
import { TableToolbar } from "@/components/table-toolbar";
import { TechnicalDisclosure } from "@/components/technical-disclosure";

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  return <StatusLabel display={caseStatusDisplay(status)} />;
}

const SUMMARY_GROUPS: { label: string; statuses: CaseStatus[] }[] = [
  { label: "En qualification", statuses: ["TRIAGE", "TRIAGE_APPROVED"] },
  { label: "En planification", statuses: ["PLANNING", "PLAN_READY"] },
  { label: "En exécution", statuses: ["IN_PROGRESS"] },
  { label: "Clôturés", statuses: ["CLOSED"] },
];

// which open case most needs a human right now (list-level heuristics)
const ATTENTION_ORDER: CaseStatus[] = [
  "PLAN_READY",
  "TRIAGE",
  "TRIAGE_APPROVED",
  "IN_PROGRESS",
  "PLANNING",
];

/** Gestion des remédiations — lifecycle ledger, dominant next action and the
    operational case table (spec §8.8). Owner / deadline / closure criterion
    are honestly « non renseigné » until the backend carries them. */
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
        caseDisplayTitle(c).toLowerCase().includes(search.trim().toLowerCase()),
      ),
    [cases.data, search],
  );

  const attention = useMemo(() => {
    for (const status of ATTENTION_ORDER) {
      const hit = (cases.data ?? []).find((c) => c.status === status);
      if (hit) return hit;
    }
    return undefined;
  }, [cases.data]);

  if (cases.isError) {
    return <p className="text-sm text-destructive">{(cases.error as Error).message}</p>;
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Gestion des remédiations"
        description="Un cas s'ouvre depuis un écart confirmé par un humain, puis avance : qualification, plan, actions, vérification d'efficacité, clôture."
      />

      {cases.data && cases.data.length > 0 && (
        <MetricLedger
          entries={SUMMARY_GROUPS.map(({ label, statuses }) => ({
            label,
            value: cases.data!.filter((c) => statuses.includes(c.status)).length,
          }))}
        />
      )}

      {attention && (
        <NextActionPanel
          tone={attention.workflow?.blocker_reason ? "attention" : "default"}
          title={caseDisplayTitle(attention)}
          description={
            attention.workflow?.blocker_reason
              ? `Plan non vérifié — ${abstainReasonDisplay(attention.workflow.blocker_reason).label.toLowerCase()}. Une nouvelle rédaction est requise.`
              : `Phase actuelle : ${caseStatusDisplay(attention.status).label.toLowerCase()}. Prochaine action : ${nextActionLabel(attention.workflow?.next_action_key).toLowerCase()}.`
          }
          actionLabel="Ouvrir le cas"
          actionTo={`/organizations/${orgId}/remediation/${attention.id}`}
        />
      )}

      {(cases.data?.length ?? 0) > 3 && (
        <TableToolbar
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder="Rechercher un cas…"
          searchLabel="Rechercher un cas de remédiation"
        />
      )}

      {!cases.data ? (
        <p className="text-sm text-muted-foreground">Chargement…</p>
      ) : cases.data.length === 0 ? (
        <EmptyState
          icon={Wrench}
          title="Aucun cas de remédiation pour le moment."
          description="Ouvrez un cas depuis un écart confirmé, dans la revue humaine ou le registre des risques."
        />
      ) : (
        <>
          {/* desktop operational table */}
          <div className="hidden overflow-x-auto rounded-lg border bg-card md:block">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="border-b bg-muted/50 text-xs tracking-wide text-muted-foreground uppercase">
                <tr>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Cas
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Écart
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Phase
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Prochaine action
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Responsable
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Échéance
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Critère de clôture
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Mise à jour
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    <span className="sr-only">Action</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {filtered.map((c) => (
                  <CaseTableRow key={c.id} orgId={orgId!} c={c} />
                ))}
              </tbody>
            </table>
          </div>

          {/* mobile record cards */}
          <ul className="space-y-3 md:hidden">
            {filtered.map((c) => (
              <li key={c.id}>
                <Link
                  to={`/organizations/${orgId}/remediation/${c.id}`}
                  className="block rounded-lg border bg-card p-4 focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">{caseDisplayTitle(c)}</span>
                    <CaseStatusBadge status={c.status} />
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Prochaine action : {nextActionLabel(c.workflow?.next_action_key)}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Responsable : <FieldState value={c.owner_role} kind="owner" /> · Échéance :{" "}
                    <FieldState
                      value={c.due_date ? new Date(c.due_date).toLocaleDateString("fr-FR") : null}
                      kind="deadline"
                    />
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}

      <TechnicalDisclosure summary="Comment fonctionne le cycle de remédiation">
        <p>
          1. Qualification : l'IA propose une classification de l'écart, un humain la valide. 2.
          Plan : l'IA rédige des actions dont chaque citation et chaque exigence visée sont
          vérifiées par le code ; un plan non vérifié n'affiche aucune action. 3. Exécution : chaque
          action est validée, priorisée et suivie par un humain. 4. Vérification : l'efficacité se
          constate, idéalement via une réévaluation ciblée. 5. Clôture : décision humaine, avec
          note obligatoire — un cas clôturé reste consultable et peut être rouvert.
        </p>
      </TechnicalDisclosure>
    </div>
  );
}

function CaseTableRow({ orgId, c }: { orgId: string; c: RemediationCase }) {
  const primary = c.finding_links.find((l) => l.is_primary) ?? c.finding_links[0];
  return (
    <tr className="align-top transition-colors hover:bg-muted/30">
      <td className="max-w-xs px-4 py-3.5">
        <Link
          to={`/organizations/${orgId}/remediation/${c.id}`}
          className="font-medium underline-offset-2 hover:underline"
        >
          {caseDisplayTitle(c)}
        </Link>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {c.finding_links.length} constat{c.finding_links.length > 1 ? "s" : ""} lié
          {c.finding_links.length > 1 ? "s" : ""} · ouvert le{" "}
          {new Date(c.created_at).toLocaleDateString("fr-FR")}
        </p>
      </td>
      <td className="px-4 py-3.5">
        {primary ? (
          <>
            <span className="font-mono text-[13px] font-medium">
              {primary.finding_requirement_id}
            </span>
            <p className="text-xs text-muted-foreground">
              {verdictDisplay(primary.finding_human_verdict).label}
            </p>
          </>
        ) : (
          <span className="text-xs text-muted-foreground/80 italic">{MISSING.value}</span>
        )}
      </td>
      <td className="px-4 py-3.5">
        <CaseStatusBadge status={c.status} />
      </td>
      <td className="px-4 py-3.5 text-[13px]">
        {nextActionLabel(c.workflow?.next_action_key)}
        {c.workflow?.blocker_reason && (
          <p className="mt-0.5 text-xs text-warning-foreground dark:text-warning">
            Plan non vérifié — une nouvelle rédaction est requise.
          </p>
        )}
      </td>
      <td className="px-4 py-3.5 text-xs">
        <FieldState value={c.owner_role} kind="owner" />
      </td>
      <td className="px-4 py-3.5 text-xs">
        <FieldState
          value={c.due_date ? new Date(c.due_date).toLocaleDateString("fr-FR") : null}
          kind="deadline"
        />
      </td>
      <td className="max-w-48 px-4 py-3.5 text-xs">
        <FieldState value={c.closure_criterion} kind="value" className="line-clamp-2" />
      </td>
      <td className="px-4 py-3.5 text-xs whitespace-nowrap text-muted-foreground">
        {new Date(c.updated_at).toLocaleDateString("fr-FR")}
      </td>
      <td className="px-4 py-3.5 text-right">
        <Button asChild variant="ghost" size="sm">
          <Link to={`/organizations/${orgId}/remediation/${c.id}`}>
            Ouvrir
            <ArrowRight className="size-3.5" aria-hidden="true" />
          </Link>
        </Button>
      </td>
    </tr>
  );
}
