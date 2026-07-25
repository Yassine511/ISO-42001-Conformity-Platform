// Triage: the LLM qualifies, the human approves an explicit draft.
// Split out of the 1 929-line RemediationCasePage — see that file.
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { abstainReasonDisplay, classificationDisplay, remediationScopeDisplay } from "@/lib/labels";
import { TechnicalDisclosure } from "@/components/technical-disclosure";
import {
  api,
  type Classification,
  type RemediationCaseDetail,
  type RemediationScope,
  type TriageDraft,
} from "../../api";
import { isOperationalAbort, ErrorText } from "./shared";

const CLASSIFICATION_OPTIONS: Classification[] = [
  "evidence_gap",
  "observation",
  "improvement_opportunity",
  "nonconformity",
];
const SCOPE_OPTIONS: RemediationScope[] = [
  "local",
  "related_requirements",
  "organization_wide",
];

// ---------------------------------------------------------------- triage

export function TriagePanel({
  orgId,
  c,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  onChanged: () => void;
}) {
  const latest: TriageDraft | null = c.triage_drafts[c.triage_drafts.length - 1] ?? null;
  const [classification, setClassification] = useState<Classification | "">("");
  const [scope, setScope] = useState<RemediationScope | "">("");
  const [correctionNote, setCorrectionNote] = useState("");
  const [scopeRationale, setScopeRationale] = useState("");

  const approve = useMutation({
    mutationFn: () =>
      api.approveTriage(orgId, c.id, {
        triage_draft_id: latest!.id,
        ...(classification ? { classification } : {}),
        ...(scope ? { scope } : {}),
        ...(correctionNote.trim() ? { correction_note: correctionNote.trim() } : {}),
        ...(scopeRationale.trim() ? { scope_rationale: scopeRationale.trim() } : {}),
      }),
    onSuccess: onChanged,
  });
  const redraft = useMutation({
    mutationFn: () => api.redraftTriage(orgId, c.id),
    onSuccess: onChanged,
  });
  const reopen = useMutation({
    mutationFn: () => api.reopenTriage(orgId, c.id),
    onSuccess: onChanged,
  });

  const approved = c.triage_approved_at !== null;
  const abstained = latest?.status === "ABSTAINED";

  const body = approved ? (
    <dl className="grid gap-2 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-xs text-muted-foreground">Qualification</dt>
        <dd>{classificationDisplay(c.classification).label}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Périmètre</dt>
        <dd>{remediationScopeDisplay(c.scope).label}</dd>
      </div>
      {c.correction_note && (
        <div className="sm:col-span-2">
          <dt className="text-xs text-muted-foreground">Correction immédiate</dt>
          <dd>{c.correction_note}</dd>
        </div>
      )}
      <div className="sm:col-span-2">
        <dt className="text-xs text-muted-foreground">Justification du périmètre</dt>
        <dd>{c.scope_rationale}</dd>
      </div>
    </dl>
  ) : latest ? (
    <div className="space-y-3">
      <div
        className={`rounded-lg border p-4 text-sm ${
          abstained
            ? isOperationalAbort(latest.abstain_reason)
              ? "border-border bg-muted/50"
              : "border-warning/40 bg-warning/10"
            : "border-primary/25 bg-accent"
        }`}
      >
        <p className="text-xs font-semibold text-muted-foreground">
          Proposition IA (brouillon n°{latest.sequence}) — à valider par un humain
        </p>
        {abstained ? (
          <p className="mt-2">
            L'agent s'est abstenu — {abstainReasonDisplay(latest.abstain_reason).label}.
            Renseignez le triage vous-même ci-dessous, ou relancez la proposition.
          </p>
        ) : (
          <dl className="mt-2 grid gap-2 sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground">Qualification proposée</dt>
              <dd>{classificationDisplay(latest.ai_classification).label}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Périmètre proposé</dt>
              <dd>{remediationScopeDisplay(latest.ai_scope).label}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs text-muted-foreground">Correction immédiate</dt>
              <dd>{latest.ai_correction_note}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs text-muted-foreground">Justification</dt>
              <dd>{latest.ai_scope_rationale}</dd>
            </div>
          </dl>
        )}
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">
            Qualification {abstained ? "(requise)" : "(laisser vide pour accepter)"}
          </span>
          <select
            value={classification}
            onChange={(e) => setClassification(e.target.value as Classification | "")}
            className="mt-1 w-full rounded-md border border-input px-2 py-1.5"
          >
            <option value="">— proposition IA —</option>
            {CLASSIFICATION_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {classificationDisplay(v).label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">
            Périmètre {abstained ? "(requis)" : "(laisser vide pour accepter)"}
          </span>
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as RemediationScope | "")}
            className="mt-1 w-full rounded-md border border-input px-2 py-1.5"
          >
            <option value="">— proposition IA —</option>
            {SCOPE_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {remediationScopeDisplay(v).label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm sm:col-span-2">
          <span className="text-xs text-muted-foreground">Correction immédiate (surcharge)</span>
          <textarea
            value={correctionNote}
            onChange={(e) => setCorrectionNote(e.target.value)}
            rows={2}
            className="mt-1 w-full rounded-md border border-input px-2 py-1.5"
          />
        </label>
        <label className="text-sm sm:col-span-2">
          <span className="text-xs text-muted-foreground">
            Justification du périmètre {abstained ? "(requise)" : "(surcharge)"}
          </span>
          <textarea
            value={scopeRationale}
            onChange={(e) => setScopeRationale(e.target.value)}
            rows={2}
            className="mt-1 w-full rounded-md border border-input px-2 py-1.5"
          />
        </label>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => approve.mutate()}
          disabled={approve.isPending}
          className="min-h-10 rounded-md bg-success px-3 py-1.5 text-sm font-medium text-success-foreground hover:bg-success/90 disabled:opacity-50"
        >
          Approuver le triage
        </button>
        <button
          onClick={() => redraft.mutate()}
          disabled={redraft.isPending}
          className="min-h-10 rounded-md border border-primary/40 px-3 py-1.5 text-sm text-primary hover:bg-accent disabled:opacity-50"
        >
          Relancer la proposition IA
        </button>
      </div>
    </div>
  ) : (
    <p className="text-sm text-muted-foreground">Aucune proposition de triage.</p>
  );

  const extras = (
    <>
      {c.triage_drafts.length > 1 && (
        <TechnicalDisclosure summary={`Historique des propositions (${c.triage_drafts.length})`}>
          <ul className="space-y-1">
            {c.triage_drafts.map((d) => (
              <li key={d.id} className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span className="font-mono">n°{d.sequence}</span>
                <span>
                  {d.status === "VERIFIED"
                    ? "vérifiée"
                    : `abstention — ${abstainReasonDisplay(d.abstain_reason).label}`}
                </span>
                {d.abstain_reason && <span className="font-mono">({d.abstain_reason})</span>}
                {d.id === c.approved_triage_draft_id && (
                  <span className="text-success">approuvée</span>
                )}
                <span className="text-muted-foreground/80">
                  {new Date(d.created_at).toLocaleString("fr-FR")}
                </span>
              </li>
            ))}
          </ul>
        </TechnicalDisclosure>
      )}
      {approved && ["TRIAGE_APPROVED", "PLAN_READY"].includes(c.status) && (
        <button
          onClick={() => reopen.mutate()}
          disabled={reopen.isPending}
          className="min-h-10 rounded-md border border-warning/50 px-3 py-1.5 text-sm text-warning-foreground hover:bg-warning/10 disabled:opacity-50 dark:text-warning"
        >
          Rouvrir le triage
        </button>
      )}
      <ErrorText error={approve.error || redraft.error || reopen.error} />
    </>
  );

  // once approved, triage collapses out of the way (spec §8.9)
  if (approved) {
    return (
      <details id="triage" className="group rounded-lg border bg-card">
        <summary className="flex min-h-12 cursor-pointer list-none flex-wrap items-center gap-3 px-5 py-3.5 select-none [&::-webkit-details-marker]:hidden">
          <h2 className="text-sm font-semibold">Triage</h2>
          <span className="rounded-full border border-success/25 bg-success/10 px-2 py-0.5 text-xs text-success">
            approuvé par un humain
          </span>
          <span className="ml-auto text-xs text-muted-foreground group-open:hidden">
            Afficher le détail
          </span>
        </summary>
        <div className="space-y-3 border-t px-5 py-4">
          {body}
          {extras}
        </div>
      </details>
    );
  }

  return (
    <section id="triage" className="space-y-3 rounded-lg border bg-card p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold">Triage</h2>
        <span className="rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-xs text-warning-foreground dark:text-warning">
          en attente d'approbation humaine
        </span>
      </div>
      {body}
      {extras}
    </section>
  );
}
