import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
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
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { MetricLedger } from "@/components/metric-ledger";
import { NextActionPanel } from "@/components/next-action-panel";
import { StatusLabel } from "@/components/status-label";
import { TableToolbar } from "@/components/table-toolbar";
import { TechnicalDisclosure } from "@/components/technical-disclosure";
import { cn } from "@/lib/utils";

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
        <ul className="grid gap-4 lg:grid-cols-2">
          {filtered.map((c) => (
            <CaseCard key={c.id} orgId={orgId!} c={c} />
          ))}
        </ul>
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

/** One case as a record card (design: 2-up grid). Keeps the operational
    fields the table carried — owner, deadline, closure criterion — so the
    card view loses no information. */
function CaseCard({ orgId, c }: { orgId: string; c: RemediationCase }) {
  const primary = c.finding_links.find((l) => l.is_primary) ?? c.finding_links[0];
  const closed = c.status === "CLOSED";
  return (
    <li>
      <Link
        to={`/organizations/${orgId}/remediation/${c.id}`}
        className={cn(
          "group flex h-full flex-col rounded-xl border bg-card p-5 transition-colors hover:border-ink/40 focus-visible:outline-2 focus-visible:outline-ring",
          closed && "bg-secondary/40",
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="font-mono text-[11px] text-muted-foreground uppercase">
              CAS-{c.id.slice(0, 6)}
            </span>
            <h3 className="mt-0.5 font-serif text-lg leading-tight font-medium">
              {caseDisplayTitle(c)}
            </h3>
          </div>
          <CaseStatusBadge status={c.status} />
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>Constat</span>
          {primary ? (
            <>
              <span className="font-mono font-semibold text-primary">
                {primary.finding_requirement_id}
              </span>
              <StatusLabel
                display={verdictDisplay(primary.finding_human_verdict)}
                dot={false}
                className="text-[10.5px]"
              />
            </>
          ) : (
            <span className="italic">{MISSING.value}</span>
          )}
        </div>

        <div className="mt-auto space-y-1 border-t pt-3 text-xs text-muted-foreground">
          <p className="pt-1">
            Prochaine action :{" "}
            <span className="font-medium text-foreground">
              {nextActionLabel(c.workflow?.next_action_key)}
            </span>
          </p>
          {c.workflow?.blocker_reason && (
            <p className="text-warning-foreground dark:text-warning">
              Plan non vérifié — une nouvelle rédaction est requise.
            </p>
          )}
          <p>
            Responsable : <FieldState value={c.owner_role} kind="owner" /> · Échéance :{" "}
            <FieldState
              value={c.due_date ? new Date(c.due_date).toLocaleDateString("fr-FR") : null}
              kind="deadline"
            />
          </p>
          <p className="flex items-center gap-1">
            <span className="truncate">
              Critère de clôture : <FieldState value={c.closure_criterion} kind="value" />
            </span>
            <ArrowRight
              className="ml-auto size-3.5 shrink-0 transition-transform group-hover:translate-x-0.5"
              aria-hidden="true"
            />
          </p>
        </div>
      </Link>
    </li>
  );
}
