import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  OPERATIONAL_ABORT_REASONS,
  type Classification,
  type RemediationArtifactView,
  type RemediationAction,
  type RemediationCaseDetail,
  type RemediationPlan,
  type RemediationScope,
  type TriageDraft,
} from "../api";
import {
  abstainReasonDisplay,
  actionLifecycleDisplay,
  actionTypeLabel,
  caseDisplayTitle,
  caseStatusDisplay,
  classificationDisplay,
  CLOSURE_RECOMMENDATIONS,
  effectivenessDisplay,
  eventTypeLabel,
  MISSING,
  priorityDisplay,
  remediationScopeDisplay,
  verdictDisplay,
  versionStateDisplay,
} from "@/lib/labels";
import { CaseStatusBadge } from "./RemediationListPage";
import { ArrowLeft } from "lucide-react";
import { NextActionPanel } from "@/components/next-action-panel";
import { SectionHeading } from "@/components/section-heading";
import { StatusLabel } from "@/components/status-label";
import { TechnicalDisclosure, TechnicalRow } from "@/components/technical-disclosure";
import { WorkflowStrip, type WorkflowStep } from "@/components/workflow-strip";

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

const isOperationalAbort = (reason: string | null) =>
  reason !== null && (OPERATIONAL_ABORT_REASONS as readonly string[]).includes(reason);

// ------------------------------------------------------ lifecycle stepper

function lifecycleSteps(c: RemediationCaseDetail, activePlan: RemediationPlan | null): WorkflowStep[] {
  const planBlocked = activePlan?.status === "ABSTAINED";
  const actions = activePlan?.status === "VERIFIED" ? activePlan.actions : [];
  const started = actions.some((a) => ["IN_PROGRESS", "DONE"].includes(a.lifecycle));
  const checked = actions.some((a) => a.effectiveness !== "NOT_CHECKED");
  const closed = c.status === "CLOSED";
  const triageDone = c.triage_approved_at !== null;
  const planDone = activePlan?.status === "VERIFIED" && c.status === "IN_PROGRESS";

  return [
    {
      key: "triage",
      label: "Triage",
      state: triageDone ? "done" : "current",
      caption: triageDone ? "Validé" : "À valider",
    },
    {
      key: "plan",
      label: "Plan",
      state: planDone
        ? "done"
        : planBlocked
          ? "blocked"
          : triageDone && !closed
            ? "current"
            : closed
              ? "done"
              : "todo",
      caption: planBlocked ? "Non vérifié" : undefined,
    },
    {
      key: "execution",
      label: "Exécution",
      state: closed ? "done" : started ? "current" : c.status === "IN_PROGRESS" ? "current" : "todo",
    },
    {
      key: "effectiveness",
      label: "Efficacité",
      state: closed ? "done" : checked ? "current" : "todo",
    },
    {
      key: "closure",
      label: "Clôture",
      state: closed ? "done" : "todo",
    },
  ];
}

export default function RemediationCasePage() {
  const { orgId, caseId } = useParams<{ orgId: string; caseId: string }>();
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["remediation-case", orgId, caseId],
    queryFn: () => api.getCase(orgId!, caseId!),
  });
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["remediation-case", orgId, caseId] });

  const draftPlan = useMutation({
    mutationFn: () => api.draftPlan(orgId!, caseId!),
    onSuccess: invalidate,
  });

  if (detail.isError) {
    return <p className="text-sm text-destructive">{(detail.error as Error).message}</p>;
  }
  if (!detail.data) {
    return <p className="text-sm text-muted-foreground">Chargement…</p>;
  }
  const c = detail.data;
  const activePlan = c.plans.find((p) => p.id === c.active_plan_id) ?? null;

  return (
    <div className="space-y-6">
      <div className="space-y-3 border-b pb-4">
        <Link
          to={`/organizations/${orgId}/remediation`}
          className="inline-flex min-h-9 items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          <ArrowLeft className="size-3.5" aria-hidden="true" />
          Gestion des remédiations
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight text-balance md:text-2xl">
            {caseDisplayTitle(c)}
          </h1>
          <CaseStatusBadge status={c.status} />
        </div>
        <WorkflowStrip steps={lifecycleSteps(c, activePlan)} ariaLabel="Cycle de vie du cas" />
      </div>

      <CaseNextAction c={c} activePlan={activePlan} draftPlan={draftPlan} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_290px] lg:items-start">
        <div className="min-w-0 space-y-6">
          <LinkedFindings orgId={orgId!} c={c} onChanged={invalidate} />
          <TriagePanel orgId={orgId!} c={c} onChanged={invalidate} />
          <PlanPanel c={c} orgId={orgId!} activePlan={activePlan} draftPlan={draftPlan} onChanged={invalidate} />
          <ReassessmentPanel orgId={orgId!} c={c} activePlan={activePlan} onChanged={invalidate} />
          <ClosurePanel orgId={orgId!} c={c} onChanged={invalidate} />
          <EventsTimeline c={c} />
        </div>
        <PilotageRail orgId={orgId!} c={c} onChanged={invalidate} />
      </div>
    </div>
  );
}

function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-sm text-destructive">{(error as Error).message}</p>;
}

// -------------------------------------------------------- next action panel

function CaseNextAction({
  c,
  activePlan,
  draftPlan,
}: {
  c: RemediationCaseDetail;
  activePlan: RemediationPlan | null;
  draftPlan: { mutate: () => void; isPending: boolean };
}) {
  const scrollTo = (id: string) => () =>
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  if (c.status === "CLOSED") {
    return (
      <NextActionPanel
        tone="done"
        eyebrow="État du cas"
        title="Cas clôturé"
        description={`Clôturé le ${c.closed_at ? new Date(c.closed_at).toLocaleDateString("fr-FR") : ""}. Le cas reste consultable ; vous pouvez le rouvrir si l'écart réapparaît.`}
      />
    );
  }
  if (c.status === "TRIAGE") {
    const latest = c.triage_drafts[c.triage_drafts.length - 1];
    const abstained = latest?.status === "ABSTAINED";
    return (
      <NextActionPanel
        title={
          abstained
            ? "L'IA n'a pas pu qualifier l'écart — votre qualification est requise"
            : "Valider la qualification proposée par l'IA"
        }
        description="La qualification (nature de l'écart, périmètre) reste une décision humaine ; la proposition de l'IA n'est qu'un point de départ."
        actionLabel="Aller au triage"
        onAction={scrollTo("triage")}
      />
    );
  }
  if (c.status === "TRIAGE_APPROVED") {
    return (
      <NextActionPanel
        title="Lancer la rédaction du plan d'actions"
        description="L'IA rédige un plan dont chaque citation et chaque exigence visée sont vérifiées par le code avant de vous être présentées."
        actionLabel={draftPlan.isPending ? "Rédaction en cours…" : "Lancer la rédaction du plan"}
        onAction={() => draftPlan.mutate()}
        actionDisabled={draftPlan.isPending}
      />
    );
  }
  if (c.status === "PLANNING") {
    return (
      <NextActionPanel
        title="Rédaction du plan en cours"
        description="Le plan sera vérifié par le code avant de vous être présenté."
      />
    );
  }
  if (activePlan?.status === "ABSTAINED") {
    return (
      <NextActionPanel
        tone="attention"
        title="Plan non vérifié"
        description="La dernière rédaction n'a pas passé la vérification — aucune action n'en est issue. Une nouvelle rédaction est requise."
        actionLabel={draftPlan.isPending ? "Rédaction en cours…" : "Relancer la rédaction du plan"}
        onAction={() => draftPlan.mutate()}
        actionDisabled={draftPlan.isPending}
      />
    );
  }
  if (c.status === "PLAN_READY") {
    const pending = (activePlan?.actions ?? []).filter((a) => a.review_status === "PENDING").length;
    return (
      <NextActionPanel
        title={
          pending > 0
            ? `Examiner ${pending} action${pending > 1 ? "s" : ""} proposée${pending > 1 ? "s" : ""}`
            : "Examiner le plan proposé"
        }
        description="Chaque action doit être approuvée, modifiée ou écartée par vous — avec une priorité obligatoire."
        actionLabel="Aller au plan"
        onAction={scrollTo("plan")}
      />
    );
  }
  // IN_PROGRESS — refine from the actions themselves
  const actions = activePlan?.status === "VERIFIED" ? activePlan.actions : [];
  const proposed = actions.filter((a) => a.lifecycle === "PROPOSED").length;
  const approved = actions.filter((a) => a.lifecycle === "APPROVED").length;
  const running = actions.filter((a) => a.lifecycle === "IN_PROGRESS").length;
  const done = actions.filter((a) => a.lifecycle === "DONE");
  const unchecked = done.filter((a) => a.effectiveness === "NOT_CHECKED").length;
  let title = "Faire avancer les actions";
  let description = "Suivez l'exécution des actions validées.";
  if (proposed > 0) {
    title = `Examiner ${proposed} action${proposed > 1 ? "s" : ""} en attente de décision`;
    description = "Des actions proposées par l'IA attendent votre validation.";
  } else if (approved > 0) {
    title = `Lancer ${approved} action${approved > 1 ? "s" : ""} validée${approved > 1 ? "s" : ""}`;
    description = "Des actions validées ne sont pas encore démarrées.";
  } else if (running > 0) {
    title = `Mener ${running} action${running > 1 ? "s" : ""} à terme`;
    description = "Marquez chaque action terminée une fois réalisée.";
  } else if (unchecked > 0) {
    title = "Vérifier l'efficacité des actions terminées";
    description =
      "Enregistrez un verdict d'efficacité — idéalement appuyé par une réévaluation ciblée.";
  } else if (done.length > 0) {
    title = "Clôturer le cas";
    description = "Les actions sont terminées et leur efficacité est enregistrée.";
  }
  return (
    <NextActionPanel
      title={title}
      description={description}
      actionLabel="Aller au plan"
      onAction={scrollTo("plan")}
    />
  );
}

// ------------------------------------------------------------ pilotage rail

/** Case-steering rail: human owner / deadline / closure criterion, editable
    under an optimistic revision check (a concurrent edit is a 409, never a
    silent overwrite). Absent values render honestly. */
function PilotageRail({
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
        <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
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
            <span className="font-mono text-[13px]">{primary.finding_requirement_id}</span>{" "}
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
    <section className="space-y-3 rounded-lg border bg-card p-5">
      <SectionHeading
        as="h2"
        title="Écart confirmé"
        description="Les constats humains qui fondent ce cas."
      />
      <ul className="space-y-2">
        {c.finding_links.map((l) => (
          <li
            key={l.finding_id}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-3 text-sm"
          >
            <span className="font-mono text-xs">{l.finding_requirement_id}</span>
            {l.is_primary && (
              <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-primary">
                principal
              </span>
            )}
            <span className="text-muted-foreground">{l.finding_requirement_fr}</span>
            <StatusLabel display={verdictDisplay(l.finding_human_verdict)} />
            {!l.is_primary && c.status === "TRIAGE" && (
              <button
                onClick={() => unlink.mutate(l.finding_id)}
                className="ml-auto min-h-9 text-xs text-destructive hover:underline"
              >
                Délier
              </button>
            )}
          </li>
        ))}
      </ul>
      {c.status === "TRIAGE" && (suggestions.data?.length ?? 0) > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold text-muted-foreground">
            Lacunes similaires suggérées (décision humaine : lier ou écarter)
          </h3>
          <ul className="space-y-1">
            {suggestions.data!.map((s) => (
              <li
                key={s.finding_id}
                className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/50 p-2 text-sm"
              >
                <span className="font-mono text-xs">{s.requirement_id}</span>
                <span className="text-muted-foreground">{s.requirement_fr}</span>
                {s.same_domain && (
                  <span className="rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-xs text-primary">
                    même domaine
                  </span>
                )}
                <span className="ml-auto flex gap-2">
                  <button
                    onClick={() => link.mutate({ finding_id: s.finding_id, decision: "link" })}
                    className="min-h-9 text-xs font-medium text-primary hover:underline"
                  >
                    Lier
                  </button>
                  <button
                    onClick={() => link.mutate({ finding_id: s.finding_id, decision: "reject" })}
                    className="min-h-9 text-xs text-muted-foreground hover:underline"
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

// ------------------------------------------------------------------ plan

function PlanPanel({
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

// ------------------------------------------------------------ M7b patches

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
  const format = selected ? (selected.filename.toLowerCase().split(".").pop() ?? "") : "";
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
    <div className="space-y-3 rounded-lg border border-primary/20 bg-accent/50 p-3">
      <p className="text-xs font-semibold text-primary">Correctif documentaire</p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={docId}
          onChange={(e) => setDocId(e.target.value)}
          aria-label="Document cible"
          className="min-h-9 rounded-md border border-input px-2 py-1 text-xs"
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
              className="min-h-9 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Proposer un correctif
            </button>
          ) : (
            <button
              onClick={() => proposeArtifact.mutate()}
              disabled={proposeArtifact.isPending}
              className="min-h-9 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Proposer une rédaction (PDF/DOCX)
            </button>
          ))}
      </div>
      {selected && !isTextual && (
        <p className="text-xs text-muted-foreground">
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
    mutationFn: (f: File) => api.supersedeUpload(orgId, f, art.document_version_id, art.id),
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
    <div className="space-y-2 rounded-lg border bg-card p-3 text-xs">
      <p className="font-medium text-foreground/90">
        Proposition de rédaction ({art.canonical_format.toUpperCase()})
      </p>
      <a href={api.artifactDownloadUrl(orgId, c.id, art.id)} className="text-primary underline">
        Télécharger le brouillon Markdown
      </a>
      <p className="text-muted-foreground/80">
        Brouillon IA — préparez le fichier {art.canonical_format.toUpperCase()} révisé, puis
        téléversez-le ici pour créer la nouvelle version (le document original reste inchangé).
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
          className="min-h-9 rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          Téléverser la version révisée
        </button>
      </div>
      {(outcome === "activated" || outcome === "already_active") && (
        <p className="text-success">
          Nouvelle version créée et activée à partir de votre fichier révisé.
        </p>
      )}
      {outcome === "index_failed" && (
        <p className="text-warning-foreground dark:text-warning">
          Indexation vectorielle échouée ; la version est conservée et peut être reprise.
        </p>
      )}
      {outcome === "pending" && (
        <p className="text-warning-foreground dark:text-warning">
          Activation en attente ; vous pouvez la reprendre.
        </p>
      )}
      {outcome === "assessment_conflict" && (
        <p className="text-warning-foreground dark:text-warning">
          Une évaluation est en cours ; réessayez la reprise une fois qu'elle est terminée.
        </p>
      )}
      {outcome.startsWith("abandoned:") && (
        <p className="text-destructive">
          Activation abandonnée — proposition périmée : retéléversez la version révisée.
        </p>
      )}
      {/* stranded on load (survives a refresh), when no in-session outcome shows it */}
      {!inSessionRecoverable && stranded && (
        <p className="text-warning-foreground dark:text-warning">
          Une activation de version (
          {stranded.state === "INDEX_FAILED" ? "échec d'indexation" : "en attente"}) est restée
          inachevée ; vous pouvez la reprendre.
        </p>
      )}
      {recoverVersionId && (
        <button
          onClick={() => recover.mutate(recoverVersionId)}
          disabled={recover.isPending}
          className="min-h-9 rounded-md border border-primary/40 px-3 py-1 text-primary hover:bg-accent disabled:opacity-50"
        >
          Reprendre l'activation
        </button>
      )}
      <ErrorText error={supersede.error || recover.error} />
    </div>
  );
}

const PATCH_DECISION_LABELS: Record<string, string> = {
  approve: "approuvé",
  edit: "approuvé après relecture",
  reject: "rejeté",
};

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
      <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-xs text-warning-foreground dark:text-warning">
        <p className="font-medium">
          Correctif en abstention — {abstainReasonDisplay(p.abstain_reason).label}
        </p>
        <p className="mt-1">
          L'agent n'a pas pu ancrer un correctif fiable ; rédigez la modification manuellement.
        </p>
        <TechnicalDisclosure summary="Détails techniques" className="mt-2">
          <TechnicalRow label="Motif brut" value={p.abstain_reason ?? "—"} />
          {p.verifier_errors?.map((e, i) => <TechnicalRow key={i} label="Vérification" value={e} />)}
        </TechnicalDisclosure>
      </div>
    );
  }
  if (p.status === "DRAFTING") {
    return <p className="text-xs text-muted-foreground">Rédaction du correctif en cours…</p>;
  }

  const resultVersion = (versions.data ?? []).find((v) => v.id === p.decision?.result_version_id);
  const stranded =
    resultVersion &&
    (resultVersion.state === "INDEX_FAILED" || resultVersion.state === "PENDING_INDEX");

  return (
    <div className="space-y-2 rounded-lg border bg-card p-3 text-xs">
      <p className="font-medium text-foreground/90">
        Diff proposé ({p.operation === "replace" ? "remplacement" : "insertion"})
      </p>
      {/* Server-derived source slice at the resolved anchor — never the model quote */}
      <div className="rounded bg-muted/50 p-3 font-mono text-[13px] leading-relaxed">
        <span className="text-muted-foreground/80">{p.context_before}</span>
        <mark className="bg-warning/30 text-foreground">{p.anchor_slice}</mark>
        {p.operation === "insert_after" && (
          <ins className="bg-success/15 text-success no-underline dark:text-success">
            {"\n\n"}
            {editing ? finalText || p.new_text_fr : p.new_text_fr}
          </ins>
        )}
        {p.operation === "replace" && (
          <span className="text-muted-foreground/80 line-through">{/* replaced */}</span>
        )}
        <span className="text-muted-foreground/80">{p.context_after}</span>
      </div>
      {p.operation === "replace" && (
        <div className="rounded bg-success/10 p-3 font-mono text-[13px] text-success">
          → {editing ? finalText || p.new_text_fr : p.new_text_fr}
        </div>
      )}
      <p className="text-muted-foreground">Justification IA : {p.rationale}</p>

      {p.decision ? (
        <div className="rounded bg-muted/50 p-2">
          <p className="font-medium text-muted-foreground">
            Décision : {PATCH_DECISION_LABELS[p.decision.decision] ?? p.decision.decision}
            {resultVersion &&
              ` → version ${resultVersion.version_number} (${versionStateDisplay(resultVersion.state).label})`}
          </p>
          {resultVersion?.state === "ACTIVE" &&
            (resultVersion.canonical_format === "txt" ||
              resultVersion.canonical_format === "md") && (
              <a
                href={api.versionDownloadUrl(p.document_id, resultVersion.id)}
                className="text-primary underline"
              >
                Télécharger la nouvelle version
              </a>
            )}
          {stranded && (
            <button
              onClick={() => recover.mutate()}
              disabled={recover.isPending}
              className="mt-1 min-h-9 rounded-md border border-primary/40 px-2 py-0.5 text-primary hover:bg-accent disabled:opacity-50"
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
              rows={4}
              placeholder="Texte final (votre rédaction sera appliquée telle quelle)"
              className="w-full rounded-md border border-input px-2 py-1 text-sm"
            />
          )}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => decide.mutate({ decision: "approve" })}
              disabled={decide.isPending}
              className="min-h-9 rounded-md bg-success px-3 py-1 font-medium text-success-foreground hover:bg-success/90 disabled:opacity-50"
            >
              Approuver le correctif
            </button>
            {editing ? (
              <button
                onClick={() => decide.mutate({ decision: "edit", final_text_fr: finalText })}
                disabled={decide.isPending || !finalText.trim()}
                className="min-h-9 rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                Appliquer ma rédaction
              </button>
            ) : (
              <button
                onClick={() => {
                  setFinalText(p.new_text_fr ?? "");
                  setEditing(true);
                }}
                className="min-h-9 rounded-md border border-input px-3 py-1 hover:bg-muted/50"
              >
                Modifier le texte
              </button>
            )}
            <button
              onClick={() => decide.mutate({ decision: "reject" })}
              disabled={decide.isPending}
              className="min-h-9 rounded-md border border-input px-3 py-1 hover:bg-muted/50"
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

const REASSESSMENT_STATUS_LABELS: Record<string, string> = {
  PENDING: "En attente de lancement",
  LAUNCHED: "Réévaluation lancée",
  LAUNCH_FAILED: "Échec du lancement",
};

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

  if (doneActions.length === 0 && (reassessments.data?.length ?? 0) === 0) return null;

  return (
    <section className="space-y-3 rounded-lg border bg-card p-5">
      <SectionHeading
        as="h2"
        title="Réévaluations ciblées"
        description="Une réévaluation confirmée est la meilleure preuve d'efficacité d'une action."
      />
      {doneActions.length > 0 && c.status === "IN_PROGRESS" && (
        <div className="space-y-2 text-sm">
          {doneActions.map((a) => (
            <label key={a.id} className="flex min-h-9 items-center gap-2">
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
            className="min-h-10 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Lancer une réévaluation
          </button>
        </div>
      )}
      {(reassessments.data?.length ?? 0) > 0 && (
        <ul className="space-y-2 text-sm">
          {reassessments.data!.map((r) => (
            <li key={r.id} className="rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
                  {REASSESSMENT_STATUS_LABELS[r.status] ?? "Réévaluation"}
                </span>
                {r.assessment_id && (
                  <Link
                    to={`/organizations/${orgId}/assessments/${r.assessment_id}`}
                    className="text-xs text-primary hover:underline"
                  >
                    Voir l'évaluation
                  </Link>
                )}
                <span className="text-xs text-muted-foreground">
                  {new Date(r.created_at).toLocaleString("fr-FR")}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Exigences réévaluées : {r.included_requirement_ids.join(", ") || "—"}
              </p>
              {r.excluded_holdout_ids.length > 0 && (
                <p className="mt-1 text-xs text-warning-foreground dark:text-warning">
                  Exclues (réservées au jeu de test de référence, jamais réévaluées ici) :{" "}
                  {r.excluded_holdout_ids.join(", ")}
                </p>
              )}
              {r.error && <p className="mt-1 text-xs text-destructive">{r.error}</p>}
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
      <section className="space-y-2 rounded-lg border bg-card p-5">
        <SectionHeading as="h2" title="Clôture" />
        <p className="text-sm">
          Clôturé le {c.closed_at ? new Date(c.closed_at).toLocaleString("fr-FR") : ""} —{" "}
          {c.close_note}
        </p>
        <button
          onClick={() => reopen.mutate()}
          disabled={reopen.isPending}
          className="min-h-10 rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted/50 disabled:opacity-50"
        >
          Rouvrir le cas
        </button>
        <ErrorText error={reopen.error} />
      </section>
    );
  }
  if (!["TRIAGE_APPROVED", "PLAN_READY", "IN_PROGRESS"].includes(c.status)) return null;

  // Server-derived closure-readiness RECOMMENDATIONS — advisory only, the
  // backend does not enforce them at closure (and the UI must not claim so).
  const recommendations = (c.workflow?.closure.recommendations ?? []).filter(
    // keep the plan-level blocker to the plan panel; the closure hints focus
    // on actions and effectiveness
    (k) => k in CLOSURE_RECOMMENDATIONS,
  );

  return (
    <section className="space-y-3 rounded-lg border bg-card p-5">
      <SectionHeading as="h2" title="Clôture" />
      {c.closure_criterion && (
        <p className="text-xs text-muted-foreground">
          Critère de clôture défini : {c.closure_criterion}
        </p>
      )}
      {recommendations.length > 0 && (
        <p className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-warning-foreground dark:text-warning">
          Recommandé avant clôture (non bloquant) :{" "}
          {recommendations.map((k) => CLOSURE_RECOMMENDATIONS[k]).join(" · ")}.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Note de clôture (requise)"
          className="min-h-10 min-w-64 flex-1 rounded-md border border-input px-2 py-1.5 text-sm"
        />
        <button
          onClick={() => close.mutate()}
          disabled={close.isPending || !note.trim()}
          className="min-h-10 rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted/50 disabled:opacity-50"
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
    <section className="space-y-4 rounded-lg border bg-card p-5">
      <SectionHeading
        as="h2"
        title="Journal d'audit"
        description="Chaque étape du cas, dans l'ordre — rien ne s'efface."
      />
      <ol className="relative space-y-4 border-l border-border pl-5">
        {[...c.events].reverse().map((e) => (
          <li key={e.sequence} className="relative text-xs text-muted-foreground">
            <span
              aria-hidden
              className="absolute top-1 -left-[calc(1.25rem+3.5px)] size-2 rounded-full border border-background bg-primary/70"
            />
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="font-medium text-foreground">{eventTypeLabel(e.event_type)}</span>
              <span>{new Date(e.created_at).toLocaleString("fr-FR")}</span>
              {e.actor_label && (
                <span className="text-muted-foreground/80">par {e.actor_label} (non vérifié)</span>
              )}
            </div>
          </li>
        ))}
      </ol>
      <TechnicalDisclosure summary="Détails techniques du journal">
        <ul className="space-y-1">
          {[...c.events].reverse().map((e) => (
            <li key={e.sequence} className="font-mono text-xs">
              #{e.sequence} {e.event_type} (v{e.payload_version})
            </li>
          ))}
        </ul>
      </TechnicalDisclosure>
    </section>
  );
}
