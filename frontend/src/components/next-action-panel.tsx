import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The dominant "what should I do next?" panel — one per page, above charts
 * and tables. Ink rule on the left, a single primary (cobalt) action, and an
 * optional quiet secondary action.
 */
export function NextActionPanel({
  eyebrow = "Prochaine action",
  title,
  description,
  actionLabel,
  actionTo,
  onAction,
  actionDisabled,
  secondary,
  icon: Icon,
  tone = "default",
  children,
  className,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  actionLabel?: string;
  /** Route target — rendered as a Link when provided. */
  actionTo?: string;
  onAction?: () => void;
  actionDisabled?: boolean;
  /** Optional quiet secondary control (link or button). */
  secondary?: ReactNode;
  icon?: LucideIcon;
  /** "attention" adds an amber left rule for blocked / failed states. */
  tone?: "default" | "attention" | "done";
  children?: ReactNode;
  className?: string;
}) {
  const accent =
    tone === "attention"
      ? { border: "border-warning/55", tile: "bg-warning/15 text-warning-foreground dark:text-warning", eyebrow: "text-warning-foreground dark:text-warning" }
      : tone === "done"
        ? { border: "border-success/55 bg-success/[0.05]", tile: "bg-success/15 text-success", eyebrow: "text-success" }
          // light: ink rule; dark: cobalt (an inverted ink border reads as a
        // stark white box — the design specifies cobalt on dark surfaces)
      : { border: "border-ink dark:border-primary", tile: "bg-primary/10 text-primary", eyebrow: "text-primary" };
  return (
    <section
      aria-label={eyebrow}
      className={cn(
        "relative overflow-hidden rounded-xl border-[1.5px] bg-card",
        accent.border,
        className,
      )}
    >
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:gap-6 sm:px-6">
        {Icon ? (
          <span
            aria-hidden="true"
            className={cn(
              "flex size-11 shrink-0 items-center justify-center rounded-[11px]",
              accent.tile,
            )}
          >
            <Icon className="size-5" />
          </span>
        ) : null}
        <div className="min-w-0 flex-1 space-y-1">
          <p className={cn("text-[11px] font-semibold tracking-[0.15em] uppercase", accent.eyebrow)}>
            {eyebrow}
          </p>
          <h2 className="font-sans text-lg font-semibold tracking-tight text-balance">{title}</h2>
          {description ? (
            <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">{description}</p>
          ) : null}
          {children}
        </div>
        {(actionLabel || secondary) && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {secondary}
            {actionLabel &&
              (actionTo ? (
                <Button asChild disabled={actionDisabled}>
                  <Link to={actionTo}>
                    {actionLabel}
                    <ArrowRight aria-hidden="true" />
                  </Link>
                </Button>
              ) : (
                <Button onClick={onAction} disabled={actionDisabled}>
                  {actionLabel}
                  <ArrowRight aria-hidden="true" />
                </Button>
              ))}
          </div>
        )}
      </div>
    </section>
  );
}
