// Remediation case workspace — the page shell.
//
// The panels live in ./remediation-case/: this file owns the data query, the
// lifecycle stepper and the next-action panel (both of which read the WHOLE
// case), and composes the rest. Panels are imported individually rather than
// through a barrel so the page's dependency list stays readable.
import { Link, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { api, type RemediationCaseDetail, type RemediationPlan } from "../api";
import { caseDisplayTitle } from "@/lib/labels";
import { CaseStatusBadge } from "./RemediationListPage";
import { NextActionPanel } from "@/components/next-action-panel";
import { WorkflowStrip, type WorkflowStep } from "@/components/workflow-strip";
import { ClosurePanel } from "./remediation-case/closure-panel";
import { EventsTimeline } from "./remediation-case/events-timeline";
import { LinkedFindings } from "./remediation-case/linked-findings";
import { PilotageRail } from "./remediation-case/pilotage-rail";
import { PlanPanel } from "./remediation-case/plan-panel";
import { ReassessmentPanel } from "./remediation-case/reassessment-panel";
import { TriagePanel } from "./remediation-case/triage-panel";

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
