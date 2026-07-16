import type { ReactNode } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * Filter / search row above an operational table. Children are the page's
 * filter controls (native selects where tests rely on them); `end` holds
 * right-aligned actions (export, sort…).
 */
export function TableToolbar({
  searchValue,
  onSearchChange,
  searchPlaceholder = "Rechercher…",
  searchLabel = "Rechercher dans le tableau",
  children,
  end,
  className,
}: {
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  searchLabel?: string;
  children?: ReactNode;
  end?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3 py-2",
        className,
      )}
    >
      {onSearchChange && (
        <div className="relative min-w-40 flex-1 sm:max-w-64">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={searchValue ?? ""}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchLabel}
            className="h-9 border-0 bg-muted/50 pl-8 shadow-none focus-visible:bg-background"
          />
        </div>
      )}
      {children}
      {end ? <div className="ml-auto flex items-center gap-2">{end}</div> : null}
    </div>
  );
}

/** Native select styled to match the toolbar — tests drive it with selectOptions. */
export function ToolbarSelect({
  label,
  className,
  children,
  ...props
}: React.ComponentProps<"select"> & { label: string }) {
  return (
    <label className="flex min-h-10 items-center gap-1.5 text-[13px] text-muted-foreground">
      <span>{label}</span>
      <select
        {...props}
        className={cn(
          "h-9 min-w-0 rounded-md border bg-background px-2 text-[13px] text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
          className,
        )}
      >
        {children}
      </select>
    </label>
  );
}
