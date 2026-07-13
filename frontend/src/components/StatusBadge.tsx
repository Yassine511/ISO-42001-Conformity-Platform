import { Check } from "lucide-react";
import type { AssessmentStatus } from "../api";
import { Badge } from "@/components/ui/badge";

const ASSESSMENT_STYLES: Record<
  AssessmentStatus,
  { label: string; variant: "outline" | "success" | "danger" }
> = {
  RUNNING: { label: "En cours", variant: "outline" },
  COMPLETED: { label: "Terminée", variant: "success" },
  FAILED: { label: "Échouée", variant: "danger" },
};

export function AssessmentStatusBadge({ status }: { status: AssessmentStatus }) {
  const s = ASSESSMENT_STYLES[status];
  return (
    <Badge variant={s.variant} className="gap-1.5">
      {status === "RUNNING" && (
        <span aria-hidden className="h-2 w-2 animate-pulse rounded-full bg-foreground" />
      )}
      {s.label}
    </Badge>
  );
}

export function ReviewStatusBadge({ status }: { status: "PENDING" | "CONFIRMED" }) {
  return status === "CONFIRMED" ? (
    <Badge variant="success" className="gap-1">
      <Check className="size-3" aria-hidden="true" />
      Confirmé
    </Badge>
  ) : (
    <Badge variant="neutral">À examiner</Badge>
  );
}
