import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  OPERATIONAL_ABORT_REASONS,
  type Classification,
  type DocumentVersionSummary,
  type RemediationArtifactView,
  type RemediationAction,
  type RemediationCaseDetail,
  type RemediationPlan,
  type RemediationScope,
  type TriageDraft,
} from "../api";
import { CaseStatusBadge } from "./RemediationListPage";

const CLASSIFICATION_LABELS: Record<Classification, string> = {
  evidence_gap: "Lacune de preuve",
  observation: "Observation",
  improvement_opportunity: "Piste d'amélioration",
  nonconformity: "Non-conformité",
};

const SCOPE_LABELS: Record<RemediationScope, string> = {
  local: "Local",
  related_requirements: "Exigences liées",
  organization_wide: "Toute l'organisation",
};

const ACTION_TYPE_LABELS: Record<RemediationAction["action_type"], string> = {
  document_amendment: "Amendement documentaire",
  new_document: "Nouveau document",
  process_change: "Changement de processus",
  training: "Formation",
  risk_treatment_update: "Mise à jour du traitement des risques",
  other: "Autre",
};

const LIFECYCLE_LABELS: Record<RemediationAction["lifecycle"], string> = {
  PROPOSED: "Proposée",
  APPROVED: "Approuvée",
  REJECTED: "Rejetée",
  IN_PROGRESS: "En cours",
  DONE: "Terminée",
  CANCELLED: "Annulée",
};

const EFFECTIVENESS_LABELS: Record<RemediationAction["effectiveness"], string> = {
  NOT_CHECKED: "Non vérifiée",
  EFFECTIVE: "Efficace",
  PARTIALLY_EFFECTIVE: "Partiellement efficace",
  INEFFECTIVE: "Inefficace",
};

const isOperationalAbort = (reason: string | null) =>
  reason !== null && (OPERATIONAL_ABORT_REASONS as readonly string[]).includes(reason);

export default function RemediationCasePage() {
  const { orgId, caseId } = useParams<{ orgId: string; caseId: string }>();
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["remediation-case", orgId, caseId],
    queryFn: () => api.getCase(orgId!, caseId!),
  });
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["remediation-case", orgId, caseId] });

  if (detail.isError) {
    return <p className="text-sm text-red-600">{(detail.error as Error).message}</p>;
  }
  if (!detail.data) {
    return <p className="text-sm text-slate-500">Chargement…</p>;
  }
  const c = detail.data;
  const activePlan = c.plans.find((p) => p.id === c.active_plan_id) ?? null;

  return (
    <div className="space-y-6">
      <Link
        to={`/organizations/${orgId}/remediation`}
        className="text-sm text-indigo-600 hover:underline"
      >
        ← Cas de remédiation
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{c.title}</h1>
        <CaseStatusBadge status={c.status} />
      </div>

      <LinkedFindings orgId={orgId!} c={c} onChanged={invalidate} />
      <TriagePanel orgId={orgId!} c={c} onChanged={invalidate} />
      <PlanPanel orgId={orgId!} c={c} activePlan={activePlan} onChanged={invalidate} />
      <ReassessmentPanel orgId={orgId!} c={c} activePlan={activePlan} onChanged={invalidate} />
      <ClosurePanel orgId={orgId!} c={c} onChanged={invalidate} />
      <EventsTimeline c={c} />
    </div>
  );
}

function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-sm text-red-600">{(error as Error).message}</p>;
}

// -------------------------------------------------------- linked findings

function LinkedFindings({
  orgId,
  c,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  onChanged: () => void;
}) {
  const suggestions = useQuery({
    queryKey: ["link-suggestions", orgId, c.id],
    queryFn: () => api.linkSuggestions(orgId, c.id),
    enabled: c.status === "TRIAGE",
  });
  const link = useMutation({
    mutationFn: (body: { finding_id: string; decision: "link" | "reject" }) =>
      api.linkFinding(orgId, c.id, { ...body, link_source: "search_suggested" }),
    onSuccess: () => {
      onChanged();
      suggestions.refetch();
    },
  });
  const unlink = useMutation({
    mutationFn: (findingId: string) => api.unlinkFinding(orgId, c.id, findingId),
    onSuccess: onChanged,
  });

  return (
    <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Constats liés
      </h2>
      <ul className="space-y-2">
        {c.finding_links.map((l) => (
          <li
            key={l.finding_id}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 p-3 text-sm"
          >
            <span className="font-mono text-xs">{l.finding_requirement_id}</span>
            {l.is_primary && (
              <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700">
                principal
              </span>
            )}
            <span className="text-slate-600">{l.finding_requirement_fr}</span>
            <span className="text-xs text-slate-500">verdict : {l.finding_human_verdict}</span>
            {!l.is_primary && c.status === "TRIAGE" && (
              <button
                onClick={() => unlink.mutate(l.finding_id)}
                className="ml-auto text-xs text-red-600 hover:underline"
              >
                Délier
              </button>
            )}
          </li>
        ))}
      </ul>
      {c.status === "TRIAGE" && (suggestions.data?.length ?? 0) > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold text-slate-500">
            Lacunes similaires suggérées (décision humaine : lier ou écarter)
          </h3>
          <ul className="space-y-1">
            {suggestions.data!.map((s) => (
              <li
                key={s.finding_id}
                className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-2 text-sm"
              >
                <span className="font-mono text-xs">{s.requirement_id}</span>
                <span className="text-slate-600">{s.requirement_fr}</span>
                {s.same_domain && (
                  <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-700">
                    même domaine
                  </span>
                )}
                <span className="ml-auto flex gap-2">
                  <button
                    onClick={() => link.mutate({ finding_id: s.finding_id, decision: "link" })}
                    className="text-xs font-medium text-indigo-600 hover:underline"
                  >
                    Lier
                  </button>
                  <button
                    onClick={() =>
                      link.mutate({ finding_id: s.finding_id, decision: "reject" })
                    }
                    className="text-xs text-slate-500 hover:underline"
                  >
                    Écarter
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <ErrorText error={link.error || unlink.error} />
    </section>
  );
}

// ---------------------------------------------------------------- triage

function TriagePanel({
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

  return (
    <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Triage</h2>
        {approved ? (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">
            approuvé par un humain
          </span>
        ) : (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
            en attente d'approbation humaine
          </span>
        )}
      </div>

      {approved ? (
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-slate-500">Qualification</dt>
            <dd>{CLASSIFICATION_LABELS[c.classification!]}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Périmètre</dt>
            <dd>{SCOPE_LABELS[c.scope!]}</dd>
          </div>
          {c.correction_note && (
            <div className="sm:col-span-2">
              <dt className="text-xs text-slate-500">Correction immédiate</dt>
              <dd>{c.correction_note}</dd>
            </div>
          )}
          <div className="sm:col-span-2">
            <dt className="text-xs text-slate-500">Justification du périmètre</dt>
            <dd>{c.scope_rationale}</dd>
          </div>
        </dl>
      ) : latest ? (
        <div className="space-y-3">
          <div
            className={`rounded-lg border p-4 text-sm ${
              abstained
                ? isOperationalAbort(latest.abstain_reason)
                  ? "border-slate-200 bg-slate-50"
                  : "border-amber-200 bg-amber-50"
                : "border-indigo-200 bg-indigo-50"
            }`}
          >
            <p className="text-xs font-semibold text-slate-500">
              Proposition IA (brouillon n°{latest.sequence}) — à valider par un humain
            </p>
            {abstained ? (
              <p className="mt-2">
                L'agent s'est abstenu ({latest.abstain_reason}) : renseignez le triage
                vous-même ci-dessous, ou relancez la proposition.
              </p>
            ) : (
              <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-slate-500">Qualification proposée</dt>
                  <dd>{CLASSIFICATION_LABELS[latest.ai_classification!]}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Périmètre proposé</dt>
                  <dd>{SCOPE_LABELS[latest.ai_scope!]}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-xs text-slate-500">Correction immédiate</dt>
                  <dd>{latest.ai_correction_note}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-xs text-slate-500">Justification</dt>
                  <dd>{latest.ai_scope_rationale}</dd>
                </div>
              </dl>
            )}
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-sm">
              <span className="text-xs text-slate-500">
                Qualification {abstained ? "(requise)" : "(laisser vide pour accepter)"}
              </span>
              <select
                value={classification}
                onChange={(e) => setClassification(e.target.value as Classification | "")}
                className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5"
              >
                <option value="">— proposition IA —</option>
                {Object.entries(CLASSIFICATION_LABELS).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="text-xs text-slate-500">
                Périmètre {abstained ? "(requis)" : "(laisser vide pour accepter)"}
              </span>
              <select
                value={scope}
                onChange={(e) => setScope(e.target.value as RemediationScope | "")}
                className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5"
              >
                <option value="">— proposition IA —</option>
                {Object.entries(SCOPE_LABELS).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm sm:col-span-2">
              <span className="text-xs text-slate-500">Correction immédiate (surcharge)</span>
              <textarea
                value={correctionNote}
                onChange={(e) => setCorrectionNote(e.target.value)}
                rows={2}
                className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5"
              />
            </label>
            <label className="text-sm sm:col-span-2">
              <span className="text-xs text-slate-500">
                Justification du périmètre {abstained ? "(requise)" : "(surcharge)"}
              </span>
              <textarea
                value={scopeRationale}
                onChange={(e) => setScopeRationale(e.target.value)}
                rows={2}
                className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5"
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => approve.mutate()}
              disabled={approve.isPending}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              Approuver le triage
            </button>
            <button
              onClick={() => redraft.mutate()}
              disabled={redraft.isPending}
              className="rounded-lg border border-indigo-300 px-3 py-1.5 text-sm text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
            >
              Relancer la proposition IA
            </button>
          </div>
        </div>
      ) : (
        <p className="text-sm text-slate-500">Aucune proposition de triage.</p>
      )}

      {c.triage_drafts.length > 1 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs font-semibold text-slate-500">
            Historique des propositions ({c.triage_drafts.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {c.triage_drafts.map((d) => (
              <li key={d.id} className="flex flex-wrap gap-2 text-xs text-slate-600">
                <span className="font-mono">n°{d.sequence}</span>
                <span>{d.status}</span>
                {d.abstain_reason && <span>({d.abstain_reason})</span>}
                {d.id === c.approved_triage_draft_id && (
                  <span className="text-emerald-700">approuvée</span>
                )}
                <span className="text-slate-400">
                  {new Date(d.created_at).toLocaleString("fr-FR")}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {approved && ["TRIAGE_APPROVED", "PLAN_READY"].includes(c.status) && (
        <button
          onClick={() => reopen.mutate()}
          disabled={reopen.isPending}
          className="rounded-lg border border-amber-300 px-3 py-1.5 text-sm text-amber-700 hover:bg-amber-50 disabled:opacity-50"
        >
          Rouvrir le triage
        </button>
      )}
      <ErrorText error={approve.error || redraft.error || reopen.error} />
    </section>
  );
}

// ------------------------------------------------------------------ plan

function PlanPanel({
  orgId,
  c,
  activePlan,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  activePlan: RemediationPlan | null;
  onChanged: () => void;
}) {
  const draft = useMutation({
    mutationFn: () => api.draftPlan(orgId, c.id),
    onSuccess: onChanged,
  });
  const canDraft = ["TRIAGE_APPROVED", "PLAN_READY"].includes(c.status);

  return (
    <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Plan d'actions correctives
        </h2>
        {canDraft && (
          <button
            onClick={() => draft.mutate()}
            disabled={draft.isPending}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {draft.isPending
              ? "Rédaction en cours…"
              : activePlan
                ? "Redemander un plan"
                : "Demander un plan à l'agent"}
          </button>
        )}
      </div>

      {activePlan === null ? (
        <p className="text-sm text-slate-500">
          Aucun plan actif. {c.status === "TRIAGE" && "Approuvez d'abord le triage."}
        </p>
      ) : activePlan.status === "ABSTAINED" ? (
        <div
          className={`rounded-lg border p-4 text-sm ${
            isOperationalAbort(activePlan.abstain_reason)
              ? "border-slate-200 bg-slate-50"
              : "border-amber-200 bg-amber-50"
          }`}
        >
          <p className="font-medium">
            {isOperationalAbort(activePlan.abstain_reason)
              ? "Rédaction interrompue (incident technique)"
              : "L'agent s'est abstenu"}
          </p>
          <p className="mt-1 text-slate-600">
            Motif : {activePlan.abstain_reason}. Relancez la rédaction ou traitez le cas
            manuellement.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-4 text-sm">
            <p className="text-xs font-semibold text-slate-500">
              Brouillon IA n°{activePlan.sequence} — chaque action requiert votre décision
            </p>
            <p className="mt-2">{activePlan.gap_restatement}</p>
            {activePlan.root_cause_hypotheses && (
              <ul className="mt-2 space-y-1">
                {activePlan.root_cause_hypotheses.map((h) => (
                  <li key={h.label}>
                    <span className="font-mono text-xs">{h.label}</span> (hypothèse) :{" "}
                    {h.hypothesis}
                  </li>
                ))}
              </ul>
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
        <details className="text-sm">
          <summary className="cursor-pointer text-xs font-semibold text-slate-500">
            Historique des plans ({c.plans.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {c.plans.map((p) => (
              <li key={p.id} className="flex flex-wrap gap-2 text-xs text-slate-600">
                <span className="font-mono">n°{p.sequence}</span>
                <span>{p.status}</span>
                {p.abstain_reason && <span>({p.abstain_reason})</span>}
                {p.status === "SUPERSEDED" && (
                  <span className="text-amber-700">
                    remplacé
                    {p.superseded_by_plan_id
                      ? ` par le plan ${
                          c.plans.find((q) => q.id === p.superseded_by_plan_id)?.sequence ??
                          "?"
                        }`
                      : " (réouverture du triage)"}
                    {p.superseded_at
                      ? ` le ${new Date(p.superseded_at).toLocaleDateString("fr-FR")}`
                      : ""}
                  </span>
                )}
                {p.id === c.active_plan_id && <span className="text-emerald-700">actif</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
      <ErrorText error={draft.error} />
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
  const [priority, setPriority] = useState<"haute" | "normale" | "basse">("normale");
  const [description, setDescription] = useState("");
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
        ...(reviewAction === "edit" && description.trim()
          ? { description: description.trim() }
          : {}),
        ...(reviewAction === "edit" && scopeIds.trim()
          ? { impacted_requirement_ids: scopeIds.split(",").map((s) => s.trim()) }
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

  return (
    <li className="space-y-3 rounded-lg border border-slate-200 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-slate-500">#{a.position}</span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
          {ACTION_TYPE_LABELS[a.action_type]}
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
          {LIFECYCLE_LABELS[a.lifecycle]}
        </span>
        {a.priority && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
            priorité {a.priority}
          </span>
        )}
        {a.effectiveness !== "NOT_CHECKED" && (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">
            {EFFECTIVENESS_LABELS[a.effectiveness]}
          </span>
        )}
      </div>
      <p>{a.description ?? a.ai_description}</p>
      <p className="text-xs text-slate-500">Justification IA : {a.ai_rationale}</p>
      <p className="text-xs text-slate-500">
        Rôle suggéré : {a.owner_role ?? a.ai_owner_role} · Critère de succès :{" "}
        {a.success_criterion ?? a.ai_success_criterion}
      </p>
      {a.policy_quote &&
        (a.source_quote ? (
          <blockquote className="border-l-2 border-indigo-300 pl-3 text-xs text-slate-600">
            « {a.source_quote} »
            <span className="ml-1 text-slate-400">
              (citation localisée, pertinence à confirmer)
            </span>
          </blockquote>
        ) : (
          <p className="text-xs text-red-600">
            Citation non affichable : {a.source_quote_error ?? "provenance invalide"}
          </p>
        ))}
      <p className="text-xs text-slate-500">
        Exigences visées (proposition IA) : {a.ai_impacted_requirement_ids.join(", ")}
        {a.effective_requirement_ids?.length > 0 && (
          <>
            {" "}
            · Périmètre effectif (décision humaine) :{" "}
            {a.effective_requirement_ids.join(", ")}
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
                className={`rounded-lg border px-3 py-1 text-xs font-medium ${
                  reviewAction === ra
                    ? "border-indigo-500 bg-indigo-600 text-white"
                    : "border-slate-300 hover:bg-slate-50"
                }`}
              >
                {ra === "approve" ? "Approuver" : ra === "edit" ? "Modifier" : "Rejeter"}
              </button>
            ))}
          </div>
          {reviewAction && reviewAction !== "reject" && (
            <div className="grid gap-2 sm:grid-cols-2">
              <label>
                <span className="text-xs text-slate-500">Priorité (requise)</span>
                <select
                  value={priority}
                  onChange={(e) => setPriority(e.target.value as typeof priority)}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1"
                >
                  <option value="haute">Haute</option>
                  <option value="normale">Normale</option>
                  <option value="basse">Basse</option>
                </select>
              </label>
              {reviewAction === "edit" && (
                <>
                  <label className="sm:col-span-2">
                    <span className="text-xs text-slate-500">Description (surcharge)</span>
                    <textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={2}
                      className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1"
                    />
                  </label>
                  <label className="sm:col-span-2">
                    <span className="text-xs text-slate-500">
                      Exigences visées (ids séparés par des virgules — votre décision remplace
                      la proposition IA)
                    </span>
                    <input
                      value={scopeIds}
                      onChange={(e) => setScopeIds(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1"
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
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
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
            className="rounded-lg border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50"
          >
            Démarrer
          </button>
          <button
            onClick={() => lifecycle.mutate("CANCELLED")}
            className="rounded-lg border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50"
          >
            Annuler
          </button>
        </div>
      )}
      {a.lifecycle === "IN_PROGRESS" && (
        <div className="flex gap-2">
          <button
            onClick={() => lifecycle.mutate("DONE")}
            className="rounded-lg border border-emerald-300 px-3 py-1 text-xs text-emerald-700 hover:bg-emerald-50"
          >
            Marquer terminée
          </button>
          <button
            onClick={() => lifecycle.mutate("CANCELLED")}
            className="rounded-lg border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50"
          >
            Annuler
          </button>
        </div>
      )}
      {a.lifecycle === "DONE" && c.status !== "CLOSED" && (
        <div className="space-y-2 rounded-lg bg-slate-50 p-3">
          <p className="text-xs font-semibold text-slate-500">
            Efficacité (verdict humain — une réévaluation est une preuve, jamais une garantie)
          </p>
          <div className="flex flex-wrap gap-2">
            <select
              value={effVerdict}
              onChange={(e) => setEffVerdict(e.target.value as typeof effVerdict)}
              className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
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
                className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
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
              className="min-w-64 flex-1 rounded-lg border border-slate-300 px-2 py-1 text-xs"
            />
            <button
              onClick={() => effectiveness.mutate()}
              disabled={effectiveness.isPending || !effNote.trim()}
              className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
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

// ------------------------------------------------------------ M7b patches

const VERSION_STATE_LABELS: Record<DocumentVersionSummary["state"], string> = {
  PENDING_INDEX: "Indexation en cours",
  ACTIVE: "Active",
  SUPERSEDED: "Remplacée",
  INDEX_FAILED: "Échec d'indexation",
  ABANDONED: "Abandonnée",
};

function PatchPanel({
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
  const [docId, setDocId] = useState("");
  const documents = useQuery({
    queryKey: ["documents", orgId],
    queryFn: () => api.listDocuments(orgId),
  });
  const proposals = useQuery({
    queryKey: ["patch-proposals", orgId, c.id, a.id],
    queryFn: () => api.listPatchProposals(orgId, c.id, a.id),
  });
  const artifacts = useQuery({
    queryKey: ["artifacts", orgId, c.id, a.id],
    queryFn: () => api.listArtifacts(orgId, c.id, a.id),
  });
  const parsed = (documents.data ?? []).filter((d) => d.status === "parsed");
  const selected = parsed.find((d) => d.id === docId);
  // Route by the CURRENT version format (server-derived); fall back to the
  // filename extension until a version pointer exists.
  const format = selected
    ? (selected.filename.toLowerCase().split(".").pop() ?? "")
    : "";
  const isTextual = format === "txt" || format === "md";

  const propose = useMutation({
    mutationFn: () => api.createPatchProposal(orgId, c.id, a.id, docId),
    onSuccess: () => {
      proposals.refetch();
      onChanged();
    },
  });
  const proposeArtifact = useMutation({
    mutationFn: () => api.createArtifact(orgId, c.id, a.id, docId),
    onSuccess: () => {
      artifacts.refetch();
      onChanged();
    },
  });

  return (
    <div className="space-y-3 rounded-lg border border-indigo-100 bg-indigo-50/40 p-3">
      <p className="text-xs font-semibold text-indigo-700">Correctif documentaire</p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={docId}
          onChange={(e) => setDocId(e.target.value)}
          aria-label="Document cible"
          className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
        >
          <option value="">Choisir le document cible…</option>
          {parsed.map((d) => (
            <option key={d.id} value={d.id}>
              {d.filename}
            </option>
          ))}
        </select>
        {selected &&
          (isTextual ? (
            <button
              onClick={() => propose.mutate()}
              disabled={propose.isPending}
              className="rounded-lg bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Proposer un correctif
            </button>
          ) : (
            <button
              onClick={() => proposeArtifact.mutate()}
              disabled={proposeArtifact.isPending}
              className="rounded-lg bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Proposer une rédaction (PDF/DOCX)
            </button>
          ))}
      </div>
      {selected && !isTextual && (
        <p className="text-xs text-slate-500">
          PDF/DOCX : l'agent produit une proposition Markdown ; le document original reste
          inchangé et seul un téléversement humain crée une nouvelle version.
        </p>
      )}
      <ErrorText error={propose.error || proposeArtifact.error} />

      {(proposals.data ?? []).map((p) => (
        <PatchProposalCard key={p.id} orgId={orgId} c={c} proposalId={p.id} onChanged={onChanged} />
      ))}
      {(artifacts.data ?? [])
        .filter((art) => art.status === "VERIFIED")
        .map((art) => (
          <ArtifactCard key={art.id} orgId={orgId} c={c} art={art} onChanged={onChanged} />
        ))}
    </div>
  );
}

function ArtifactCard({
  orgId,
  c,
  art,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  art: RemediationArtifactView;
  onChanged: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  // A candidate this artifact spawned that never finished activating (a crash /
  // Qdrant outage / assessment conflict). Detecting it on LOAD makes recovery
  // reachable after a refresh, not only within the failed upload's session.
  const versions = useQuery({
    queryKey: ["document-versions", art.document_id],
    queryFn: () => api.listDocumentVersions(art.document_id),
  });
  const refresh = () => {
    versions.refetch();
    onChanged();
  };
  // The superseding upload replaces the version the artifact was drafted
  // against and records the artifact as lineage (action -> artifact -> file ->
  // version).
  const supersede = useMutation({
    mutationFn: (f: File) =>
      api.supersedeUpload(orgId, f, art.document_version_id, art.id),
    onSuccess: () => {
      setFile(null);
      refresh();
    },
  });
  // Recovery re-drives a stranded activation WITHOUT re-uploading the file —
  // it operates on the candidate version the first upload already created.
  const recover = useMutation({
    mutationFn: (versionId: string) => api.recoverUpload(art.document_id, versionId),
    onSuccess: refresh,
  });
  const stranded = (versions.data ?? []).find(
    (v) =>
      v.source_artifact_id === art.id &&
      v.supersedes_version_id === art.document_version_id &&
      (v.state === "PENDING_INDEX" || v.state === "INDEX_FAILED"),
  );
  const result = recover.data ?? supersede.data;
  const outcome = result?.outcome ?? "";
  const inSessionRecoverable =
    outcome === "pending" || outcome === "index_failed" || outcome === "assessment_conflict";
  // recover id: the in-session mutation result, else the stranded version on load
  const recoverVersionId = inSessionRecoverable ? result?.version_id : stranded?.id;
  return (
    <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3 text-xs">
      <p className="font-medium text-slate-700">
        Proposition de rédaction ({art.canonical_format.toUpperCase()})
      </p>
      <a
        href={api.artifactDownloadUrl(orgId, c.id, art.id)}
        className="text-indigo-600 underline"
      >
        Télécharger le brouillon Markdown
      </a>
      <p className="text-slate-400">
        Brouillon IA — préparez le fichier {art.canonical_format.toUpperCase()} révisé,
        puis téléversez-le ici pour créer la nouvelle version (le document original reste
        inchangé).
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="file"
          aria-label="Fichier révisé à téléverser"
          accept={art.canonical_format === "pdf" ? ".pdf" : ".docx"}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-xs"
        />
        <button
          onClick={() => file && supersede.mutate(file)}
          disabled={!file || supersede.isPending}
          className="rounded-lg bg-indigo-600 px-3 py-1 font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          Téléverser la version révisée
        </button>
      </div>
      {(outcome === "activated" || outcome === "already_active") && (
        <p className="text-emerald-700">
          Nouvelle version créée et activée à partir de votre fichier révisé.
        </p>
      )}
      {outcome === "index_failed" && (
        <p className="text-amber-700">
          Indexation vectorielle échouée ; la version est conservée et peut être reprise.
        </p>
      )}
      {outcome === "pending" && (
        <p className="text-amber-700">Activation en attente ; vous pouvez la reprendre.</p>
      )}
      {outcome === "assessment_conflict" && (
        <p className="text-amber-700">
          Une évaluation est en cours ; réessayez la reprise une fois qu'elle est terminée.
        </p>
      )}
      {outcome.startsWith("abandoned:") && (
        <p className="text-red-600">
          Activation abandonnée ({outcome.split(":")[1]}) : retéléversez la version révisée.
        </p>
      )}
      {/* stranded on load (survives a refresh), when no in-session outcome shows it */}
      {!inSessionRecoverable && stranded && (
        <p className="text-amber-700">
          Une activation de version ({stranded.state === "INDEX_FAILED"
            ? "échec d'indexation"
            : "en attente"}) est restée inachevée ; vous pouvez la reprendre.
        </p>
      )}
      {recoverVersionId && (
        <button
          onClick={() => recover.mutate(recoverVersionId)}
          disabled={recover.isPending}
          className="rounded-lg border border-indigo-300 px-3 py-1 text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
        >
          Reprendre l'activation
        </button>
      )}
      <ErrorText error={supersede.error || recover.error} />
    </div>
  );
}

function PatchProposalCard({
  orgId,
  c,
  proposalId,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  proposalId: string;
  onChanged: () => void;
}) {
  const proposal = useQuery({
    queryKey: ["patch-proposal", orgId, c.id, proposalId],
    queryFn: () => api.getPatchProposal(orgId, c.id, proposalId),
  });
  const versions = useQuery({
    queryKey: ["document-versions", proposal.data?.document_id],
    queryFn: () => api.listDocumentVersions(proposal.data!.document_id),
    enabled: !!proposal.data,
  });
  const [editing, setEditing] = useState(false);
  const [finalText, setFinalText] = useState("");
  const refresh = () => {
    proposal.refetch();
    versions.refetch();
    onChanged();
  };
  const decide = useMutation({
    mutationFn: (body: { decision: "approve" | "edit" | "reject"; final_text_fr?: string }) =>
      api.decidePatch(orgId, c.id, proposalId, body),
    onSuccess: () => {
      setEditing(false);
      refresh();
    },
  });
  const recover = useMutation({
    mutationFn: () => api.recoverPatch(orgId, c.id, proposalId),
    onSuccess: refresh,
  });

  const p = proposal.data;
  if (!p) return null;

  if (p.status === "ABSTAINED") {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
        <p className="font-medium">Correctif en abstention ({p.abstain_reason})</p>
        <p className="mt-1">
          L'agent n'a pas pu ancrer un correctif fiable ; rédigez la modification manuellement.
        </p>
      </div>
    );
  }
  if (p.status === "DRAFTING") {
    return <p className="text-xs text-slate-500">Rédaction du correctif en cours…</p>;
  }

  const resultVersion = (versions.data ?? []).find((v) => v.id === p.decision?.result_version_id);
  const stranded =
    resultVersion &&
    (resultVersion.state === "INDEX_FAILED" || resultVersion.state === "PENDING_INDEX");

  return (
    <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3 text-xs">
      <p className="font-medium text-slate-700">
        Diff proposé ({p.operation === "replace" ? "remplacement" : "insertion"})
      </p>
      {/* Server-derived source slice at the resolved anchor — never the model quote */}
      <div className="rounded bg-slate-50 p-2 font-mono text-[11px] leading-relaxed">
        <span className="text-slate-400">{p.context_before}</span>
        <mark className="bg-amber-200">{p.anchor_slice}</mark>
        {p.operation === "insert_after" && (
          <ins className="bg-emerald-100 text-emerald-800 no-underline">
            {"\n\n"}
            {editing ? finalText || p.new_text_fr : p.new_text_fr}
          </ins>
        )}
        {p.operation === "replace" && (
          <span className="text-slate-400 line-through">{/* replaced */}</span>
        )}
        <span className="text-slate-400">{p.context_after}</span>
      </div>
      {p.operation === "replace" && (
        <div className="rounded bg-emerald-50 p-2 font-mono text-[11px] text-emerald-800">
          → {editing ? finalText || p.new_text_fr : p.new_text_fr}
        </div>
      )}
      <p className="text-slate-500">Justification IA : {p.rationale}</p>

      {p.decision ? (
        <div className="rounded bg-slate-50 p-2">
          <p className="font-medium text-slate-600">
            Décision : {p.decision.decision}
            {resultVersion && ` → version ${resultVersion.version_number} (${
              VERSION_STATE_LABELS[resultVersion.state]
            })`}
          </p>
          {resultVersion?.state === "ACTIVE" &&
            (resultVersion.canonical_format === "txt" ||
              resultVersion.canonical_format === "md") && (
              <a
                href={api.versionDownloadUrl(p.document_id, resultVersion.id)}
                className="text-indigo-600 underline"
              >
                Télécharger la nouvelle version
              </a>
            )}
          {stranded && (
            <button
              onClick={() => recover.mutate()}
              disabled={recover.isPending}
              className="mt-1 rounded-lg border border-indigo-300 px-2 py-0.5 text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
            >
              Reprendre l'activation
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {editing && (
            <textarea
              value={finalText}
              onChange={(e) => setFinalText(e.target.value)}
              rows={3}
              placeholder="Texte final (votre rédaction sera appliquée telle quelle)"
              className="w-full rounded-lg border border-slate-300 px-2 py-1"
            />
          )}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => decide.mutate({ decision: "approve" })}
              disabled={decide.isPending}
              className="rounded-lg bg-emerald-600 px-3 py-1 font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              Approuver le correctif
            </button>
            {editing ? (
              <button
                onClick={() => decide.mutate({ decision: "edit", final_text_fr: finalText })}
                disabled={decide.isPending || !finalText.trim()}
                className="rounded-lg bg-indigo-600 px-3 py-1 font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                Appliquer ma rédaction
              </button>
            ) : (
              <button
                onClick={() => {
                  setFinalText(p.new_text_fr ?? "");
                  setEditing(true);
                }}
                className="rounded-lg border border-slate-300 px-3 py-1 hover:bg-slate-50"
              >
                Modifier le texte
              </button>
            )}
            <button
              onClick={() => decide.mutate({ decision: "reject" })}
              disabled={decide.isPending}
              className="rounded-lg border border-slate-300 px-3 py-1 hover:bg-slate-50"
            >
              Rejeter le correctif
            </button>
          </div>
        </div>
      )}
      <ErrorText error={decide.error || recover.error} />
    </div>
  );
}

// ---------------------------------------------------------- reassessments

function ReassessmentPanel({
  orgId,
  c,
  activePlan,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  activePlan: RemediationPlan | null;
  onChanged: () => void;
}) {
  const reassessments = useQuery({
    queryKey: ["reassessments", orgId, c.id],
    queryFn: () => api.listReassessments(orgId, c.id),
  });
  const doneActions = (activePlan?.actions ?? []).filter((a) => a.lifecycle === "DONE");
  const [selected, setSelected] = useState<string[]>([]);
  const launch = useMutation({
    mutationFn: () => api.launchReassessment(orgId, c.id, selected),
    onSuccess: () => {
      setSelected([]);
      reassessments.refetch();
      onChanged();
    },
  });

  return (
    <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Réévaluations ciblées (preuve d'efficacité)
      </h2>
      {doneActions.length > 0 && c.status === "IN_PROGRESS" && (
        <div className="space-y-2 text-sm">
          {doneActions.map((a) => (
            <label key={a.id} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={selected.includes(a.id)}
                onChange={(e) =>
                  setSelected((prev) =>
                    e.target.checked ? [...prev, a.id] : prev.filter((x) => x !== a.id),
                  )
                }
              />
              <span>
                #{a.position} — {a.description ?? a.ai_description}
              </span>
            </label>
          ))}
          <button
            onClick={() => launch.mutate()}
            disabled={launch.isPending || selected.length === 0}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Lancer une réévaluation
          </button>
        </div>
      )}
      {(reassessments.data?.length ?? 0) > 0 && (
        <ul className="space-y-2 text-sm">
          {reassessments.data!.map((r) => (
            <li key={r.id} className="rounded-lg border border-slate-200 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">{r.status}</span>
                {r.assessment_id && (
                  <Link
                    to={`/organizations/${orgId}/assessments/${r.assessment_id}`}
                    className="text-xs text-indigo-600 hover:underline"
                  >
                    Voir l'évaluation
                  </Link>
                )}
                <span className="text-xs text-slate-500">
                  {new Date(r.created_at).toLocaleString("fr-FR")}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-600">
                Exigences réévaluées : {r.included_requirement_ids.join(", ") || "—"}
              </p>
              {r.excluded_holdout_ids.length > 0 && (
                <p className="mt-1 text-xs text-amber-700">
                  Exclues (réservées au jeu de test M6, jamais réévaluées ici) :{" "}
                  {r.excluded_holdout_ids.join(", ")}
                </p>
              )}
              {r.error && <p className="mt-1 text-xs text-red-600">{r.error}</p>}
            </li>
          ))}
        </ul>
      )}
      <ErrorText error={launch.error} />
    </section>
  );
}

// ---------------------------------------------------------------- closure

function ClosurePanel({
  orgId,
  c,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  onChanged: () => void;
}) {
  const [note, setNote] = useState("");
  const close = useMutation({
    mutationFn: () => api.closeCase(orgId, c.id, note.trim()),
    onSuccess: onChanged,
  });
  const reopen = useMutation({
    mutationFn: () => api.reopenCase(orgId, c.id),
    onSuccess: onChanged,
  });

  if (c.status === "CLOSED") {
    return (
      <section className="space-y-2 rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Clôture
        </h2>
        <p className="text-sm">
          Clôturé le {c.closed_at ? new Date(c.closed_at).toLocaleString("fr-FR") : ""} —{" "}
          {c.close_note}
        </p>
        <button
          onClick={() => reopen.mutate()}
          disabled={reopen.isPending}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
        >
          Rouvrir le cas
        </button>
        <ErrorText error={reopen.error} />
      </section>
    );
  }
  if (!["TRIAGE_APPROVED", "PLAN_READY", "IN_PROGRESS"].includes(c.status)) return null;
  return (
    <section className="space-y-2 rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Clôture</h2>
      <div className="flex flex-wrap gap-2">
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Note de clôture (requise)"
          className="min-w-64 flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
        />
        <button
          onClick={() => close.mutate()}
          disabled={close.isPending || !note.trim()}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
        >
          Clôturer le cas
        </button>
      </div>
      <ErrorText error={close.error} />
    </section>
  );
}

// ----------------------------------------------------------------- events

function EventsTimeline({ c }: { c: RemediationCaseDetail }) {
  return (
    <section className="space-y-2 rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Journal d'audit
      </h2>
      <ul className="space-y-1 text-xs text-slate-600">
        {[...c.events].reverse().map((e) => (
          <li key={e.sequence} className="flex flex-wrap gap-2">
            <span className="font-mono text-slate-400">#{e.sequence}</span>
            <span className="font-medium">{e.event_type}</span>
            <span>{new Date(e.created_at).toLocaleString("fr-FR")}</span>
            {e.actor_label && (
              <span className="text-slate-400">par {e.actor_label} (non vérifié)</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
