import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { api, SoaControlRow } from "../api";
import { soaEvalStatusDisplay } from "@/lib/labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { PageHeader } from "@/components/page-header";
import { MetricLedger } from "@/components/metric-ledger";
import { NextActionPanel } from "@/components/next-action-panel";
import { StatusLabel } from "@/components/status-label";
import { TableToolbar } from "@/components/table-toolbar";
import { cn } from "@/lib/utils";

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

/** Déclaration d'applicabilité — a parallel governance layer, never a
    workflow step: applicability annotates rows, it never changes conformity
    or risk scores (spec §8.7). Decisions are append-only and justified. */
export default function SoaPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const [filter, setFilter] = useState<SoaFilter>("all");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<SoaControlRow | null>(null);
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
      defaults: controls.filter((c) => c.is_default).length,
    }),
    [controls],
  );

  const q = search.trim().toLowerCase();
  const visible = controls.filter(
    (c) =>
      matchesFilter(c, filter) &&
      (!q ||
        c.control_id.toLowerCase().includes(q) ||
        (c.requirement_fr ?? "").toLowerCase().includes(q) ||
        c.domain_title_fr.toLowerCase().includes(q)),
  );
  const byDomain = new Map<string, SoaControlRow[]>();
  for (const c of visible) {
    byDomain.set(c.domain, [...(byDomain.get(c.domain) ?? []), c]);
  }
  // Collapsed domain groups by default; open them when the view is already
  // narrowed (filter/search) or small enough to scan.
  const groupsOpen = filter !== "all" || q !== "" || byDomain.size <= 3;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Déclaration d'applicabilité"
        description="38 contrôles de l'Annexe A. Par défaut, chaque contrôle est applicable — enregistrez une décision justifiée pour en déclarer un non applicable. L'applicabilité annote la déclaration : elle ne modifie jamais les scores ni le registre des risques. « Applicable » n'est pas « conforme » — la conformité vient des évaluations confirmées."
      />

      {soa.data && summary.defaults > 0 && (
        <NextActionPanel
          title={`${summary.defaults} contrôle${summary.defaults > 1 ? "s" : ""} rest${summary.defaults > 1 ? "ent" : "e"} à examiner`}
          description="Ces contrôles portent l'applicabilité par défaut. Confirmez-la ou déclarez-les non applicables, avec justification."
          onAction={() => setFilter("non_evalue")}
          actionLabel="Voir les contrôles sans décision"
          secondary={
            <Button variant="ghost" size="sm" onClick={() => setFilter("explicit")}>
              Décisions déjà prises
            </Button>
          }
        />
      )}

      {soa.data && (
        <MetricLedger
          entries={[
            {
              label: "Applicables",
              value: summary.applicable,
              caption: "Dont décisions par défaut — l'applicabilité ne note rien.",
            },
            { label: "Non applicables", value: summary.nonApplicable },
            {
              label: "Évalués",
              value: summary.evaluated,
              caption: "Contrôles couverts par une évaluation confirmée.",
            },
            { label: "Écarts confirmés", value: summary.gaps },
          ]}
        />
      )}

      {soa.data && (
        <TableToolbar
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder="Rechercher un contrôle…"
          searchLabel="Rechercher un contrôle"
        >
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filtrer les contrôles">
            {(Object.keys(FILTER_LABELS) as SoaFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                aria-pressed={filter === f}
                className={cn(
                  "min-h-9 rounded-md px-3 text-xs font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-ring",
                  filter === f
                    ? "bg-ink text-ink-foreground"
                    : "border border-input text-muted-foreground hover:bg-muted/60",
                )}
              >
                {FILTER_LABELS[f]}
              </button>
            ))}
          </div>
        </TableToolbar>
      )}

      {soa.isLoading && <p className="text-sm text-muted-foreground">Chargement…</p>}
      {soa.error && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {(soa.error as Error).message}
        </p>
      )}
      {soa.data && byDomain.size === 0 && (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          Aucun contrôle ne correspond à ce filtre.
        </p>
      )}

      {[...byDomain.entries()].map(([domain, domainControls]) => (
        <details
          key={domain}
          className="group rounded-lg border bg-card"
          open={groupsOpen || undefined}
        >
          <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 px-5 py-3.5 select-none [&::-webkit-details-marker]:hidden">
            <ChevronDown
              className="size-4 shrink-0 -rotate-90 text-muted-foreground transition-transform duration-150 group-open:rotate-0"
              aria-hidden="true"
            />
            <h2 className="text-sm font-semibold text-foreground/90">
              {domain} · {domainControls[0].domain_title_fr}
            </h2>
            <span className="ml-auto text-xs text-muted-foreground tabular-nums">
              {domainControls.length} contrôle{domainControls.length > 1 ? "s" : ""}
            </span>
          </summary>
          <ul className="divide-y border-t">
            {domainControls.map((c) => (
              <ControlRow
                key={c.control_id}
                orgId={orgId!}
                control={c}
                onEdit={() => setEditing(c)}
              />
            ))}
          </ul>
        </details>
      ))}

      <DecisionDrawer
        orgId={orgId!}
        control={editing}
        onClose={() => setEditing(null)}
      />
    </div>
  );
}

function ControlRow({
  orgId,
  control: c,
  onEdit,
}: {
  orgId: string;
  control: SoaControlRow;
  onEdit: () => void;
}) {
  const [showHistory, setShowHistory] = useState(false);

  const history = useQuery({
    queryKey: ["soa-history", orgId, c.control_id],
    queryFn: () => api.getSoaHistory(orgId, c.control_id),
    enabled: showHistory,
  });

  return (
    <li
      className={cn(
        "px-5 py-4 text-sm transition-colors hover:bg-muted/30",
        // controls still carrying the default applicability read as "à examiner"
        c.is_default && "bg-warning/[0.05]",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono font-semibold text-primary">{c.control_id}</span>
        <StatusLabel display={soaEvalStatusDisplay(c.status)} dot={false} />
        <Badge
          variant={c.applicable ? "success" : "outline"}
          className={cn(c.is_default && "border-dashed")}
        >
          {c.applicable ? "applicable" : "non applicable"}
        </Badge>
        {c.is_default && <span className="text-xs text-muted-foreground/80">(par défaut)</span>}
        {!c.is_default && c.updated_at && (
          <span className="text-xs text-muted-foreground/80">
            décidé le {new Date(c.updated_at).toLocaleDateString("fr-FR")}
            {c.editor_label && <> par {c.editor_label} (non vérifié)</>}
          </span>
        )}
        <div className="ml-auto flex gap-3">
          {c.decision_count > 0 && (
            <button
              onClick={() => setShowHistory((s) => !s)}
              className="min-h-10 text-xs font-medium underline-offset-2 hover:underline"
            >
              Historique ({c.decision_count})
            </button>
          )}
          <button
            onClick={onEdit}
            className="min-h-10 text-xs font-medium text-primary underline-offset-2 hover:underline"
          >
            Modifier
          </button>
        </div>
      </div>
      {c.requirement_fr && (
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{c.requirement_fr}</p>
      )}
      {c.justification_fr && (
        <p className="mt-1 text-xs text-muted-foreground">Justification : {c.justification_fr}</p>
      )}
      {c.finding_id && c.assessment_id && (
        <Link
          to={`/organizations/${orgId}/assessments/${c.assessment_id}`}
          className="mt-1 inline-block text-xs font-medium underline-offset-2 hover:underline"
        >
          Constat associé
        </Link>
      )}

      {showHistory && (
        <div className="mt-3 rounded-lg bg-muted/50 p-3">
          <h3 className="text-xs font-semibold text-muted-foreground">Historique des décisions</h3>
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

/** Right-side decision drawer (sheet on mobile). Justification is required
    before save; every decision appends to the immutable history. */
function DecisionDrawer({
  orgId,
  control,
  onClose,
}: {
  orgId: string;
  control: SoaControlRow | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [applicable, setApplicable] = useState(true);
  const [justification, setJustification] = useState("");
  const [editor, setEditor] = useState("");
  // reset the form whenever a different control opens
  const [lastId, setLastId] = useState<string | null>(null);
  if (control && control.control_id !== lastId) {
    setLastId(control.control_id);
    setApplicable(control.applicable);
    setJustification(control.justification_fr ?? "");
  }

  const save = useMutation({
    mutationFn: () =>
      api.putSoaControl(orgId, control!.control_id, {
        applicable,
        justification_fr: justification.trim(),
        ...(editor.trim() ? { editor_label: editor.trim() } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["soa", orgId] });
      queryClient.invalidateQueries({ queryKey: ["soa-history", orgId, control!.control_id] });
      onClose();
    },
  });

  return (
    <Sheet
      open={!!control}
      onOpenChange={(open) => {
        if (!open) {
          setLastId(null);
          onClose();
        }
      }}
    >
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        {control && (
          <>
            <SheetHeader>
              <SheetTitle>Décision d'applicabilité — {control.control_id}</SheetTitle>
              <SheetDescription>
                {control.requirement_fr ??
                  "Déclarez si ce contrôle s'applique à votre organisation."}
              </SheetDescription>
            </SheetHeader>
            <form
              className="space-y-4 px-4 pb-6"
              onSubmit={(e) => {
                e.preventDefault();
                if (justification.trim()) save.mutate();
              }}
            >
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <StatusLabel display={soaEvalStatusDisplay(control.status)} dot={false} />
                <span className="text-muted-foreground">
                  {control.is_default
                    ? "Applicabilité par défaut — aucune décision enregistrée."
                    : `Dernière décision : ${control.applicable ? "applicable" : "non applicable"}.`}
                </span>
              </div>
              <label className="flex min-h-10 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={applicable}
                  onChange={(e) => setApplicable(e.target.checked)}
                  className="accent-[var(--primary)]"
                />
                Contrôle applicable à l'organisation
              </label>
              <label className="block text-sm">
                <span className="font-medium">Justification (requise)</span>
                <textarea
                  value={justification}
                  onChange={(e) => setJustification(e.target.value)}
                  rows={3}
                  className="mt-1 w-full rounded-md border border-input bg-card px-2 py-1.5 text-sm"
                />
              </label>
              <label className="block text-sm">
                <span className="font-medium">Votre nom (facultatif, non vérifié)</span>
                <input
                  value={editor}
                  onChange={(e) => setEditor(e.target.value)}
                  className="mt-1 w-full rounded-md border border-input bg-card px-2 py-1.5 text-sm"
                />
              </label>
              <p className="text-xs text-muted-foreground">
                Cette décision s'ajoute à l'historique — rien n'est écrasé. Elle ne modifie ni les
                scores ni le registre des risques.
              </p>
              <div className="flex items-center gap-2">
                <Button type="submit" disabled={save.isPending || !justification.trim()}>
                  Enregistrer la décision
                </Button>
                <Button type="button" variant="ghost" onClick={onClose}>
                  Annuler
                </Button>
              </div>
              {save.isError && (
                <p className="text-xs text-destructive">{(save.error as Error).message}</p>
              )}
            </form>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
