import type { Verdict } from "../api";
import { Badge } from "@/components/ui/badge";

// Semantic status accents, always paired with a text label (never color-only).
const VERDICT_STYLES: Record<
  Verdict,
  { label: string; variant: "success" | "warning" | "danger" | "neutral"; dot: string }
> = {
  compliant: { label: "Conforme", variant: "success", dot: "bg-success" },
  partial: { label: "Partiel", variant: "warning", dot: "bg-warning" },
  non_compliant: { label: "Non conforme", variant: "danger", dot: "bg-destructive" },
  missing: { label: "Preuve insuffisante", variant: "neutral", dot: "bg-muted-foreground" },
};

export default function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return null;
  const s = VERDICT_STYLES[verdict];
  return (
    <Badge variant={s.variant} className="gap-1.5">
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </Badge>
  );
}
