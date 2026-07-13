import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * One dashboard KPI. `value` is rendered in mono for stable digit alignment.
 * Owns its loading / error presentation so the KPI row never collapses.
 * DOM contract (tests rely on it): the label <p>'s grandparent contains the
 * rendered value.
 */
export function KpiCard({
  icon: Icon,
  label,
  value,
  caption,
  loading,
  error,
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  caption?: ReactNode;
  loading?: boolean;
  error?: boolean;
}) {
  return (
    <Card className="gap-0 py-6 shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-shadow duration-300 hover:shadow-[0_10px_30px_-12px_rgba(0,0,0,0.12)]">
      <CardContent className="space-y-3 px-6">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[13px] font-medium text-muted-foreground">{label}</p>
          <span className="flex size-8 items-center justify-center rounded-full border bg-muted/50">
            <Icon className="size-3.5 text-muted-foreground" aria-hidden="true" />
          </span>
        </div>
        {loading ? (
          <Skeleton className="h-9 w-24" />
        ) : error ? (
          <p className="text-sm text-muted-foreground">Indisponible</p>
        ) : (
          <p className="font-mono text-3xl font-semibold tracking-tight">{value}</p>
        )}
        {caption ? <p className="text-xs leading-relaxed text-muted-foreground">{caption}</p> : null}
      </CardContent>
    </Card>
  );
}
