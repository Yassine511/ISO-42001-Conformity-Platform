/**
 * Central user-language module — the ONLY place internal enums become visible
 * French text. Pages must never render a raw backend value (`partial`,
 * `TRIAGE_APPROVED`, `verification_failed`, pipeline node names, …) outside a
 * collapsed « Détails techniques » disclosure.
 *
 * Every lookup falls back to a neutral French phrase (never the raw value) so
 * an unknown future enum cannot leak jargon into the interface. The raw value
 * stays available to callers that want to show it inside a technical
 * disclosure.
 */

import type {
  ActionLifecycle,
  AssessmentStatus,
  CaseStatus,
  Classification,
  Effectiveness,
  FindingStatus,
  RemediationCase,
  RemediationScope,
  ReviewAction,
  Severity,
  Verdict,
} from "../api";

export type Tone = "success" | "warning" | "danger" | "neutral" | "info";

export interface Display {
  label: string;
  tone: Tone;
  /** Optional one-line human explanation for panels / tooltips. */
  hint?: string;
}

const UNKNOWN: Display = { label: "État inconnu", tone: "neutral" };

function lookup<K extends string>(table: Record<K, Display>, value: K | null | undefined): Display {
  if (!value) return UNKNOWN;
  return table[value] ?? UNKNOWN;
}

// ------------------------------------------------------------------ verdicts

export const VERDICTS: Record<Verdict, Display> = {
  compliant: { label: "Conforme", tone: "success" },
  partial: { label: "Partiellement conforme", tone: "warning" },
  non_compliant: { label: "Non conforme", tone: "danger" },
  missing: { label: "Preuve absente", tone: "neutral" },
};

export const verdictDisplay = (v: Verdict | null | undefined): Display => lookup(VERDICTS, v);

/** Whether a confirmed human verdict constitutes a gap (opens remediation). */
export const isGapVerdict = (v: Verdict | null | undefined): boolean =>
  v === "partial" || v === "non_compliant" || v === "missing";

// ------------------------------------------------------- assessment statuses

export const ASSESSMENT_STATUSES: Record<AssessmentStatus, Display> = {
  RUNNING: { label: "Évaluation en cours", tone: "info" },
  COMPLETED: { label: "Terminée", tone: "success" },
  FAILED: { label: "Échouée", tone: "danger" },
};

export const assessmentStatusDisplay = (s: AssessmentStatus | null | undefined): Display =>
  lookup(ASSESSMENT_STATUSES, s);

// ------------------------------------------------------------ AI finding gate

export const FINDING_STATUSES: Record<FindingStatus, Display> = {
  VERIFIED: {
    label: "Citation localisée",
    tone: "success",
    hint: "La citation existe mot pour mot dans le document — la pertinence reste à confirmer par un humain.",
  },
  ABSTAINED: {
    label: "IA sans réponse fiable",
    tone: "warning",
    hint: "L'IA n'a pas produit de constat vérifiable — votre jugement remplace le sien.",
  },
};

export const findingStatusDisplay = (s: FindingStatus | null | undefined): Display =>
  lookup(FINDING_STATUSES, s);

// ----------------------------------------------------------- review lifecycle

export const REVIEW_STATUSES: Record<"PENDING" | "CONFIRMED", Display> = {
  PENDING: { label: "À examiner", tone: "warning" },
  CONFIRMED: { label: "Confirmé", tone: "success" },
};

export const reviewStatusDisplay = (s: "PENDING" | "CONFIRMED" | null | undefined): Display =>
  lookup(REVIEW_STATUSES, s);

export const REVIEW_ACTIONS: Record<ReviewAction, Display> = {
  approve: { label: "Verdict IA confirmé", tone: "success" },
  edit: { label: "Justification modifiée", tone: "neutral" },
  override: { label: "Verdict remplacé", tone: "neutral" },
};

export const reviewActionDisplay = (a: ReviewAction | null | undefined): Display =>
  lookup(REVIEW_ACTIONS, a);

// --------------------------------------------------------- abstention reasons

/** Pipeline / chat / remediation abstention reasons, in user language. */
export const ABSTAIN_REASONS: Record<string, Display> = {
  model_abstained: {
    label: "Aucune preuve trouvée",
    tone: "warning",
    hint: "L'IA n'a trouvé aucun passage pertinent — à traiter comme un écart potentiel.",
  },
  verification_failed: {
    label: "Citations non vérifiables",
    tone: "warning",
    hint: "Les citations proposées ne correspondent à aucun passage exact des documents.",
  },
  fuzzy_citation: {
    label: "Citation approximative",
    tone: "warning",
    hint: "Un passage proche existe mais ne correspond pas exactement — vérification humaine prioritaire.",
  },
  low_confidence: { label: "Confiance insuffisante", tone: "warning" },
  schema_invalid: {
    label: "Réponse IA inexploitable",
    tone: "warning",
    hint: "La réponse du modèle n'a pas respecté le format attendu.",
  },
  llm_error: { label: "Service IA indisponible", tone: "neutral" },
  rate_limited: { label: "Service IA saturé — réessayez", tone: "neutral" },
  retrieval_error: { label: "Recherche documentaire interrompue", tone: "neutral" },
  draft_interrupted: { label: "Rédaction interrompue", tone: "neutral" },
  anchor_not_found: {
    label: "Point d'insertion introuvable",
    tone: "warning",
    hint: "Le passage d'ancrage proposé n'existe pas tel quel dans le document.",
  },
  anchor_ambiguous: {
    label: "Point d'insertion ambigu",
    tone: "warning",
    hint: "Le passage d'ancrage apparaît plusieurs fois dans le document.",
  },
  no_documents: { label: "Aucun document préparé", tone: "neutral" },
  no_results: { label: "Aucun passage pertinent trouvé", tone: "warning" },
};

export const abstainReasonDisplay = (reason: string | null | undefined): Display => {
  if (!reason) return UNKNOWN;
  return (
    ABSTAIN_REASONS[reason] ?? {
      label: "Réponse IA non exploitable",
      tone: "warning",
    }
  );
};

// --------------------------------------------------------- remediation cases

export const CASE_STATUSES: Record<CaseStatus, Display> = {
  TRIAGE: { label: "Qualification de l'écart", tone: "warning" },
  TRIAGE_APPROVED: { label: "Triage terminé", tone: "info" },
  PLANNING: { label: "Rédaction du plan", tone: "info" },
  PLAN_READY: { label: "Plan à examiner", tone: "warning" },
  IN_PROGRESS: { label: "Actions en cours", tone: "info" },
  CLOSED: { label: "Clôturé", tone: "success" },
};

export const caseStatusDisplay = (s: CaseStatus | null | undefined): Display =>
  lookup(CASE_STATUSES, s);

export const CLASSIFICATIONS: Record<Classification, Display> = {
  nonconformity: { label: "Non-conformité", tone: "danger" },
  evidence_gap: { label: "Preuve manquante", tone: "warning" },
  observation: { label: "Observation", tone: "neutral" },
  improvement_opportunity: { label: "Piste d'amélioration", tone: "neutral" },
};

export const classificationDisplay = (c: Classification | null | undefined): Display =>
  lookup(CLASSIFICATIONS, c);

export const REMEDIATION_SCOPES: Record<RemediationScope, Display> = {
  local: { label: "Exigence concernée uniquement", tone: "neutral" },
  related_requirements: { label: "Exigences liées", tone: "neutral" },
  organization_wide: { label: "Toute l'organisation", tone: "neutral" },
};

export const remediationScopeDisplay = (s: RemediationScope | null | undefined): Display =>
  lookup(REMEDIATION_SCOPES, s);

export const ACTION_LIFECYCLES: Record<ActionLifecycle, Display> = {
  PROPOSED: { label: "Proposée par l'IA", tone: "warning" },
  APPROVED: { label: "Validée — à lancer", tone: "info" },
  REJECTED: { label: "Écartée", tone: "neutral" },
  IN_PROGRESS: { label: "En cours", tone: "info" },
  DONE: { label: "Réalisée", tone: "success" },
  CANCELLED: { label: "Annulée", tone: "neutral" },
};

export const actionLifecycleDisplay = (l: ActionLifecycle | null | undefined): Display =>
  lookup(ACTION_LIFECYCLES, l);

export const EFFECTIVENESS: Record<Effectiveness, Display> = {
  NOT_CHECKED: { label: "Efficacité non vérifiée", tone: "neutral" },
  EFFECTIVE: { label: "Efficace", tone: "success" },
  PARTIALLY_EFFECTIVE: { label: "Partiellement efficace", tone: "warning" },
  INEFFECTIVE: { label: "Inefficace", tone: "danger" },
};

export const effectivenessDisplay = (e: Effectiveness | null | undefined): Display =>
  lookup(EFFECTIVENESS, e);

export const ACTION_TYPES: Record<string, string> = {
  document_amendment: "Amendement de document",
  new_document: "Nouveau document",
  process_change: "Changement de processus",
  training: "Formation",
  risk_treatment_update: "Mise à jour du traitement des risques",
  other: "Autre action",
};

export const actionTypeLabel = (t: string | null | undefined): string =>
  (t && ACTION_TYPES[t]) || "Autre action";

export const PRIORITIES: Record<string, Display> = {
  haute: { label: "Priorité haute", tone: "danger" },
  normale: { label: "Priorité normale", tone: "neutral" },
  basse: { label: "Priorité basse", tone: "neutral" },
};

export const priorityDisplay = (p: string | null | undefined): Display => {
  if (!p) return { label: "Priorité à définir", tone: "warning" };
  return PRIORITIES[p] ?? { label: "Priorité à définir", tone: "warning" };
};

// -------------------------------------------------------- plan-level statuses

export const PLAN_STATUSES: Record<string, Display> = {
  VERIFIED: {
    label: "Plan vérifié",
    tone: "success",
    hint: "Toutes les citations et exigences du plan ont été vérifiées par le code.",
  },
  ABSTAINED: {
    label: "Plan non vérifié",
    tone: "warning",
    hint: "Une nouvelle rédaction est requise.",
  },
  SUPERSEDED: { label: "Plan remplacé", tone: "neutral" },
};

export const planStatusDisplay = (s: string | null | undefined): Display =>
  s ? (PLAN_STATUSES[s] ?? UNKNOWN) : UNKNOWN;

// ------------------------------------------------------------- reassessments

export const REASSESSMENT_STATUSES: Record<string, Display> = {
  PENDING: { label: "Réévaluation en préparation", tone: "neutral" },
  LAUNCHED: { label: "Réévaluation lancée", tone: "info" },
  LAUNCH_FAILED: { label: "Lancement de la réévaluation échoué", tone: "danger" },
};

export const reassessmentStatusDisplay = (s: string | null | undefined): Display =>
  s ? (REASSESSMENT_STATUSES[s] ?? UNKNOWN) : UNKNOWN;

// ----------------------------------------------------- documents & versions

export const DOC_STATUSES: Record<string, Display> = {
  uploaded: { label: "Reçu — analyse en attente", tone: "neutral" },
  parsed: { label: "Prêt pour l'évaluation", tone: "success" },
  failed: { label: "Analyse échouée", tone: "danger" },
};

export const docStatusDisplay = (s: string | null | undefined): Display =>
  s ? (DOC_STATUSES[s] ?? UNKNOWN) : UNKNOWN;

export const VERSION_STATES: Record<string, Display> = {
  ACTIVE: { label: "Version active", tone: "success" },
  SUPERSEDED: { label: "Version remplacée", tone: "neutral" },
  PENDING_INDEX: { label: "Indexation en attente", tone: "warning" },
  INDEX_FAILED: { label: "Indexation échouée", tone: "danger" },
  ABANDONED: { label: "Version abandonnée", tone: "neutral" },
};

export const versionStateDisplay = (s: string | null | undefined): Display =>
  s ? (VERSION_STATES[s] ?? UNKNOWN) : UNKNOWN;

export const PATCH_STATUSES: Record<string, Display> = {
  DRAFTING: { label: "Rédaction en cours", tone: "info" },
  VERIFIED: { label: "Proposition vérifiée", tone: "success" },
  ABSTAINED: { label: "Proposition non vérifiée", tone: "warning" },
};

export const patchStatusDisplay = (s: string | null | undefined): Display =>
  s ? (PATCH_STATUSES[s] ?? UNKNOWN) : UNKNOWN;

export const ACTIVATION_OUTCOMES: Record<string, Display> = {
  activated: { label: "Nouvelle version activée", tone: "success" },
  already_active: { label: "Version déjà active", tone: "success" },
  rejected: { label: "Proposition écartée", tone: "neutral" },
  pending: { label: "Activation en attente", tone: "warning" },
  assessment_conflict: {
    label: "Évaluation en cours — activation reportée",
    tone: "warning",
  },
  index_failed: { label: "Indexation échouée — réessayez", tone: "danger" },
};

export const activationOutcomeDisplay = (outcome: string | null | undefined): Display => {
  if (!outcome) return UNKNOWN;
  if (outcome.startsWith("abandoned:")) {
    return { label: "Activation abandonnée — proposition périmée", tone: "warning" };
  }
  return ACTIVATION_OUTCOMES[outcome] ?? UNKNOWN;
};

// ----------------------------------------------------------------- reporting

export const SEVERITIES: Record<Severity, Display> = {
  high: { label: "Sévérité haute", tone: "danger" },
  medium: { label: "Sévérité moyenne", tone: "warning" },
  low: { label: "Sévérité faible", tone: "neutral" },
};

export const severityDisplay = (s: Severity | null | undefined): Display =>
  s ? (SEVERITIES[s] ?? { label: "Sévérité non calculée", tone: "neutral" }) : {
    label: "Sévérité non calculée",
    tone: "neutral",
  };

export const SOA_EVAL_STATUSES: Record<string, Display> = {
  conforme: { label: "Conforme", tone: "success" },
  ecart: { label: "Écart confirmé", tone: "danger" },
  non_evalue: { label: "Non évalué", tone: "neutral" },
};

export const soaEvalStatusDisplay = (s: string | null | undefined): Display =>
  s ? (SOA_EVAL_STATUSES[s] ?? UNKNOWN) : UNKNOWN;

// --------------------------------------------------------------- chat scopes

export const EVIDENCE_SCOPES: Record<string, string> = {
  policy: "Documents de l'organisation",
  kb_only: "Norme ISO/IEC 42001 uniquement",
  mixed: "Documents et norme ISO/IEC 42001",
};

export const evidenceScopeLabel = (s: string | null | undefined): string =>
  (s && EVIDENCE_SCOPES[s]) || "Périmètre non précisé";

export const CLAIM_KINDS: Record<string, string> = {
  organization: "D'après vos documents",
  standard: "D'après la norme",
};

// -------------------------------------------------------------- audit events

/** remediation_events / document_version_events → human timeline labels
    (kept in sync with backend REMEDIATION_EVENT_TYPES). */
export const EVENT_TYPES: Record<string, string> = {
  case_created: "Cas ouvert",
  case_closed: "Cas clôturé",
  case_reopened: "Cas rouvert",
  finding_linked: "Constat rattaché",
  finding_unlinked: "Constat détaché",
  finding_link_rejected: "Suggestion de rattachement écartée",
  triage_drafted: "Analyse de triage rédigée par l'IA",
  triage_approved: "Triage validé",
  triage_reopened: "Triage rouvert",
  plan_draft_started: "Rédaction du plan lancée",
  plan_drafted: "Plan rédigé par l'IA",
  plan_abstained: "Rédaction du plan non vérifiée",
  plan_superseded: "Plan remplacé",
  plan_draft_recovered: "Rédaction du plan interrompue puis récupérée",
  action_reviewed: "Action examinée par un humain",
  lifecycle_changed: "Avancement de l'action mis à jour",
  effectiveness_recorded: "Efficacité de l'action enregistrée",
  reassessment_launched: "Réévaluation lancée",
  case_planning_updated: "Pilotage du cas mis à jour",
  patch_proposed: "Modification de document proposée",
  patch_abstained: "Proposition de modification non vérifiée",
  patch_approved: "Modification approuvée",
  patch_rejected: "Modification écartée",
  patch_activation_abandoned: "Activation de la modification abandonnée",
  artifact_created: "Document de travail généré",
  artifact_abstained: "Génération du document de travail non vérifiée",
  version_superseded_by_upload: "Version remplacée par un nouveau dépôt",
  version_indexed: "Nouvelle version indexée",
  version_activated: "Nouvelle version activée",
};

export const eventTypeLabel = (t: string | null | undefined): string =>
  (t && EVENT_TYPES[t]) || "Événement d'audit";

// ------------------------------------------------------------ pipeline nodes

/** Live assessment progress — pipeline node → what the system is doing. */
export const PIPELINE_NODES: Record<string, string> = {
  retrieve: "Recherche des passages pertinents",
  judge: "Analyse de la conformité",
  verify: "Vérification des citations",
  repair: "Correction des citations",
  persist: "Enregistrement des constats",
};

export const pipelineNodeLabel = (node: string | null | undefined): string =>
  (node && PIPELINE_NODES[node]) || "Traitement en cours";

// ------------------------------------------------------- missing-data honesty

/** Honest placeholders — never fabricate owners, deadlines or criteria. */
export const MISSING = {
  owner: "Non attribué",
  deadline: "À définir",
  value: "Non renseigné",
} as const;

// ------------------------------------------------------------- next actions

/** Workflow next-action keys (frontend-derived today, backend-provided later). */
export const NEXT_ACTIONS: Record<string, string> = {
  review_triage: "Valider le triage",
  draft_plan: "Lancer la rédaction du plan",
  wait_planning: "Rédaction du plan en cours",
  redraft_plan: "Relancer la rédaction du plan",
  review_actions: "Examiner les actions proposées",
  launch_actions: "Lancer les actions validées",
  complete_actions: "Mener les actions à terme",
  check_effectiveness: "Vérifier l'efficacité",
  close_case: "Clôturer le cas",
  reopen_case: "Rouvrir le cas si nécessaire",
};

/** Closure-readiness recommendation keys (server-derived, advisory only). */
export const CLOSURE_RECOMMENDATIONS: Record<string, string> = {
  no_verified_plan: "Aucun plan vérifié n'est actif",
  open_actions: "Des actions sont encore ouvertes",
  unchecked_effectiveness: "Des actions terminées n'ont pas de verdict d'efficacité",
};

export const nextActionLabel = (k: string | null | undefined): string =>
  (k && NEXT_ACTIONS[k]) || "Poursuivre le traitement";

/** Per-status next action for a remediation case (list-level knowledge only —
    the case page refines this with plan/action detail). */
export const CASE_NEXT_ACTIONS: Record<CaseStatus, string> = {
  TRIAGE: "Valider le triage",
  TRIAGE_APPROVED: "Lancer la rédaction du plan",
  PLANNING: "Attendre la fin de la rédaction",
  PLAN_READY: "Examiner les actions proposées",
  IN_PROGRESS: "Faire avancer les actions",
  CLOSED: "Aucune — cas clôturé",
};

/** Human-readable case title — backend titles like « Remédiation A.7.2 —
    partial » never render. Built from the primary linked finding. */
export function caseDisplayTitle(
  c: Pick<RemediationCase, "title" | "finding_links">,
): string {
  const primary = c.finding_links.find((l) => l.is_primary) ?? c.finding_links[0];
  if (primary) {
    return `Remédiation de l'exigence ${primary.finding_requirement_id} — ${verdictDisplay(primary.finding_human_verdict).label.toLowerCase()}`;
  }
  // strip a trailing raw-verdict suffix from legacy backend titles
  const m = /^(.*?)\s*—\s*(partial|non_compliant|missing|compliant)\s*$/.exec(c.title);
  return m ? m[1] : c.title;
}
