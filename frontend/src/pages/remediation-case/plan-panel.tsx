// The action plan and per-action human review.
// Split out of the 1 929-line RemediationCasePage — see that file.
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { abstainReasonDisplay, actionLifecycleDisplay, actionTypeLabel, effectivenessDisplay, MISSING, priorityDisplay } from "@/lib/labels";
import { SectionHeading } from "@/components/section-heading";
import { StatusLabel } from "@/components/status-label";
import { TechnicalDisclosure, TechnicalRow } from "@/components/technical-disclosure";
import {
  api,
  type RemediationAction,
  type RemediationCaseDetail,
  type RemediationPlan,
} from "../../api";
import { isOperationalAbort, ErrorText } from "./shared";
import { PatchPanel } from "./patch-panels";

// ------------------------------------------------------------------ plan

export function PlanPanel({
  orgId,
  c,
  activePlan,
  draftPlan,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  activePlan: RemediationPlan | null;
  draftPlan: { mutate: () => void; isPending: boolean; error: unknown };
  onChanged: () => void;
}) {
  const canDraft = ["TRIAGE_APPROVED", "PLAN_READY"].includes(c.status);

  return (
    <section id="plan" className="space-y-3 rounded-lg border bg-card p-5">
      <SectionHeading
        as="h2"
        title="Plan d'actions correctives"
        actions={
          canDraft ? (
            <button
              onClick={() => draftPlan.mutate()}
              disabled={draftPlan.isPending}
              className="min-h-10 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {draftPlan.isPending
                ? "Rédaction en cours…"
                : activePlan?.status === "ABSTAINED"
                  ? "Relancer la rédaction du plan"
                  : activePlan
                    ? "Redemander un plan"
                    : "Demander un plan à l'agent"}
            </button>
          ) : undefined
        }
      />

      {activePlan === null ? (
        <p className="text-sm text-muted-foreground">
          Aucun plan actif. {c.status === "TRIAGE" && "Approuvez d'abord le triage."}
        </p>
      ) : activePlan.status === "ABSTAINED" ? (
        <div
          className={`rounded-lg border p-4 text-sm ${
            isOperationalAbort(activePlan.abstain_reason)
              ? "border-border bg-muted/50"
              : "border-warning/40 bg-warning/10"
          }`}
        >
          <p className="font-medium">
            {isOperationalAbort(activePlan.abstain_reason)
              ? "Rédaction interrompue (incident technique)"
              : "Plan non vérifié"}
          </p>
          <p className="mt-1 text-muted-foreground">
            {abstainReasonDisplay(activePlan.abstain_reason).label}. Une nouvelle rédaction est
            requise — aucune action n'est issue de ce plan.
          </p>
          <TechnicalDisclosure summary="Détails techniques" className="mt-3">
            <TechnicalRow label="Motif brut" value={activePlan.abstain_reason ?? "—"} />
            <TechnicalRow label="Tentatives" value={String(activePlan.draft_attempts)} />
          </TechnicalDisclosure>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg border border-primary/25 bg-accent p-4 text-sm">
            <p className="text-xs font-semibold text-muted-foreground">
              Brouillon IA n°{activePlan.sequence} — chaque action requiert votre décision
            </p>
            <p className="mt-2">{activePlan.gap_restatement}</p>
            {activePlan.root_cause_hypotheses && (
              <details className="mt-2" open={activePlan.root_cause_hypotheses.length <= 3 || undefined}>
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground select-none [&::-webkit-details-marker]:hidden">
                  Afficher l'analyse complète ({activePlan.root_cause_hypotheses.length} hypothèse
                  {activePlan.root_cause_hypotheses.length > 1 ? "s" : ""})
                </summary>
                <ul className="mt-2 space-y-1">
                  {activePlan.root_cause_hypotheses.map((h) => (
                    <li key={h.label}>
                      <span className="font-mono text-xs">{h.label}</span> (hypothèse) :{" "}
                      {h.hypothesis}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
          <ul className="space-y-3">
            {activePlan.actions.map((a) => (
              <ActionCard key={a.id} orgId={orgId} c={c} a={a} onChanged={onChanged} />
            ))}
          </ul>
        </div>
      )}
      {c.plans.length > (activePlan ? 1 : 0) && (
        <TechnicalDisclosure summary={`Historique des plans (${c.plans.length})`}>
          <ul className="space-y-1">
            {c.plans.map((p) => (
              <li key={p.id} className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span className="font-mono">n°{p.sequence}</span>
                <span>
                  {p.status === "VERIFIED"
                    ? "vérifié"
                    : p.status === "SUPERSEDED"
                      ? "remplacé"
                      : `abstention — ${abstainReasonDisplay(p.abstain_reason).label}`}
                </span>
                {p.abstain_reason && <span className="font-mono">({p.abstain_reason})</span>}
                {p.status === "SUPERSEDED" && (
                  <span className="text-warning-foreground dark:text-warning">
                    {p.superseded_by_plan_id
                      ? `par le plan ${
                          c.plans.find((q) => q.id === p.superseded_by_plan_id)?.sequence ?? "?"
                        }`
                      : "(réouverture du triage)"}
                    {p.superseded_at
                      ? ` le ${new Date(p.superseded_at).toLocaleDateString("fr-FR")}`
                      : ""}
                  </span>
                )}
                {p.id === c.active_plan_id && <span className="text-success">actif</span>}
              </li>
            ))}
          </ul>
        </TechnicalDisclosure>
      )}
      <ErrorText error={draftPlan.error} />
    </section>
  );
}

function ActionCard({
  orgId,
  c,
  a,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  a: RemediationAction;
  onChanged: () => void;
}) {
  const [reviewAction, setReviewAction] = useState<"approve" | "edit" | "reject" | null>(null);
  // Pre-selected once at mount from the severity-derived suggestion (an
  // already-recorded human priority wins over it); useState's initializer
  // never re-runs, so a background refetch cannot overwrite a value the
  // human already changed. The decision itself stays mandatory and human.
  const [priority, setPriority] = useState<"haute" | "normale" | "basse">(
    a.priority ?? a.suggested_priority ?? "normale",
  );
  const [description, setDescription] = useState("");
  // human-set deadline (never LLM-proposed); prefilled with the recorded one
  const [actionDueDate, setActionDueDate] = useState(a.due_date ?? "");
  // prefilled with the CURRENT effective scope: an untouched field re-submits
  // the human decision, never silently reverts to the AI proposal
  const [scopeIds, setScopeIds] = useState(
    (a.effective_requirement_ids?.length
      ? a.effective_requirement_ids
      : a.ai_impacted_requirement_ids
    ).join(", "),
  );
  const [effNote, setEffNote] = useState("");
  const [effVerdict, setEffVerdict] = useState<
    "EFFECTIVE" | "PARTIALLY_EFFECTIVE" | "INEFFECTIVE"
  >("EFFECTIVE");
  const [effReassessment, setEffReassessment] = useState<string>("");
  const reassessments = useQuery({
    queryKey: ["reassessments", orgId, c.id],
    queryFn: () => api.listReassessments(orgId, c.id),
    enabled: a.lifecycle === "DONE" && c.status !== "CLOSED",
  });
  const citable = (reassessments.data ?? []).filter(
    (r) => r.status === "LAUNCHED" && r.selected_action_ids.includes(a.id),
  );

  const review = useMutation({
    mutationFn: () =>
      api.reviewAction(orgId, c.id, a.id, {
        action: reviewAction!,
        ...(reviewAction !== "reject" ? { priority } : {}),
        ...(reviewAction !== "reject" && actionDueDate ? { due_date: actionDueDate } : {}),
        ...(reviewAction === "edit" && description.trim()
          ? { description: description.trim() }
          : {}),
        // filter(Boolean): a trailing comma — the commonest typo in a
        // comma-separated field — used to submit an empty id, which the
        // server then rejected with «Exigence(s) inconnue(s) … : » and
        // nothing after the colon.
        ...(reviewAction === "edit" && scopeIds.trim()
          ? {
              impacted_requirement_ids: scopeIds
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            }
          : {}),
      }),
    onSuccess: () => {
      setReviewAction(null);
      onChanged();
    },
  });
  const lifecycle = useMutation({
    mutationFn: (target: "IN_PROGRESS" | "DONE" | "CANCELLED") =>
      api.changeLifecycle(orgId, c.id, a.id, target),
    onSuccess: onChanged,
  });
  const effectiveness = useMutation({
    mutationFn: () =>
      api.recordEffectiveness(orgId, c.id, a.id, {
        effectiveness: effVerdict,
        note: effNote.trim(),
        reassessment_id: effReassessment || null,
      }),
    onSuccess: onChanged,
  });

  const reviewable =
    a.lifecycle === "PROPOSED" || (a.review_status === "CONFIRMED" && a.lifecycle === "APPROVED");
  const proposed = a.lifecycle === "PROPOSED";

  return (
    <li
      className={`space-y-3 rounded-lg border p-4 text-sm ${
        proposed ? "border-warning/40 bg-warning/5" : "border-border bg-card"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted-foreground">#{a.position}</span>
        <span className="rounded-full bg-muted px-2 py-0.5 text-xs">
          {actionTypeLabel(a.action_type)}
        </span>
        <StatusLabel display={actionLifecycleDisplay(a.lifecycle)} dot={false} />
        {a.priority && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs">
            {priorityDisplay(a.priority).label}
          </span>
        )}
        {a.effectiveness !== "NOT_CHECKED" && (
          <StatusLabel display={effectivenessDisplay(a.effectiveness)} dot={false} />
        )}
      </div>
      <p className="leading-relaxed font-medium text-foreground">
        {a.description ?? a.ai_description}
      </p>
      <p className="text-xs text-muted-foreground">Justification IA : {a.ai_rationale}</p>
      <dl className="grid gap-x-6 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2">
        <div>
          <dt className="inline font-medium">Rôle responsable : </dt>
          <dd className="inline">{a.owner_role ?? a.ai_owner_role}</dd>
        </div>
        <div>
          <dt className="inline font-medium">Échéance : </dt>
          {a.due_date ? (
            <dd className="inline">{new Date(a.due_date).toLocaleDateString("fr-FR")}</dd>
          ) : (
            <dd className="inline italic">{MISSING.deadline}</dd>
          )}
        </div>
        <div className="sm:col-span-2">
          <dt className="inline font-medium">Critère de succès : </dt>
          <dd className="inline">{a.success_criterion ?? a.ai_success_criterion}</dd>
        </div>
      </dl>
      {a.policy_quote &&
        (a.source_quote ? (
          <blockquote className="border-l-2 border-primary/40 pl-3 text-xs text-muted-foreground">
            « {a.source_quote} »
            <span className="ml-1 text-muted-foreground/80">
              (citation localisée, pertinence à confirmer)
            </span>
          </blockquote>
        ) : (
          <p className="text-xs text-destructive">
            Citation non affichable : {a.source_quote_error ?? "provenance invalide"}
          </p>
        ))}
      <p className="text-xs text-muted-foreground">
        Exigences visées (proposition IA) : {a.ai_impacted_requirement_ids.join(", ")}
        {a.effective_requirement_ids?.length > 0 && (
          <>
            {" "}
            · Périmètre effectif (décision humaine) : {a.effective_requirement_ids.join(", ")}
          </>
        )}
      </p>

      {reviewable && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {(["approve", "edit", "reject"] as const).map((ra) => (
              <button
                key={ra}
                onClick={() => setReviewAction(ra)}
                aria-pressed={reviewAction === ra}
                className={`min-h-10 rounded-md border px-3 py-1 text-xs font-medium ${
                  reviewAction === ra
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-input hover:bg-muted/50"
                }`}
              >
                {ra === "approve" ? "Approuver" : ra === "edit" ? "Modifier" : "Rejeter"}
              </button>
            ))}
          </div>
          {reviewAction && reviewAction !== "reject" && (
            <div className="grid gap-2 sm:grid-cols-2">
              <label>
                <span className="text-xs text-muted-foreground">Priorité (requise)</span>
                <select
                  value={priority}
                  onChange={(e) => setPriority(e.target.value as typeof priority)}
                  className="mt-1 w-full rounded-md border border-input px-2 py-1"
                >
                  <option value="haute">Haute</option>
                  <option value="normale">Normale</option>
                  <option value="basse">Basse</option>
                </select>
                {a.suggested_priority && !a.priority && (
                  <span className="mt-1 block text-xs text-muted-foreground/80">
                    Suggestion « {a.suggested_priority} » dérivée de la sévérité — décision
                    humaine requise.
                  </span>
                )}
              </label>
              <label>
                <span className="text-xs text-muted-foreground">
                  Échéance (requise avant lancement)
                </span>
                <input
                  type="date"
                  value={actionDueDate}
                  onChange={(e) => setActionDueDate(e.target.value)}
                  className="mt-1 w-full rounded-md border border-input px-2 py-1"
                />
              </label>
              {reviewAction === "edit" && (
                <>
                  <label className="sm:col-span-2">
                    <span className="text-xs text-muted-foreground">Description (surcharge)</span>
                    <textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={2}
                      className="mt-1 w-full rounded-md border border-input px-2 py-1"
                    />
                  </label>
                  <label className="sm:col-span-2">
                    <span className="text-xs text-muted-foreground">
                      Exigences visées (ids séparés par des virgules — votre décision remplace la
                      proposition IA)
                    </span>
                    <input
                      value={scopeIds}
                      onChange={(e) => setScopeIds(e.target.value)}
                      className="mt-1 w-full rounded-md border border-input px-2 py-1"
                    />
                  </label>
                </>
              )}
            </div>
          )}
          {reviewAction && (
            <button
              onClick={() => review.mutate()}
              disabled={review.isPending}
              className="min-h-10 rounded-md bg-success px-3 py-1.5 text-xs font-medium text-success-foreground hover:bg-success/90 disabled:opacity-50"
            >
              Enregistrer la décision
            </button>
          )}
        </div>
      )}

      {a.lifecycle === "APPROVED" && (
        <div className="flex gap-2">
          <button
            onClick={() => lifecycle.mutate("IN_PROGRESS")}
            className="min-h-10 rounded-md border border-input px-3 py-1 text-xs hover:bg-muted/50"
          >
            Démarrer
          </button>
          <button
            onClick={() => lifecycle.mutate("CANCELLED")}
            className="min-h-10 rounded-md border border-input px-3 py-1 text-xs hover:bg-muted/50"
          >
            Annuler
          </button>
        </div>
      )}
      {a.lifecycle === "IN_PROGRESS" && (
        <div className="flex gap-2">
          <button
            onClick={() => lifecycle.mutate("DONE")}
            className="min-h-10 rounded-md border border-success/40 px-3 py-1 text-xs text-success hover:bg-success/10"
          >
            Marquer terminée
          </button>
          <button
            onClick={() => lifecycle.mutate("CANCELLED")}
            className="min-h-10 rounded-md border border-input px-3 py-1 text-xs hover:bg-muted/50"
          >
            Annuler
          </button>
        </div>
      )}
      {a.lifecycle === "DONE" && c.status !== "CLOSED" && (
        <div className="space-y-2 rounded-lg bg-muted/50 p-3">
          <p className="text-xs font-semibold text-muted-foreground">
            Efficacité (verdict humain — une réévaluation est une preuve, jamais une garantie)
          </p>
          <div className="flex flex-wrap gap-2">
            <select
              value={effVerdict}
              onChange={(e) => setEffVerdict(e.target.value as typeof effVerdict)}
              className="rounded-md border border-input px-2 py-1 text-xs"
            >
              <option value="EFFECTIVE">Efficace</option>
              <option value="PARTIALLY_EFFECTIVE">Partiellement efficace</option>
              <option value="INEFFECTIVE">Inefficace</option>
            </select>
            {citable.length > 0 && (
              <select
                value={effReassessment}
                onChange={(e) => setEffReassessment(e.target.value)}
                aria-label="Réévaluation citée en preuve"
                className="rounded-md border border-input px-2 py-1 text-xs"
              >
                <option value="">Sans réévaluation (preuve externe)</option>
                {citable.map((r) => (
                  <option key={r.id} value={r.id}>
                    Réévaluation du {new Date(r.created_at).toLocaleDateString("fr-FR")} (
                    {r.included_requirement_ids.join(", ")})
                  </option>
                ))}
              </select>
            )}
            <input
              value={effNote}
              onChange={(e) => setEffNote(e.target.value)}
              placeholder="Preuve / justification (requise)"
              className="min-w-64 flex-1 rounded-md border border-input px-2 py-1 text-xs"
            />
            <button
              onClick={() => effectiveness.mutate()}
              disabled={effectiveness.isPending || !effNote.trim()}
              className="min-h-9 rounded-md bg-success px-3 py-1 text-xs font-medium text-success-foreground disabled:opacity-50"
            >
              Enregistrer
            </button>
          </div>
        </div>
      )}
      {a.action_type === "document_amendment" &&
        a.lifecycle === "APPROVED" &&
        c.status !== "CLOSED" && <PatchPanel orgId={orgId} c={c} a={a} onChanged={onChanged} />}
      <ErrorText error={review.error || lifecycle.error || effectiveness.error} />
    </li>
  );
}
