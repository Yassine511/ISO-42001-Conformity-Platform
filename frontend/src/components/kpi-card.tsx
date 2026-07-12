import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * One dashboard KPI. `value` is rendered in mono for stable digit alignment.
 * Owns its loading / error presentation so the KPI row never collapses.
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
    <Card className="gap-0 py-5">
      <CardContent className="space-y-2 px-5">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm text-muted-foreground">{label}</p>
          <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
        </div>
        {loading ? (
          <Skeleton className="h-8 w-20" />
        ) : error ? (
          <p className="text-sm text-muted-foreground">Indisponible</p>
        ) : (
          <p className="font-mono text-2xl font-semibold tracking-tight">{value}</p>
        )}
        {caption ? <p className="text-xs text-muted-foreground">{caption}</p> : null}
      </CardContent>
    </Card>
  );
}
