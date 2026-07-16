import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The ONLY place raw technical values (corpus versions, manifests, model
 * names, raw enums, hashes, retrieval settings) may appear. Collapsed by
 * default, quiet by design.
 */
export function TechnicalDisclosure({
  summary = "Détails techniques",
  children,
  className,
  defaultOpen = false,
}: {
  summary?: string;
  children: ReactNode;
  className?: string;
  defaultOpen?: boolean;
}) {
  return (
    <details
      className={cn("group rounded-lg border border-dashed bg-muted/30", className)}
      open={defaultOpen || undefined}
    >
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-lg px-4 py-2.5 text-[13px] font-medium text-muted-foreground select-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="size-3.5 shrink-0 transition-transform group-open:rotate-90"
          aria-hidden="true"
        />
        {summary}
      </summary>
      <div className="border-t border-dashed px-4 py-3 text-[13px] leading-relaxed text-muted-foreground">
        {children}
      </div>
    </details>
  );
}

/** Aligned key→value row for technical metadata inside a disclosure. */
export function TechnicalRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-0.5">
      <span className="w-44 shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 font-mono text-xs break-all text-foreground/80">{value}</span>
    </div>
  );
}
