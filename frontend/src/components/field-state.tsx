import { MISSING } from "@/lib/labels";
import { cn } from "@/lib/utils";

/**
 * Honest field rendering: a real value in normal ink, a missing value as a
 * quiet italic placeholder (« Non attribué », « À définir », « Non
 * renseigné ») — never a fabricated default.
 */
export function FieldState({
  value,
  kind = "value",
  className,
}: {
  value: string | null | undefined;
  kind?: keyof typeof MISSING;
  className?: string;
}) {
  const missing = value == null || value.trim() === "";
  return (
    <span
      className={cn(missing && "text-muted-foreground/80 italic", className)}
      data-missing={missing || undefined}
    >
      {missing ? MISSING[kind] : value}
    </span>
  );
}
