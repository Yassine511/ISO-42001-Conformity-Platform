import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Section-level heading (18–20px semibold) with optional side actions.
 * Major workflow phases deserve real headings, not small uppercase labels.
 */
export function SectionHeading({
  title,
  description,
  actions,
  as: Tag = "h2",
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  as?: "h2" | "h3";
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-x-4 gap-y-2", className)}>
      <div className="min-w-0 space-y-0.5">
        <Tag className="text-lg font-semibold tracking-tight">{title}</Tag>
        {description ? (
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
