import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export interface WorkflowStep {
  key: string;
  label: string;
  /** Optional short annotation under the label (count, state…). */
  caption?: string;
  state: "done" | "current" | "todo" | "blocked";
}

/**
 * Compact horizontal lifecycle strip — the product's mental model
 * (Préparer → Évaluer → Confirmer → Prioriser → Agir → Clôturer) or a
 * remediation case's phases. Scrolls horizontally on narrow screens instead
 * of overflowing the page.
 */
export function WorkflowStrip({
  steps,
  ariaLabel = "Étapes du parcours",
  className,
}: {
  steps: WorkflowStep[];
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <ol
      aria-label={ariaLabel}
      className={cn(
        "flex items-stretch gap-0 overflow-x-auto rounded-lg border bg-card",
        className,
      )}
    >
      {steps.map((step, i) => (
        <li
          key={step.key}
          aria-current={step.state === "current" ? "step" : undefined}
          className={cn(
            "flex min-w-32 flex-1 items-center gap-2.5 px-4 py-3",
            i > 0 && "border-l",
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              "flex size-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-semibold tabular-nums",
              step.state === "done" && "border-success/40 bg-success/10 text-success",
              step.state === "current" && "border-primary bg-primary text-primary-foreground",
              step.state === "todo" && "border-border bg-muted text-muted-foreground",
              step.state === "blocked" && "border-warning/50 bg-warning/10 text-warning-foreground",
            )}
          >
            {step.state === "done" ? <Check className="size-3" aria-hidden="true" /> : i + 1}
          </span>
          <span className="min-w-0">
            <span
              className={cn(
                "block truncate text-[13px] leading-tight font-medium",
                step.state === "todo" && "text-muted-foreground",
              )}
            >
              {step.label}
            </span>
            {step.caption ? (
              <span className="block truncate text-xs leading-tight text-muted-foreground">
                {step.caption}
              </span>
            ) : null}
            <span className="sr-only">
              {step.state === "done"
                ? " — terminé"
                : step.state === "current"
                  ? " — étape en cours"
                  : step.state === "blocked"
                    ? " — bloqué"
                    : " — à venir"}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}
