// Case-steering rail: owner, deadline and closure criterion.
// Split out of the 1 929-line RemediationCasePage — see that file.
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { caseStatusDisplay, classificationDisplay, MISSING, remediationScopeDisplay, verdictDisplay } from "@/lib/labels";
import { StatusLabel } from "@/components/status-label";
import {
  api,
  type RemediationCaseDetail,
} from "../../api";

/** Case-steering rail: human owner / deadline / closure criterion, editable
    under an optimistic revision check (a concurrent edit is a 409, never a
    silent overwrite). Absent values render honestly. */
export function PilotageRail({
  orgId,
  c,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  onChanged: () => void;
}) {
  const primary = c.finding_links.find((l) => l.is_primary) ?? c.finding_links[0];
  const [editing, setEditing] = useState(false);
  const [ownerRole, setOwnerRole] = useState(c.owner_role ?? "");
  const [dueDate, setDueDate] = useState(c.due_date ?? "");
  const [criterion, setCriterion] = useState(c.closure_criterion ?? "");
  const [editor, setEditor] = useState("");

  const save = useMutation({
    mutationFn: () =>
      api.updateCasePlanning(orgId, c.id, {
        expected_revision: c.planning_revision,
        owner_role: ownerRole.trim() || null,
        due_date: dueDate || null,
        closure_criterion: criterion.trim() || null,
        editor_label: editor.trim() || null,
      }),
    onSuccess: () => {
      setEditing(false);
      onChanged();
    },
  });

  return (
    <aside
      aria-label="Pilotage du cas"
      className="space-y-3 rounded-lg border bg-card p-4 lg:sticky lg:top-4"
    >
      <div className="flex items-center gap-2">
        <h2 className="font-mono text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
          Pilotage du cas
        </h2>
        {c.status !== "CLOSED" && (
          <button
            onClick={() => {
              setOwnerRole(c.owner_role ?? "");
              setDueDate(c.due_date ?? "");
              setCriterion(c.closure_criterion ?? "");
              setEditing((e) => !e);
            }}
            className="ml-auto min-h-9 rounded text-xs font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
          >
            {editing ? "Annuler" : "Modifier"}
          </button>
        )}
      </div>
      <dl className="space-y-2.5 text-sm">
        <RailRow label="Phase">
          <StatusLabel display={caseStatusDisplay(c.status)} />
        </RailRow>
        {primary && (
          <RailRow label="Écart principal">
            <span className="font-mono text-[13px] font-semibold text-primary">
              {primary.finding_requirement_id}
            </span>{" "}
            <span className="text-muted-foreground">
              {verdictDisplay(primary.finding_human_verdict).label}
            </span>
          </RailRow>
        )}
        {c.classification && (
          <RailRow label="Nature de l'écart">
            {classificationDisplay(c.classification).label}
          </RailRow>
        )}
        {c.scope && (
          <RailRow label="Périmètre">{remediationScopeDisplay(c.scope).label}</RailRow>
        )}
        {!editing && (
          <>
            <RailRow label="Responsable">
              {c.owner_role ?? (
                <span className="text-muted-foreground/80 italic">{MISSING.owner}</span>
              )}
            </RailRow>
            <RailRow label="Échéance">
              {c.due_date ? (
                new Date(c.due_date).toLocaleDateString("fr-FR")
              ) : (
                <span className="text-muted-foreground/80 italic">{MISSING.deadline}</span>
              )}
            </RailRow>
            <RailRow label="Critère de clôture">
              {c.closure_criterion ?? (
                <span className="text-muted-foreground/80 italic">{MISSING.value}</span>
              )}
            </RailRow>
          </>
        )}
        <RailRow label="Ouvert le">{new Date(c.created_at).toLocaleDateString("fr-FR")}</RailRow>
        <RailRow label="Mise à jour">
          {new Date(c.updated_at).toLocaleDateString("fr-FR")}
        </RailRow>
      </dl>

      {editing && (
        <form
          className="space-y-2 border-t pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <label className="block text-xs">
            <span className="text-muted-foreground">Responsable (rôle)</span>
            <input
              value={ownerRole}
              onChange={(e) => setOwnerRole(e.target.value)}
              className="mt-1 w-full rounded-md border border-input px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-xs">
            <span className="text-muted-foreground">Échéance du cas</span>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="mt-1 w-full rounded-md border border-input px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-xs">
            <span className="text-muted-foreground">Critère de clôture</span>
            <textarea
              value={criterion}
              onChange={(e) => setCriterion(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded-md border border-input px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-xs">
            <span className="text-muted-foreground">Votre nom (facultatif, non vérifié)</span>
            <input
              value={editor}
              onChange={(e) => setEditor(e.target.value)}
              className="mt-1 w-full rounded-md border border-input px-2 py-1.5 text-sm"
            />
          </label>
          <button
            type="submit"
            disabled={save.isPending}
            className="min-h-10 w-full rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Enregistrer le pilotage
          </button>
          {save.isError && (
            <p className="text-xs text-destructive">{(save.error as Error).message}</p>
          )}
        </form>
      )}

      {c.planning_updated_at && !editing && (
        <p className="border-t pt-2 text-xs leading-relaxed text-muted-foreground">
          Dernière mise à jour du pilotage le{" "}
          {new Date(c.planning_updated_at).toLocaleDateString("fr-FR")}
          {c.planning_editor_label && <> par {c.planning_editor_label} (non vérifié)</>}.
        </p>
      )}
    </aside>
  );
}

function RailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}
