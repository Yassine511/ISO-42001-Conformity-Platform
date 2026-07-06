import { isInfraAbstain } from "../api";

const REASON_LABELS: Record<string, string> = {
  model_abstained: "Le modèle n'a trouvé aucune preuve",
  verification_failed: "Citations non vérifiables",
  fuzzy_citation: "Citation approximative — vérification humaine prioritaire",
  low_confidence: "Confiance insuffisante",
  llm_error: "Échec technique du fournisseur LLM",
  rate_limited: "Fournisseur LLM saturé (réessayez)",
};

/**
 * Infrastructure abstentions (llm_error/rate_limited) are neutral service
 * failures — never amber "needs your judgment".
 */
export default function AbstainReasonLabel({ reason }: { reason: string | null }) {
  if (!reason) return null;
  const infra = isInfraAbstain(reason);
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        infra ? "bg-slate-200 text-slate-600" : "bg-amber-100 text-amber-800"
      }`}
    >
      {infra ? "⚙ " : "⚠ "}
      {REASON_LABELS[reason] ?? reason}
    </span>
  );
}
