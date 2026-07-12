import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, SoaControlRow } from "../api";

const STATUS_LABELS: Record<SoaControlRow["status"], string> = {
  conforme: "conforme",
  ecart: "écart",
  non_evalue: "non évalué",
};

const STATUS_CLASSES: Record<SoaControlRow["status"], string> = {
  conforme: "bg-emerald-100 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300",
  ecart: "bg-amber-100 dark:bg-amber-400/15 text-amber-700 dark:text-amber-300",
  non_evalue: "bg-muted text-muted-foreground",
};

export default function SoaPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const soa = useQuery({
    queryKey: ["soa", orgId],
    queryFn: () => api.getSoa(orgId!),
  });

  const byDomain = new Map<string, SoaControlRow[]>();
  for (const c of soa.data?.controls ?? []) {
    byDomain.set(c.domain, [...(byDomain.get(c.domain) ?? []), c]);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Déclaration d'applicabilité (Annexe A)
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          38 contrôles Annexe A. Par défaut, chaque contrôle est applicable — enregistrez une
          décision justifiée pour en déclarer un non applicable. L'applicabilité annote la
          déclaration : elle ne modifie jamais les scores ni le registre des risques. État
          d'applicabilité : organisation courante.
        </p>
      </div>

      {soa.isLoading && <p className="text-sm text-muted-foreground">Chargement…</p>}
      {soa.error && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {(soa.error as Error).message}
        </p>
      )}

      {[...byDomain.entries()].map(([domain, controls]) => (
        <section key={domain} className="space-y-2">
          <h2 className="text-sm font-semibold text-foreground/90">
            {domain} · {controls[0].domain_title_fr}
          </h2>
          <ul className="space-y-2">
            {controls.map((c) => (
              <ControlRow key={c.control_id} orgId={orgId!} control={c} />
            ))}
          </ul>
        </section>
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
    <li className="rounded-xl border bg-card p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-foreground">{c.control_id}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_CLASSES[c.status]}`}>
          {STATUS_LABELS[c.status]}
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            c.applicable ? "bg-accent text-accent-foreground" : "bg-muted text-muted-foreground"
          }`}
        >
          {c.applicable ? "applicable" : "non applicable"}
        </span>
        {c.is_default && <span className="text-xs text-muted-foreground/80">(par défaut)</span>}
        <div className="ml-auto flex gap-3">
          {c.decision_count > 0 && (
            <button
              onClick={() => setShowHistory((s) => !s)}
              className="text-xs text-primary hover:underline"
            >
              Historique ({c.decision_count})
            </button>
          )}
          <button
            onClick={() => setEditing((e) => !e)}
            className="text-xs text-primary hover:underline"
          >
            {editing ? "Annuler" : "Modifier"}
          </button>
        </div>
      </div>
      {c.requirement_fr && <p className="mt-1 text-xs text-muted-foreground">{c.requirement_fr}</p>}
      {c.justification_fr && !editing && (
        <p className="mt-1 text-xs text-muted-foreground">Justification : {c.justification_fr}</p>
      )}
      {c.finding_id && c.assessment_id && (
        <Link
          to={`/organizations/${orgId}/assessments/${c.assessment_id}`}
          className="mt-1 inline-block text-xs text-primary hover:underline"
        >
          Constat associé
        </Link>
      )}

      {editing && (
        <form
          className="mt-3 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (justification.trim()) save.mutate();
          }}
        >
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
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
              className="mt-1 w-full rounded-lg border border-input px-2 py-1"
            />
          </label>
          <button
            type="submit"
            disabled={save.isPending || !justification.trim()}
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
          >
            Enregistrer la décision
          </button>
          {save.isError && (
            <p className="text-xs text-destructive">{(save.error as Error).message}</p>
          )}
        </form>
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
