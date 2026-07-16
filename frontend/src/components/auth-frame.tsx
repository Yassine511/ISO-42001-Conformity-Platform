import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { FileCheck2 } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { PageFade } from "@/components/motion";

/** Shared centered frame for the public auth pages (connexion, inscription,
    invitation) — same quiet header as the landing, one card of content. */
export function AuthFrame({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex min-h-[100dvh] flex-col bg-background">
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between px-6 py-3">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-lg bg-ink text-ink-foreground">
              <FileCheck2 className="size-4" aria-hidden="true" />
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight">Copilote ISO/IEC 42001</p>
              <p className="text-xs text-muted-foreground">Gouvernance de l'IA</p>
            </div>
          </Link>
          <ThemeToggle />
        </div>
      </header>

      <PageFade className="flex flex-1 items-center justify-center px-6 py-12">
        <main className="w-full max-w-sm space-y-6">
          <div className="space-y-1.5 text-center">
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {subtitle && (
              <p className="text-sm leading-relaxed text-muted-foreground">{subtitle}</p>
            )}
          </div>
          {children}
          {footer && <div className="text-center text-sm text-muted-foreground">{footer}</div>}
        </main>
      </PageFade>
    </div>
  );
}
