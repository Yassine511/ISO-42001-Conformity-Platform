import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ThemeToggle } from "@/components/theme-toggle";
import { PageFade } from "@/components/motion";

/** The brand mark used on every public auth surface. */
function BrandMark({ tone = "ink" }: { tone?: "ink" | "surface" }) {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <span
        className={
          "flex size-[30px] items-center justify-center rounded-lg font-serif text-base font-semibold " +
          (tone === "ink" ? "bg-primary text-primary-foreground" : "bg-ink text-ink-foreground")
        }
      >
        C
      </span>
      <span className="text-sm font-semibold tracking-tight">Copilote 42001</span>
    </Link>
  );
}

/**
 * Shared frame for the public auth pages. With `brand`, it renders the split
 * card of the design — ink panel on the left, form on the right. Without it
 * (invitation states), it renders the compact centered card.
 */
export function AuthFrame({
  title,
  subtitle,
  children,
  footer,
  brand,
  badge,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  /** Left ink panel content — omit for the centered (invitation) variant. */
  brand?: { tagline: string; text: string; note: string };
  /** Optional status chip above the title (invitation states). */
  badge?: ReactNode;
}) {
  const form = (
    <main className="p-7 sm:p-9">
      {!brand && (
        <div className="mb-6">
          <BrandMark tone="surface" />
        </div>
      )}
      {badge ? <div className="mb-3.5">{badge}</div> : null}
      <h1 className="font-serif text-[26px] font-medium tracking-tight">{title}</h1>
      {subtitle && <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{subtitle}</p>}
      <div className="mt-5">{children}</div>
      {footer && <div className="mt-4 text-center text-sm text-muted-foreground">{footer}</div>}
    </main>
  );

  return (
    <div className="relative flex min-h-[100dvh] items-center justify-center bg-secondary/30 p-4 sm:p-6">
      <div className="absolute top-4 right-4">
        <ThemeToggle />
      </div>
      <PageFade className={brand ? "w-full max-w-4xl" : "w-full max-w-md"}>
        <div
          className={
            "overflow-hidden rounded-2xl border bg-card " +
            (brand ? "md:grid md:grid-cols-[280px_1fr]" : "")
          }
        >
          {brand && (
            <aside className="hidden flex-col bg-ink p-8 text-ink-foreground md:flex">
              <BrandMark />
              <div className="flex flex-1 flex-col justify-center py-10">
                <p className="font-serif text-[26px] leading-[1.2] font-medium tracking-tight">
                  {brand.tagline}
                </p>
                <p className="mt-3 text-[13px] leading-relaxed text-ink-foreground/70">
                  {brand.text}
                </p>
              </div>
              <p className="font-mono text-[11px] text-ink-foreground/55">{brand.note}</p>
            </aside>
          )}
          {form}
        </div>
      </PageFade>
    </div>
  );
}
