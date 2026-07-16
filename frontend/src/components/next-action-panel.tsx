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
  return (
    <section
      aria-label={eyebrow}
      className={cn(
        "relative overflow-hidden rounded-lg border bg-card",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "absolute inset-y-0 left-0 w-1",
          tone === "attention" ? "bg-warning" : tone === "done" ? "bg-success" : "bg-primary",
        )}
      />
      <div className="flex flex-col gap-4 py-5 pr-5 pl-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 space-y-1">
          <p className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {Icon ? <Icon className="size-3.5" aria-hidden="true" /> : null}
            {eyebrow}
          </p>
          <h2 className="text-base font-semibold tracking-tight text-balance">{title}</h2>
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
