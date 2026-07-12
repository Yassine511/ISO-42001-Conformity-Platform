import { Settings2, TriangleAlert } from "lucide-react";
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
 * Tests assert the hue names ("amber" / "slate") in the class list.
 */
export default function AbstainReasonLabel({ reason }: { reason: string | null }) {
  if (!reason) return null;
  const infra = isInfraAbstain(reason);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${
        infra
          ? "border-slate-500/20 bg-slate-200 text-slate-600 dark:border-slate-400/20 dark:bg-slate-400/10 dark:text-slate-300"
          : "border-amber-600/20 bg-amber-100 text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-300"
      }`}
    >
      {infra ? (
        <Settings2 className="size-3 shrink-0" aria-hidden="true" />
      ) : (
        <TriangleAlert className="size-3 shrink-0" aria-hidden="true" />
      )}
      {REASON_LABELS[reason] ?? reason}
    </span>
  );
}
