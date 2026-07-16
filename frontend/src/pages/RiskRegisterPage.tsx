import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { MessageSquareText, ShieldAlert } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api, RiskRow, Severity, Verdict } from "../api";
import { caseStatusDisplay, MISSING } from "@/lib/labels";
import VerdictBadge from "../components/VerdictBadge";
import OpenRemediationCaseButton from "../components/OpenRemediationCaseButton";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/page-header";
import { MetricLedger } from "@/components/metric-ledger";
import { NextActionPanel } from "@/components/next-action-panel";
import { TechnicalDisclosure } from "@/components/technical-disclosure";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import type { CaseStatus } from "../api";

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
      <Badge variant="neutral" title="Poids de contrôle indisponible dans la politique de notation">
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
    sorted.sort((a, b) => a.requirement_id.localeCompare(b.requirement_id, "fr", { numeric: true }));
  } else {
    sorted.sort(
      (a, b) =>
        (VERDICT_ORDER[a.human_verdict] ?? 9) - (VERDICT_ORDER[b.human_verdict] ?? 9) ||
        a.requirement_id.localeCompare(b.requirement_id),
    );
  }
  return sorted;
}

/** Risques à traiter — one row per latest human-confirmed gap in scope.
    Remediation treatment annotates a risk, never removes it; SoA
    applicability annotates the row, never filters it (spec §8.6). */
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

  const untreated = register.data
    ? sortRows(register.data.rows, "severity").find((r) => !r.treatment?.active_case_id)
    : undefined;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Risques à traiter"
        description="Chaque ligne est un écart confirmé par un humain sur les derniers verdicts. Un traitement en cours annote le risque — il ne le retire pas."
      />

      {register.data && register.data.rows.length > 0 && (
        <MetricLedger
          entries={[
            {
              label: "Écarts confirmés",
              value: register.data.rows.length,
              caption: "Toutes sévérités confondues, dans ce périmètre.",
            },
            {
              label: "Sévérité élevée",
              value: register.data.counts.high,
              caption: "À traiter en priorité.",
            },
            { label: "Sévérité moyenne", value: register.data.counts.medium },
            { label: "Sévérité faible", value: register.data.counts.low },
          ]}
        />
      )}

      {untreated && (
        <NextActionPanel
          tone="attention"
          title={`Traiter l'écart ${untreated.requirement_id} — le plus sévère sans traitement`}
          description="Ouvrez un cas de remédiation pour cet écart confirmé, ou documentez la décision de ne pas le traiter."
        >
          <OpenRemediationCaseButton orgId={orgId!} findingId={untreated.finding_id} />
        </NextActionPanel>
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
                "min-h-10 rounded-md px-4 text-sm transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-ring",
                filter === f
                  ? "bg-ink font-medium text-ink-foreground"
                  : "border border-input text-muted-foreground hover:bg-muted",
              )}
            >
              {f === "all"
                ? `Tous (${register.data.rows.length})`
                : `${SEVERITY_LABELS[f]} (${register.data.counts[f]})`}
            </button>
          ))}
          <label className="ml-auto flex min-h-10 items-center gap-2 text-sm text-muted-foreground">
            Trier par
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="h-9 rounded-md border border-input bg-card px-2 text-sm"
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
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-14 text-center">
          <span className="flex size-11 items-center justify-center rounded-full bg-muted">
            <ShieldAlert className="size-5 text-muted-foreground" aria-hidden="true" />
          </span>
          <p className="text-sm text-muted-foreground">Aucun écart confirmé dans ce périmètre.</p>
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
          <div className="overflow-x-auto rounded-lg border bg-card">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="border-b bg-muted/50 text-xs tracking-wide text-muted-foreground uppercase">
                <tr>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Exigence
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Pourquoi ce risque
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Sévérité
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Décision humaine
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Traitement
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Responsable
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Échéance
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    <span className="sr-only">Action</span>
                  </th>
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

      <section className="space-y-3">
        <div className="rounded-lg border bg-card p-4 text-sm leading-relaxed text-muted-foreground">
          <p className="font-medium text-foreground">Pourquoi ces risques apparaissent</p>
          <p className="mt-1">
            Un risque apparaît quand un humain a confirmé qu'une exigence est partiellement
            conforme, non conforme ou sans preuve. La ligne reste visible tant que la décision
            humaine tient — clôturer un cas de remédiation annote la ligne mais ne la retire pas ;
            seule une nouvelle évaluation confirmée peut changer le verdict.
          </p>
        </div>
        <TechnicalDisclosure summary="Comment la sévérité est calculée">
          <p>
            Sévérité = facteur d'écart (1 partiel, 2 non conforme, 3 preuve absente) × poids du
            contrôle (1 à 3, fixé par la politique de notation
            {register.data ? ` ${register.data.scope.scoring_policy_version}` : ""}). Résultat 1–2 :
            faible ; 3–4 : moyenne ; 6–9 : élevée. Un contrôle absent de la politique de notation
            est affiché « non évaluée », jamais doté d'un poids par défaut.
          </p>
        </TechnicalDisclosure>
      </section>
    </div>
  );
}

/** Mobile presentation: one expandable card per risk — no horizontal scroll. */
function RiskCard({ orgId, row }: { orgId: string; row: RiskRow }) {
  return (
    <li className="rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold">{row.requirement_id}</span>
        <SeverityBadge severity={row.severity} score={row.severity_score} />
        <VerdictBadge verdict={row.human_verdict as Verdict} />
      </div>
      <p className="mt-2 text-sm leading-relaxed text-foreground/90">{row.risk_statement_fr}</p>
      <details className="mt-2 text-xs text-muted-foreground">
        <summary className="min-h-10 cursor-pointer py-2 font-medium select-none [&::-webkit-details-marker]:hidden">
          Détails & traitement
        </summary>
        <div className="space-y-2 pb-1">
          <p>{row.domain_title_fr}</p>
          {!row.applicable && (
            <Badge variant="neutral" title={row.applicability_justification_fr ?? undefined}>
              déclaré non applicable (SoA)
            </Badge>
          )}
          {row.requirement_fr && <p>{row.requirement_fr}</p>}
          <p>
            Responsable : <span className="italic">{MISSING.owner}</span> · Échéance :{" "}
            <span className="italic">{MISSING.deadline}</span>
          </p>
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
              Cas en cours — {caseStatusDisplay(row.treatment.active_case_status as CaseStatus).label}
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
      <td className="max-w-md px-4 py-3.5 leading-relaxed text-foreground/90">
        {row.risk_statement_fr}
        {row.requirement_fr && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
              Exigence évaluée
            </summary>
            <p className="mt-1 text-xs text-muted-foreground">{row.requirement_fr}</p>
          </details>
        )}
      </td>
      <td className="px-4 py-3.5">
        <SeverityBadge severity={row.severity} score={row.severity_score} />
      </td>
      <td className="px-4 py-3.5">
        <VerdictBadge verdict={row.human_verdict as Verdict} />
        <Link
          to={`/organizations/${orgId}/assessments/${row.assessment_id}`}
          className="mt-1 block text-xs font-medium underline-offset-2 hover:underline"
        >
          Constat confirmé
          {row.reviewed_at && <> le {new Date(row.reviewed_at).toLocaleDateString("fr-FR")}</>}
        </Link>
      </td>
      <td className="px-4 py-3.5">
        {row.treatment?.active_case_id ? (
          <div className="text-xs">
            <Link
              to={`/organizations/${orgId}/remediation/${row.treatment.active_case_id}`}
              className="font-medium underline-offset-2 hover:underline"
            >
              Cas en cours —{" "}
              {caseStatusDisplay(row.treatment.active_case_status as CaseStatus).label}
            </Link>
            <p className="text-muted-foreground">
              {row.treatment.approved_action_count} action(s) approuvée(s) au plan actif
            </p>
          </div>
        ) : row.treatment && row.treatment.closed_case_ids.length > 0 ? (
          <div className="text-xs">
            <Badge variant="neutral">Traitement clôturé</Badge>
            <p className="mt-1 text-muted-foreground">
              {row.treatment.closed_case_ids.length} cas clôturé(s) — le risque reste affiché tant
              que le verdict tient.
            </p>
          </div>
        ) : (
          <Badge variant="warning">Sans traitement</Badge>
        )}
      </td>
      <td className="px-4 py-3.5 text-xs text-muted-foreground/80 italic">{MISSING.owner}</td>
      <td className="px-4 py-3.5 text-xs text-muted-foreground/80 italic">{MISSING.deadline}</td>
      <td className="px-4 py-3.5">
        {!row.treatment?.active_case_id && (
          <OpenRemediationCaseButton orgId={orgId} findingId={row.finding_id} />
        )}
        <Link
          to={`/organizations/${orgId}/chat?finding=${row.finding_id}`}
          className="mt-1 flex items-center gap-1 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          <MessageSquareText className="size-3" aria-hidden="true" />
          Expliquer via le copilote
        </Link>
      </td>
    </tr>
  );
}
