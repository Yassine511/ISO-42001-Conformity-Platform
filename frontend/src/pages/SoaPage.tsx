import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { api, SoaControlRow } from "../api";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/page-header";
import { cn } from "@/lib/utils";

const STATUS_LABELS: Record<SoaControlRow["status"], string> = {
  conforme: "conforme",
  ecart: "écart",
  non_evalue: "non évalué",
};

const STATUS_VARIANTS: Record<SoaControlRow["status"], "success" | "warning" | "neutral"> = {
  conforme: "success",
  ecart: "warning",
  non_evalue: "neutral",
};

type SoaFilter = "all" | "ecart" | "non_applicable" | "explicit" | "non_evalue";

const FILTER_LABELS: Record<SoaFilter, string> = {
  all: "Tous",
  ecart: "Écarts",
  non_applicable: "Non applicables",
  explicit: "Décisions explicites",
  non_evalue: "Non évalués",
};

function matchesFilter(c: SoaControlRow, filter: SoaFilter): boolean {
  switch (filter) {
    case "ecart":
      return c.status === "ecart";
    case "non_applicable":
      return !c.applicable;
    case "explicit":
      return !c.is_default;
    case "non_evalue":
      return c.status === "non_evalue";
    default:
      return true;
  }
}

export default function SoaPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const [filter, setFilter] = useState<SoaFilter>("all");
  const soa = useQuery({
    queryKey: ["soa", orgId],
    queryFn: () => api.getSoa(orgId!),
  });

  const controls = soa.data?.controls ?? [];
  const summary = useMemo(
    () => ({
      applicable: controls.filter((c) => c.applicable).length,
      nonApplicable: controls.filter((c) => !c.applicable).length,
      evaluated: controls.filter((c) => c.status !== "non_evalue").length,
      gaps: controls.filter((c) => c.status === "ecart").length,
      explicit: controls.filter((c) => !c.is_default).length,
    }),
    [controls],
  );

  const byDomain = new Map<string, SoaControlRow[]>();
  for (const c of controls.filter((c) => matchesFilter(c, filter))) {
    byDomain.set(c.domain, [...(byDomain.get(c.domain) ?? []), c]);
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Déclaration d'applicabilité (Annexe A)"
        description="38 contrôles Annexe A. Par défaut, chaque contrôle est applicable — enregistrez une décision justifiée pour en déclarer un non applicable. L'applicabilité annote la déclaration : elle ne modifie jamais les scores ni le registre des risques. État d'applicabilité : organisation courante."
      />

      {soa.data && (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {[
            { k: "Applicables", v: summary.applicable },
            { k: "Non applicables", v: summary.nonApplicable },
            { k: "Évalués", v: summary.evaluated },
            { k: "Écarts", v: summary.gaps },
            { k: "Décisions explicites", v: summary.explicit },
          ].map(({ k, v }) => (
            <div key={k} className="rounded-2xl border bg-card px-4 py-3.5 shadow-xs">
              <dt className="text-xs font-medium text-muted-foreground">{k}</dt>
              <dd className="mt-0.5 font-mono text-2xl font-semibold tracking-tight">{v}</dd>
            </div>
          ))}
        </dl>
      )}

      {soa.data && (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrer les contrôles">
          {(Object.keys(FILTER_LABELS) as SoaFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              aria-pressed={filter === f}
              className={cn(
                "min-h-9 rounded-full px-4 text-xs font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-ring",
                filter === f
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "border border-input text-muted-foreground hover:bg-muted/60",
              )}
            >
              {FILTER_LABELS[f]}
            </button>
          ))}
        </div>
      )}

      {soa.isLoading && <p className="text-sm text-muted-foreground">Chargement…</p>}
      {soa.error && (
        <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {(soa.error as Error).message}
        </p>
      )}
      {soa.data && byDomain.size === 0 && (
        <p className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">
          Aucun contrôle ne correspond à ce filtre.
        </p>
      )}

      {[...byDomain.entries()].map(([domain, domainControls]) => (
        <details key={domain} className="group rounded-2xl border bg-card shadow-xs" open>
          <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 px-5 py-3.5 [&::-webkit-details-marker]:hidden">
            <ChevronDown
              className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-open:rotate-0 -rotate-90"
              aria-hidden="true"
            />
            <h2 className="text-sm font-semibold text-foreground/90">
              {domain} · {domainControls[0].domain_title_fr}
            </h2>
            <span className="ml-auto text-xs text-muted-foreground">
              {domainControls.length} contrôle{domainControls.length > 1 ? "s" : ""}
            </span>
          </summary>
          <ul className="divide-y border-t">
            {domainControls.map((c) => (
              <ControlRow key={c.control_id} orgId={orgId!} control={c} />
            ))}
          </ul>
        </details>
      ))}
    </div>
  );
}

function ControlRow({ orgId, control: c }: { orgId: string; control: SoaControlRow }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [applicable, setApplicable] = useState(c.applicable);
  const [justification, setJustification] = useState(c.justification_fr ?? "");
  const [showHistory, setShowHistory] = useState(false);

  const history = useQuery({
    queryKey: ["soa-history", orgId, c.control_id],
    queryFn: () => api.getSoaHistory(orgId, c.control_id),
    enabled: showHistory,
  });

  const save = useMutation({
    mutationFn: () =>
      api.putSoaControl(orgId, c.control_id, {
        applicable,
        justification_fr: justification.trim(),
      }),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["soa", orgId] });
      queryClient.invalidateQueries({ queryKey: ["soa-history", orgId, c.control_id] });
    },
  });

  return (
    <li className="px-5 py-4 text-sm transition-colors hover:bg-muted/30">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono font-medium text-foreground">{c.control_id}</span>
        <Badge variant={STATUS_VARIANTS[c.status]}>{STATUS_LABELS[c.status]}</Badge>
        <Badge variant={c.applicable ? "outline" : "neutral"}>
          {c.applicable ? "applicable" : "non applicable"}
        </Badge>
        {c.is_default && <span className="text-xs text-muted-foreground/80">(par défaut)</span>}
        <div className="ml-auto flex gap-3">
          {c.decision_count > 0 && (
            <button
              onClick={() => setShowHistory((s) => !s)}
              className="min-h-9 text-xs font-medium underline-offset-2 hover:underline"
            >
              Historique ({c.decision_count})
            </button>
          )}
          <button
            onClick={() => setEditing((e) => !e)}
            className="min-h-9 text-xs font-medium underline-offset-2 hover:underline"
          >
            {editing ? "Annuler" : "Modifier"}
          </button>
        </div>
      </div>
      {c.requirement_fr && (
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{c.requirement_fr}</p>
      )}
      {c.justification_fr && !editing && (
        <p className="mt-1 text-xs text-muted-foreground">
          Justification : {c.justification_fr}
        </p>
      )}
      {c.finding_id && c.assessment_id && (
        <Link
          to={`/organizations/${orgId}/assessments/${c.assessment_id}`}
          className="mt-1 inline-block text-xs font-medium underline-offset-2 hover:underline"
        >
          Constat associé
        </Link>
      )}

      {editing && (
        <form
          className="mt-3 space-y-2 rounded-xl border bg-muted/30 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (justification.trim()) save.mutate();
          }}
        >
          <label className="flex min-h-9 items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={applicable}
              onChange={(e) => setApplicable(e.target.checked)}
            />
            Contrôle applicable à l'organisation
          </label>
          <label className="block">
            <span className="text-xs text-muted-foreground">Justification (requise)</span>
            <textarea
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded-lg border border-input bg-card px-2 py-1.5"
            />
          </label>
          <button
            type="submit"
            disabled={save.isPending || !justification.trim()}
            className="min-h-9 rounded-full bg-primary px-4 text-xs font-medium text-primary-foreground transition-transform active:scale-[0.98] disabled:opacity-50"
          >
            Enregistrer la décision
          </button>
          {save.isError && (
            <p className="text-xs text-destructive">{(save.error as Error).message}</p>
          )}
        </form>
      )}

      {showHistory && (
        <div className="mt-3 rounded-xl bg-muted/50 p-3">
          <h3 className="text-xs font-semibold text-muted-foreground">
            Historique des décisions
          </h3>
          <ol className="mt-1 space-y-1 text-xs text-muted-foreground">
            {(history.data ?? []).map((d) => (
              <li key={d.sequence}>
                n°{d.sequence} — {d.applicable ? "applicable" : "non applicable"} :{" "}
                {d.justification_fr}
                {d.editor_label && <> ({d.editor_label})</>} ·{" "}
                {new Date(d.created_at).toLocaleString("fr-FR")}
              </li>
            ))}
          </ol>
        </div>
      )}
    </li>
  );
}
