import { Link } from "react-router-dom";
import {
  ArrowRight,
  Check,
  ClipboardList,
  Download,
  ListChecks,
  Lock,
  MessageSquareText,
  ShieldAlert,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { homeOf, useAuth } from "../auth";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";
import { PageFade, StaggerGroup, StaggerItem } from "@/components/motion";

/** Public landing (M10, "Registre" redesign). The page's argument IS the
    verifiable trust layer — so it states exactly what the system does and
    does not claim: no fake logos, no invented metrics, no testimonials. */

const PIPELINE = [
  {
    step: "01",
    title: "Retrouver",
    text: "Les passages pertinents sont extraits de votre corpus et de la base de connaissances ISO.",
  },
  {
    step: "02",
    title: "Juger",
    text: "L'IA propose un verdict et une justification — étiquetés « brouillon », jamais définitifs.",
  },
  {
    step: "03",
    title: "Vérifier",
    text: "Du code déterministe confronte chaque citation à la source, au caractère près. Sinon, abstention.",
    emphasis: true,
  },
  {
    step: "04",
    title: "Revue humaine",
    text: "Rien ne compte tant qu'un humain n'a pas confirmé. Chaque décision est horodatée.",
  },
];

const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: ListChecks,
    title: "Évaluations ISO 42001",
    text: "65 exigences de la norme, évaluées avec citations vérifiées et dénominateurs transparents.",
  },
  {
    icon: MessageSquareText,
    title: "Chat fondé sur les preuves",
    text: "Des réponses assemblées uniquement à partir de citations vérifiées, avec notes de bas de page.",
  },
  {
    icon: ShieldAlert,
    title: "Registre des risques",
    text: "Chaque écart confirmé devient un risque scoré (1–9), avec l'applicabilité annotée, jamais masquée.",
  },
  {
    icon: Wrench,
    title: "Remédiation guidée",
    text: "Triage, plan cité, actions à priorité humaine, patchs de documents — l'original reste immuable.",
  },
  {
    icon: Download,
    title: "Export PDF audit-ready",
    text: "Un rapport horodaté, avec provenance et invariants, prêt pour votre auditeur.",
  },
  {
    icon: ClipboardList,
    title: "Déclaration d'applicabilité",
    text: "38 contrôles de l'Annexe A, décisions justifiées et historisées en ajout seul.",
  },
];

const JOURNAL = [
  { dot: "bg-warning", label: "Verdict IA — Partiellement conforme", meta: "07-14 · 09:41 · brouillon" },
  { dot: "bg-destructive", label: "Override humain — Non conforme, M. Dubois", meta: "07-15 · 14:02" },
  { dot: "bg-primary", label: "Cas de remédiation ouvert — CAS-014", meta: "07-15 · 14:02" },
];

export default function LandingPage() {
  const { user, organizations, loading } = useAuth();
  const appHome = homeOf(organizations);
  const authed = !loading && !!user;

  const primaryCta = authed ? (
    <Button asChild size="lg" className="h-11">
      <Link to={appHome}>
        Ouvrir l'application
        <ArrowRight className="size-4" aria-hidden="true" />
      </Link>
    </Button>
  ) : (
    <Button asChild size="lg" className="h-11">
      <Link to="/signup">
        Créer un espace de conformité
        <ArrowRight className="size-4" aria-hidden="true" />
      </Link>
    </Button>
  );

  return (
    <div className="flex min-h-[100dvh] flex-col bg-background">
      {/* top nav */}
      <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-4">
          <Link to="/" className="flex items-center gap-2.5">
            <span className="flex size-[30px] items-center justify-center rounded-lg bg-ink font-serif text-base font-semibold text-ink-foreground">
              C
            </span>
            <span className="text-[15px] font-semibold tracking-tight">Copilote 42001</span>
          </Link>
          <nav className="hidden items-center gap-8 text-[13.5px] text-muted-foreground md:flex">
            <a href="#pipeline" className="transition-colors hover:text-foreground">
              Le pipeline
            </a>
            <a href="#features" className="transition-colors hover:text-foreground">
              Fonctionnalités
            </a>
            <a href="#audit" className="transition-colors hover:text-foreground">
              Piste d'audit
            </a>
          </nav>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            {authed ? (
              <Button asChild size="sm" className="h-9">
                <Link to={appHome}>
                  Ouvrir l'application
                  <ArrowRight className="size-3.5" aria-hidden="true" />
                </Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="ghost" size="sm" className="h-9">
                  <Link to="/login">Se connecter</Link>
                </Button>
                <Button asChild size="sm" className="h-9">
                  <Link to="/signup">Créer un espace</Link>
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <PageFade className="flex-1">
        <main>
          {/* HERO */}
          <section className="relative overflow-hidden border-b bg-gradient-to-b from-background to-secondary/40">
            <div className="mx-auto grid w-full max-w-6xl items-center gap-10 px-6 pt-16 pb-16 md:pt-24 md:pb-24 lg:grid-cols-[1.35fr_1fr]">
              <div className="max-w-2xl">
                <span className="inline-flex items-center gap-2 rounded-full border bg-card px-3.5 py-1.5 text-xs text-muted-foreground">
                  <span aria-hidden="true" className="size-1.5 rounded-full bg-success" />
                  Conforme à ISO/IEC 42001 · gouvernance de l'IA
                </span>
                <h1 className="mt-5 font-serif text-[2.75rem] leading-[1.04] font-medium tracking-[-0.025em] text-balance md:text-6xl">
                  L'IA rédige.
                  <br />
                  Le code vérifie.
                  <br />
                  <span className="text-primary italic">L'humain confirme.</span>
                </h1>
                <p className="mt-6 max-w-xl text-[17px] leading-relaxed text-muted-foreground text-pretty">
                  Le copilote de conformité qui ne vous demande jamais de croire une affirmation
                  sur parole. Chaque citation est un extrait de vos documents, localisé au
                  caractère près. Chaque verdict attend votre confirmation. Ce qui est incertain
                  est déclaré, jamais inventé.
                </p>
                <div className="mt-8 flex flex-wrap items-center gap-3.5">
                  {primaryCta}
                  {!authed && (
                    <Button asChild variant="outline" size="lg" className="h-11">
                      <Link to="/login">Se connecter</Link>
                    </Button>
                  )}
                </div>
              </div>

              {/* floating verified-slice motif */}
              <div className="relative hidden lg:block" aria-hidden="true">
                <div className="ml-auto max-w-[420px] -rotate-2 overflow-hidden rounded-xl border bg-card shadow-[0_24px_60px_-20px_oklch(0.2_0.02_262/0.25)]">
                  <div className="flex items-center gap-2 border-b px-4 py-2.5 font-mono text-[11px] text-muted-foreground">
                    <span className="font-semibold text-foreground">Politique_IA_v3.pdf</span>
                    <span className="opacity-60">· p.4 · chars 1204–1361</span>
                    <span className="ml-auto inline-flex items-center gap-1 text-success">
                      <Check className="size-3" strokeWidth={2.5} />
                      localisée
                    </span>
                  </div>
                  <p className="px-4 py-3.5 text-[12.5px] leading-[1.7] text-muted-foreground">
                    La direction s'engage à maintenir une politique de gouvernance.{" "}
                    <mark className="rounded-[3px] bg-warning/25 px-0.5 text-warning-foreground dark:text-warning">
                      Cette politique est revue à chaque changement significatif
                    </mark>{" "}
                    du contexte.
                  </p>
                </div>
              </div>
            </div>
          </section>

          {/* PIPELINE */}
          <section id="pipeline" className="scroll-mt-20 border-b">
            <div className="mx-auto w-full max-w-6xl px-6 py-16 md:py-20">
              <p className="font-mono text-xs tracking-[0.14em] text-primary">LE PIPELINE</p>
              <h2 className="mt-2.5 max-w-2xl font-serif text-3xl font-medium tracking-tight md:text-4xl">
                Quatre étapes. Aucune ne fait confiance à la précédente.
              </h2>
              <StaggerGroup className="mt-9 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
                {PIPELINE.map((p) => (
                  <StaggerItem key={p.step}>
                    <div
                      className={
                        "h-full rounded-xl border bg-card p-6 " +
                        (p.emphasis ? "border-[1.5px] border-ink dark:border-primary" : "")
                      }
                    >
                      <span
                        className={
                          "font-mono text-xs " + (p.emphasis ? "text-primary" : "text-muted-foreground")
                        }
                      >
                        {p.step}
                      </span>
                      <h3 className="mt-2.5 font-serif text-xl font-medium">{p.title}</h3>
                      <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                        {p.text}
                      </p>
                    </div>
                  </StaggerItem>
                ))}
              </StaggerGroup>
            </div>
          </section>

          {/* ABSTENTION AS A FEATURE */}
          <section className="bg-ink text-ink-foreground">
            <div className="mx-auto grid w-full max-w-6xl items-center gap-12 px-6 py-16 md:py-20 lg:grid-cols-2">
              <div>
                <p className="font-mono text-xs tracking-[0.14em] text-primary/90 dark:text-primary">
                  L'ABSTENTION EST UNE FONCTIONNALITÉ
                </p>
                <h2 className="mt-3.5 font-serif text-3xl leading-[1.15] font-medium tracking-tight text-ink-foreground md:text-4xl">
                  «&nbsp;Le système préfère s'abstenir plutôt qu'inventer.&nbsp;»
                </h2>
                <p className="mt-4 max-w-lg text-[15px] leading-relaxed text-ink-foreground/75">
                  Quand aucune preuve vérifiable n'existe, l'outil ne comble pas le vide par une
                  supposition. Il le déclare — clairement, en ambre non alarmant — pour qu'un
                  humain tranche. C'est l'honnêteté, pas l'échec.
                </p>
              </div>
              <div className="rounded-xl border border-warning/40 border-l-[3px] border-l-warning bg-warning/10 p-6">
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-warning px-3 py-0.5 text-xs font-semibold text-warning-foreground">
                    Écart potentiel
                  </span>
                  <span className="font-mono text-[11px] text-warning-foreground/80 dark:text-warning/90">
                    ABSTENTION · CONTENU
                  </span>
                </div>
                <p className="mt-3.5 text-sm leading-relaxed text-ink-foreground/90">
                  Aucune preuve vérifiable trouvée dans le corpus pour l'exigence{" "}
                  <span className="font-mono">A.6.2.4</span> — journalisation des événements IA. À
                  examiner par un humain.
                </p>
                <div className="mt-4 flex items-center gap-2 border-t border-warning/30 pt-3.5 font-mono text-[11.5px] text-ink-foreground/60">
                  <Lock className="size-3.5 shrink-0" aria-hidden="true" />
                  Les incidents techniques, eux, restent neutres — jamais confondus avec un écart.
                </div>
              </div>
            </div>
          </section>

          {/* FEATURE GRID */}
          <section id="features" className="scroll-mt-20 border-b">
            <div className="mx-auto w-full max-w-6xl px-6 py-16 md:py-20">
              <p className="font-mono text-xs tracking-[0.14em] text-primary">
                TOUT LE CYCLE DE CONFORMITÉ
              </p>
              <h2 className="mt-2.5 font-serif text-3xl font-medium tracking-tight md:text-4xl">
                De la preuve à la remédiation.
              </h2>
              <StaggerGroup className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {FEATURES.map((f) => (
                  <StaggerItem key={f.title}>
                    <div className="h-full rounded-xl border bg-card p-5.5">
                      <f.icon className="size-5 text-primary" strokeWidth={1.8} aria-hidden="true" />
                      <h3 className="mt-3 font-sans text-base font-semibold tracking-tight">
                        {f.title}
                      </h3>
                      <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
                        {f.text}
                      </p>
                    </div>
                  </StaggerItem>
                ))}
              </StaggerGroup>
            </div>
          </section>

          {/* AUDIT TRAIL */}
          <section id="audit" className="scroll-mt-20 border-b bg-secondary/40">
            <div className="mx-auto grid w-full max-w-6xl items-center gap-12 px-6 py-16 md:py-20 lg:grid-cols-2">
              <div>
                <p className="font-mono text-xs tracking-[0.14em] text-primary">PISTE D'AUDIT</p>
                <h2 className="mt-2.5 font-serif text-3xl leading-[1.15] font-medium tracking-tight md:text-4xl">
                  Qui a décidé quoi, et quand — toujours.
                </h2>
                <p className="mt-4 max-w-md text-[15px] leading-relaxed text-muted-foreground">
                  Chaque verdict, override, plan et patch laisse une trace horodatée en ajout seul.
                  La revue peut être ré-ouverte ; l'historique n'est jamais réécrit. Votre auditeur
                  voit exactement la même chose que vous.
                </p>
                <p className="mt-5 flex items-center gap-2 font-mono text-[12.5px] text-success">
                  <Check className="size-3.5 shrink-0" strokeWidth={2.5} aria-hidden="true" />0
                  citation non vérifiée affichée — invariant structurel.
                </p>
              </div>
              <div className="rounded-xl border bg-card p-6">
                <p className="mb-3.5 font-mono text-[11px] tracking-[0.1em] text-muted-foreground">
                  JOURNAL — EN AJOUT SEUL
                </p>
                <ul>
                  {JOURNAL.map((j, i) => (
                    <li
                      key={j.label}
                      className={
                        "flex gap-3 py-3 " + (i < JOURNAL.length - 1 ? "border-b" : "")
                      }
                    >
                      <span
                        aria-hidden="true"
                        className={"mt-1.5 size-[7px] shrink-0 rounded-full " + j.dot}
                      />
                      <div className="text-[12.5px] leading-relaxed">
                        {j.label}
                        <span className="block font-mono text-[11px] text-muted-foreground">
                          {j.meta}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </section>

          {/* CTA */}
          <section className="bg-ink text-ink-foreground">
            <div className="mx-auto w-full max-w-6xl px-6 py-20 text-center md:py-24">
              <h2 className="font-serif text-4xl font-medium tracking-[-0.02em] text-ink-foreground md:text-5xl">
                La conformité, sans acte de foi.
              </h2>
              <p className="mx-auto mt-3.5 max-w-lg text-base leading-relaxed text-ink-foreground/75">
                Créez votre espace de conformité ISO/IEC 42001 en quelques minutes. Votre
                organisation et son espace sont créés ensemble.
              </p>
              <div className="mt-7 flex flex-wrap items-center justify-center gap-3.5">
                {authed ? (
                  <Button asChild size="lg" className="h-11">
                    <Link to={appHome}>
                      Ouvrir l'application
                      <ArrowRight className="size-4" aria-hidden="true" />
                    </Link>
                  </Button>
                ) : (
                  <Button asChild size="lg" className="h-11">
                    <Link to="/signup">Créer un espace</Link>
                  </Button>
                )}
              </div>
              <div className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-ink-foreground/15 pt-6 text-xs text-ink-foreground/60">
                <span>© 2026 Copilote 42001 · Lumen AI SAS</span>
                <span className="font-mono">Hébergé en France · RGPD</span>
              </div>
            </div>
          </section>
        </main>
      </PageFade>
    </div>
  );
}
