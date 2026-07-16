import type { ComponentProps } from "react";
import { Badge } from "@/components/ui/badge";
import type { Display, Tone } from "@/lib/labels";
import { cn } from "@/lib/utils";

const TONE_VARIANT: Record<Tone, ComponentProps<typeof Badge>["variant"]> = {
  success: "success",
  warning: "warning",
  danger: "danger",
  neutral: "neutral",
  info: "info",
};

const TONE_DOT: Record<Tone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
  neutral: "bg-muted-foreground",
  info: "bg-primary",
};

/**
 * The one way a status renders in the interface: a translated French label
 * from `lib/labels.ts` with its semantic tone. Color never carries meaning
 * alone — the text label is always present.
 */
export function StatusLabel({
  display,
  dot = true,
  pulse = false,
  className,
}: {
  display: Display;
  /** Leading tone dot (decorative — meaning stays in the text). */
  dot?: boolean;
  /** Animate the dot for live in-flight states. */
  pulse?: boolean;
  className?: string;
}) {
  return (
    <Badge variant={TONE_VARIANT[display.tone]} className={cn("gap-1.5", className)}>
      {dot && (
        <span
          aria-hidden="true"
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            TONE_DOT[display.tone],
            pulse && "animate-pulse",
          )}
        />
      )}
      {display.label}
    </Badge>
  );
}
