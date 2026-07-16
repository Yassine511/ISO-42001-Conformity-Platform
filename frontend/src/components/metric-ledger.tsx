import type { ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export interface MetricEntry {
  /** Short metric name, e.g. « Conformité évaluée ». */
  label: string;
  /** The number itself — tabular numerals, mono not required. */
  value: ReactNode;
  /** One line saying exactly WHAT the denominator is. Honesty lives here. */
  caption?: ReactNode;
  /** Small trailing annotation next to the value (unit, fraction…). */
  detail?: ReactNode;
}

/**
 * A grouped metric ledger: one bordered group, thin dividers between entries,
 * instead of rows of identical KPI cards. Each entry states its own
 * denominator so distinct measures (évaluée / périmètre / norme) can never be
 * read as the same number.
 */
export function MetricLedger({
  entries,
  loading,
  error,
  columns,
  className,
}: {
  entries: MetricEntry[];
  loading?: boolean;
  error?: boolean;
  /** Desktop column count; defaults to the entry count (max 4). */
  columns?: 2 | 3 | 4;
  className?: string;
}) {
  const cols = columns ?? (Math.min(entries.length, 4) as 2 | 3 | 4);
  const colClass =
    cols === 2 ? "sm:grid-cols-2" : cols === 3 ? "sm:grid-cols-3" : "sm:grid-cols-2 lg:grid-cols-4";
  return (
    <dl
      className={cn(
        "grid grid-cols-1 divide-y rounded-lg border bg-card",
        colClass,
        "sm:divide-x sm:divide-y-0",
        className,
      )}
    >
      {entries.map((entry) => (
        <div key={entry.label} className="min-w-0 px-5 py-4">
          <dt className="text-[13px] font-medium text-muted-foreground">{entry.label}</dt>
          {loading ? (
            <Skeleton className="mt-2 h-8 w-20" />
          ) : error ? (
            <dd className="mt-2 text-sm text-muted-foreground">Indisponible</dd>
          ) : (
            <dd className="mt-1 flex items-baseline gap-2">
              <span className="text-[28px] leading-9 font-semibold tracking-tight tabular-nums">
                {entry.value}
              </span>
              {entry.detail ? (
                <span className="text-sm text-muted-foreground tabular-nums">{entry.detail}</span>
              ) : null}
            </dd>
          )}
          {entry.caption ? (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{entry.caption}</p>
          ) : null}
        </div>
      ))}
    </dl>
  );
}
