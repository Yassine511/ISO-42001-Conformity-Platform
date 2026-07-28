import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { Link } from "react-router";
import { ThemeToggle } from "@/components/theme-toggle";
import { PageFade, Reveal } from "@/components/motion";

/** Cobalt readable on the ink panel in BOTH themes: blended toward the
    panel's own foreground so it lightens on dark ink and darkens on the
    inverted (dark-mode) light panel. */
export const ACCENT_ON_INK = {
  color: "color-mix(in oklab, var(--primary) 45%, var(--ink-foreground))",
} as const;

/** Back to the public landing page — the product has no wordmark yet, so the
    lockup slot carries a plain return control instead. */
function BackToSite({ tone = "ink" }: { tone?: "ink" | "surface" }) {
  return (
    <Link
      to="/"
      aria-label="Retour à l'accueil"
      className={
        "flex size-[30px] items-center justify-center rounded-lg transition-opacity hover:opacity-80 " +
        (tone === "ink" ? "bg-ink-foreground text-ink" : "bg-ink text-ink-foreground")
      }
    >
      <ArrowLeft className="size-4" aria-hidden="true" />
    </Link>
  );
}

/**
 * Shared frame for the public auth pages (Registre 2.0). With `brand`, it
 * renders the full-viewport split — ink manifesto panel on the left, form
 * column on the right. Without it (invitation states), the compact centered
 * card. The ink panel carries an outlined "42001" watermark and an optional
 * list of numbered points.
 */
export function AuthFrame({
  title,
  subtitle,
  children,
  footer,
  brand,
  badge,
  caps,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  /** Left ink panel content — omit for the centered (invitation) variant. */
  brand?: {
    eyebrow: string;
    /** Headline; pass a ReactNode to include the serif-italic accent. */
    tagline: ReactNode;
    text: string;
    /** Numbered manifesto lines ([prefix, text]). */
    points?: [string, string][];
    note: string;
  };
  /** Optional status chip above the title (invitation states). */
  badge?: ReactNode;
  /** Mono footnote line under the footer. */
  caps?: string;
}) {
  if (!brand) {
    return (
      <div className="relative flex min-h-[100dvh] items-center justify-center bg-secondary/30 p-4 sm:p-6">
        <div className="absolute top-4 right-4">
          <ThemeToggle />
        </div>
        <PageFade className="w-full max-w-md">
          <div className="overflow-hidden rounded-2xl border bg-card">
            <main className="p-7 sm:p-9">
              <div className="mb-6">
                <BackToSite tone="surface" />
              </div>
              {badge ? <div className="mb-3.5">{badge}</div> : null}
              <h1 className="font-serif text-[26px] font-medium tracking-tight">{title}</h1>
              {subtitle && (
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{subtitle}</p>
              )}
              <div className="mt-5">{children}</div>
              {footer && (
                <div className="mt-4 text-center text-sm text-muted-foreground">{footer}</div>
              )}
            </main>
          </div>
        </PageFade>
      </div>
    );
  }

  return (
    <div className="grid min-h-[100dvh] bg-background md:grid-cols-[5fr_6fr]">
      {/* ink manifesto panel */}
      <aside className="relative hidden flex-col overflow-hidden bg-ink p-10 text-ink-foreground md:flex lg:p-13">
        <BackToSite />
        <div className="flex max-w-md flex-1 flex-col justify-center py-10">
          <Reveal i={0}>
            <p
              className="font-mono text-[11px] tracking-[0.16em] uppercase"
              style={ACCENT_ON_INK}
            >
              {brand.eyebrow}
            </p>
            <h2 className="mt-3.5 font-sans text-[clamp(28px,3vw,40px)] leading-[1.1] font-medium tracking-[-0.028em]">
              {brand.tagline}
            </h2>
          </Reveal>
          <Reveal i={1}>
            <p className="mt-5 text-sm leading-[1.75] text-ink-foreground/65">{brand.text}</p>
          </Reveal>
          {brand.points && (
            <Reveal i={2} className="mt-8 flex flex-col gap-3.5">
              {brand.points.map(([prefix, text]) => (
                <p key={prefix} className="flex items-baseline gap-3 text-[13px] text-ink-foreground/80">
                  <span
                    className="shrink-0 rounded-full border border-ink-foreground/20 px-2 py-0.5 font-mono text-[10.5px]"
                    style={ACCENT_ON_INK}
                  >
                    {prefix}
                  </span>
                  {text}
                </p>
              ))}
            </Reveal>
          )}
        </div>
        <p className="font-mono text-[10.5px] tracking-[0.14em] text-ink-foreground/45 uppercase">
          {brand.note}
        </p>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -right-8 -bottom-14 font-mono text-[200px] leading-none font-light text-transparent opacity-20 select-none"
          style={{ WebkitTextStroke: "1px var(--ink-foreground)" }}
        >
          42001
        </span>
      </aside>

      {/* form column */}
      <main className="relative grid place-items-center px-6 py-12">
        <div className="absolute top-4 right-4">
          <ThemeToggle />
        </div>
        <div className="w-full max-w-[420px]">
          <div className="mb-7 md:hidden">
            <BackToSite tone="surface" />
          </div>
          {badge ? <div className="mb-3.5">{badge}</div> : null}
          <Reveal i={1}>
            <h1 className="font-sans text-[26px] font-semibold tracking-tight">{title}</h1>
            {subtitle && (
              <p className="mt-2 text-[13.5px] leading-relaxed text-muted-foreground">{subtitle}</p>
            )}
          </Reveal>
          <Reveal i={2} className="mt-7">
            {children}
          </Reveal>
          {footer && (
            <Reveal i={3}>
              <div className="mt-6 flex items-center justify-between gap-3 border-t pt-5 text-[13px] text-muted-foreground">
                {footer}
              </div>
            </Reveal>
          )}
          {caps && (
            <Reveal i={4}>
              <p className="mt-6 font-mono text-[11px] leading-[1.7] text-muted-foreground/70 uppercase">
                {caps}
              </p>
            </Reveal>
          )}
        </div>
      </main>
    </div>
  );
}
