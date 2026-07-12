import { Check } from "lucide-react";
import type { AssessmentStatus } from "../api";

const ASSESSMENT_STYLES: Record<AssessmentStatus, { label: string; className: string }> = {
  RUNNING: {
    label: "En cours",
    className:
      "border-primary/20 bg-accent text-accent-foreground",
  },
  COMPLETED: {
    label: "Terminée",
    className:
      "border-emerald-600/20 bg-emerald-100 text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-300",
  },
  FAILED: {
    label: "Échouée",
    className:
      "border-red-600/20 bg-red-100 text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-300",
  },
};

export function AssessmentStatusBadge({ status }: { status: AssessmentStatus }) {
  const s = ASSESSMENT_STYLES[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${s.className}`}
    >
      {status === "RUNNING" && (
        <span aria-hidden className="h-2 w-2 animate-pulse rounded-full bg-primary" />
      )}
      {s.label}
    </span>
  );
}

export function ReviewStatusBadge({ status }: { status: "PENDING" | "CONFIRMED" }) {
  return status === "CONFIRMED" ? (
    <span className="inline-flex items-center gap-1 rounded-full border border-emerald-600/20 bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-300">
      <Check className="size-3" aria-hidden="true" />
      Confirmé
    </span>
  ) : (
    <span className="inline-flex items-center rounded-full border border-border bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
      À examiner
    </span>
  );
}
