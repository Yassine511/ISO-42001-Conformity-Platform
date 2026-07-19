import { Link } from "react-router-dom";
import {
  ArrowRight,
  Check,
  ClipboardList,
  Download,
  ListChecks,
  MessageSquareText,
  ShieldAlert,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { homeOf, useAuth } from "../auth";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";
import { PageFade, Reveal } from "@/components/motion";

/** Public landing — "Registre 2.0" port from the design lab. The page's
    argument IS the verifiable trust layer: no fake logos, no invented
    metrics, no testimonials. The only number shown is the structural one. */

const PIPELINE: { step: string; title: string; text: string; hot?: boolean }[] = [
  {
    step: "01",
    title: "Retrouver",
    text: "Les passages pertinents sont extraits de votre corpus documentaire et de la base de connaissances ISO — recherche hybride, lexicale et sémantique.",
  },
  {
    step: "02",
    title: "Juger",
    text: "L'IA propose un verdict et sa justification, étiquetés « brouillon ». Rien de ce qu'elle écrit n'est présenté comme un fait.",
  },
  {
    step: "03",
    title: "Vérifier",
    text: "Du code déterministe confronte chaque citation à la source, au caractère près. Une citation introuvable ? Le constat devient une abstention.",
    hot: true,
  },
  {
    step: "04",
    title: "Confirmer",
    text: "Rien ne compte dans votre conformité tant qu'un humain n'a pas signé. Chaque décision est horodatée et conservée pour l'audit.",
  },
];

const MODULES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: ListChecks,
    title: "Évaluations ISO 42001",
    text: "65 exigences de la norme évaluées automatiquement, avec citations vérifiées, dénominateurs transparents et progression en direct, exigence par exigence.",
  },
  {
    icon: ClipboardList,
    title: "Revue humaine",
    text: "Un espace de décision : la source à gauche, le brouillon IA à droite, la citation surlignée à l'offset exact. Approuver, corriger ou remplacer — l'historique est immuable.",
  },
  {
    icon: ShieldAlert,
    title: "Registre des risques",
    text: "Chaque écart confirmé devient un risque scoré (1–9) : gravité de l'écart × poids du contrôle. Le traitement annote le risque, il ne le masque jamais.",
  },
  {
    icon: Wrench,
    title: "Remédiation guidée",
    text: "Triage, plan d'action cité, priorités fixées par un humain, correctifs de documents — et l'original reste immuable : l'agent ne touche jamais à vos fichiers.",
  },
  {
    icon: MessageSquareText,
    title: "Copilote documentaire",
    text: "Posez une question sur vos politiques : la réponse est assemblée uniquement à partir de citations vérifiées, notes de bas de page comprises. Sinon, il s'abstient.",
  },
  {
    icon: Download,
    title: "Déclaration d'applicabilité & rapport PDF",
    text: "38 contrôles de l'Annexe A, décisions justifiées en ajout seul, et un rapport horodaté avec provenance et invariants, prêt pour votre auditeur.",
  },
];

const JOURNAL = [
  { dot: "bg-warning", label: "Verdict IA — partiellement conforme (A.5.2)", meta: "07-14 · 09:41" },
  { dot: "bg-success", label: "Confirmation humaine — S. Vasseur, RSSI", meta: "07-14 · 11:07" },
  { dot: "bg-destructive", label: "Remplacement de verdict — non conforme (7.2)", meta: "07-15 · 14:02" },
  { dot: "bg-primary", label: "Cas de remédiation ouvert — CAS-014", meta: "07-15 · 14:02" },
  { dot: "bg-muted-foreground", label: "Version de document activée — Politique v4", meta: "07-16 · 10:26" },
];

/** Outlined display numeral (transparent fill, hairline stroke). */
function OutlineNum({ value, hot }: { value: string; hot?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className="font-mono text-[46px] leading-none font-light text-transparent select-none"
      style={{ WebkitTextStroke: hot ? "1px var(--primary)" : "1px var(--border)" }}
    >
      {value}
    </span>
  );
}

function EvidenceSlice({
  file,
  meta,
  status,
  statusClass,
  children,
  className,
}: {
  file: string;
  meta: string;
  status: string;
  statusClass: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={
        "absolute w-full max-w-[400px] overflow-hidden rounded-xl border bg-card shadow-[0_22px_50px_-22px_oklch(0.2_0.02_262/0.3)] " +
        (className ?? "")
      }
    >
      <div className="flex items-center gap-2 border-b px-4 py-2.5 font-mono text-[11px] text-muted-foreground">
        <span className="font-semibold text-foreground">{file}</span>
        <span className="opacity-60">{meta}</span>
        <span className={"ml-auto shrink-0 " + statusClass}>● {status}</span>
      </div>
      <p className="px-4 py-3.5 text-[12.5px] leading-[1.75] text-muted-foreground">{children}</p>
    </div>
  );
}

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
            <span className="flex size-[30px] items-center justify-center rounded-lg bg-ink font-mono text-base font-bold text-ink-foreground">
              C
            </span>
            <span className="text-[15px] font-semibold tracking-tight">Copilote 42001</span>
          </Link>
          <nav className="hidden items-center gap-8 text-[13.5px] text-muted-foreground md:flex">
            <a href="#pipeline" className="transition-colors hover:text-foreground">
              Le pipeline
            </a>
            <a href="#modules" className="transition-colors hover:text-foreground">
              Modules
            </a>
            <a href="#journal" className="transition-colors hover:text-foreground">
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
          <section className="relative overflow-hidden border-b">
            <div className="mx-auto grid w-full max-w-6xl items-center gap-14 px-6 pt-16 pb-16 md:pt-20 md:pb-20 lg:grid-cols-[7fr_5fr]">
              <div>
                <Reveal i={0}>
                  <span className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/[0.06] px-3.5 py-1.5 font-mono text-[11px] tracking-[0.04em] text-primary">
                    <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-primary" />
                    ISO/IEC 42001 · gouvernance des systèmes d'IA
                  </span>
                </Reveal>
                <Reveal i={1}>
                  <h1 className="mt-6 font-sans text-[clamp(44px,6.2vw,78px)] leading-[1.02] font-medium tracking-[-0.03em]">
                    L'IA rédige.
                    <br />
                    Le code vérifie.
                    <br />
                    <span className="font-serif font-normal text-primary italic">
                      L'humain confirme.
                    </span>
                  </h1>
                </Reveal>
                <Reveal i={2}>
                  <p className="mt-7 max-w-xl text-[16.5px] leading-relaxed text-muted-foreground text-pretty">
                    Un copilote de conformité qui ne vous demande{" "}
                    <strong className="font-medium text-foreground">
                      jamais de croire une affirmation sur parole
                    </strong>
                    . Chaque citation est localisée au caractère près dans vos documents. Chaque
                    verdict attend votre signature. Ce qui est incertain est déclaré —{" "}
                    <strong className="font-medium text-foreground">jamais inventé</strong>.
                  </p>
                </Reveal>
                <Reveal i={3}>
                  <div className="mt-9 flex flex-wrap items-center gap-3.5">
                    {primaryCta}
                    {!authed && (
                      <Button asChild variant="outline" size="lg" className="h-11">
                        <a href="#pipeline">Voir comment ça vérifie</a>
                      </Button>
                    )}
                  </div>
                </Reveal>
                <Reveal i={4}>
                  <p className="mt-11 font-mono text-[11.5px] text-muted-foreground/80">
                    <strong className="font-semibold text-foreground">0</strong> citation non
                    vérifiée affichée
                  </p>
                </Reveal>
              </div>

              {/* floating evidence dossier */}
              <Reveal i={2} className="relative hidden min-h-[540px] lg:block">
                <div aria-hidden="true">
                <span className="absolute -top-4 right-0 z-10 inline-flex -rotate-2 items-center gap-2 rounded-[4px] border-[1.5px] border-dashed border-success bg-background px-3 py-1.5 font-mono text-[11px] tracking-[0.14em] text-success uppercase select-none">
                  ✓ Vérifié · exact · p.4
                </span>
                <EvidenceSlice
                  className="top-8 right-0 z-[3] -rotate-2 animate-floaty"
                  file="Politique_gouvernance_IA.md"
                  meta="· p.4 · car. 1204–1361"
                  status="localisée"
                  statusClass="text-success"
                >
                  La direction s'engage à maintenir une politique de gouvernance de l'IA.{" "}
                  <mark className="rounded-[3px] bg-primary/15 px-0.5 text-foreground">
                    Cette politique est revue à chaque changement significatif du contexte
                  </mark>{" "}
                  et communiquée à l'ensemble des parties intéressées.
                </EvidenceSlice>
                <EvidenceSlice
                  className="top-[240px] right-11 z-[2] rotate-[1.6deg] animate-floaty-alt"
                  file="Procédure_évaluation_impact.md"
                  meta="· p.2 · car. 388–512"
                  status="localisée"
                  statusClass="text-success"
                >
                  Une évaluation d'impact est conduite{" "}
                  <mark className="rounded-[3px] bg-warning/25 px-0.5 text-foreground">
                    avant toute mise en production et lors des évolutions majeures
                  </mark>{" "}
                  du système d'IA concerné.
                </EvidenceSlice>
                <EvidenceSlice
                  className="top-[420px] right-1 z-[1] -rotate-1 opacity-90"
                  file="Exigence A.5.2"
                  meta="· brouillon IA"
                  status="à confirmer"
                  statusClass="text-warning-foreground dark:text-warning"
                >
                  Verdict proposé :{" "}
                  <strong className="font-medium text-foreground">partiellement conforme</strong>{" "}
                  — les impacts sociétaux au sens large sont exclus du processus.
                </EvidenceSlice>
                </div>
              </Reveal>
            </div>
          </section>

          {/* marquee band */}
          <div className="overflow-hidden border-b bg-secondary/60 py-3.5 whitespace-nowrap select-none" aria-hidden="true">
            <div className="animate-marquee inline-block">
              {[0, 1].map((i) => (
                <span
                  key={i}
                  className="px-7 font-mono text-xs tracking-[0.22em] text-muted-foreground uppercase"
                >
                  L'IA rédige <span className="text-primary">·</span> le code vérifie{" "}
                  <span className="text-primary">·</span> l'humain confirme{" "}
                  <span className="text-primary">·</span> citation localisée au caractère près{" "}
                  <span className="text-primary">·</span> abstention plutôt qu'invention{" "}
                  <span className="text-primary">·</span>
                </span>
              ))}
            </div>
          </div>

          {/* PIPELINE */}
          <section id="pipeline" className="scroll-mt-20 border-b">
            <div className="mx-auto w-full max-w-6xl px-6 py-20 md:py-24">
              <div className="mb-14 grid items-end gap-10 md:grid-cols-2">
                <Reveal i={0}>
                  <h2 className="font-sans text-[clamp(30px,3.6vw,44px)] leading-[1.08] font-medium tracking-[-0.025em]">
                    Quatre étapes.
                    <br />
                    <em className="font-serif font-normal italic">
                      Aucune ne fait confiance à la précédente.
                    </em>
                  </h2>
                </Reveal>
                <Reveal i={1} className="md:justify-self-end">
                  <p className="max-w-md text-[14.5px] text-muted-foreground">
                    Le système est construit comme une chaîne de méfiance organisée : chaque
                    maillon contrôle le précédent, et le dernier mot revient toujours à un être
                    humain.
                  </p>
                </Reveal>
              </div>
              <div className="grid border-t border-border sm:grid-cols-2 lg:grid-cols-4">
                {PIPELINE.map((p, i) => (
                  <Reveal
                    i={i}
                    key={p.step}
                    className={
                      "relative py-8 pr-6 " +
                      (i > 0 ? "lg:border-l lg:pl-6 " : "") +
                      (p.hot ? "before:absolute before:-top-px before:right-6 before:left-0 before:h-0.5 before:bg-primary lg:before:left-6" : "")
                    }
                  >
                    <OutlineNum value={p.step} hot={p.hot} />
                    <h3 className="mt-4.5 font-sans text-lg font-semibold">{p.title}</h3>
                    <p className="mt-2.5 text-[13px] leading-[1.65] text-muted-foreground">
                      {p.text}
                    </p>
                  </Reveal>
                ))}
              </div>
            </div>
          </section>

          {/* ABSTENTION — ink band */}
          <section className="bg-ink text-ink-foreground">
            <div className="mx-auto grid w-full max-w-6xl gap-16 px-6 py-20 md:py-24 lg:grid-cols-[5fr_7fr]">
              <Reveal i={0}>
                <p
                  className="font-mono text-[11px] tracking-[0.16em] uppercase"
                  style={{ color: "color-mix(in oklab, var(--primary) 45%, var(--ink-foreground))" }}
                >
                  Le parti pris
                </p>
                <h2 className="mt-3 font-sans text-[clamp(30px,3.4vw,42px)] leading-[1.1] font-medium tracking-[-0.025em]">
                  Un système qui préfère
                  <br />
                  <em
                    className="font-serif font-normal italic"
                    style={{ color: "color-mix(in oklab, var(--primary) 45%, var(--ink-foreground))" }}
                  >
                    s'abstenir
                  </em>{" "}
                  plutôt qu'inventer.
                </h2>
                <p className="mt-6 text-[14.5px] leading-[1.7] text-ink-foreground/65">
                  La plupart des outils d'IA remplissent les silences avec de l'assurance.
                  Celui-ci les remplit avec une déclaration d'incertitude. Onze exigences de la
                  norme ne sont volontairement pas couvertes par le corpus de démonstration : la
                  bonne réponse du système, mesurée et assumée, est de le dire.
                </p>
              </Reveal>
              <div className="space-y-3.5">
                {[
                  {
                    tone: "warn" as const,
                    head: "⚠ Écart potentiel — abstention",
                    text: "« Aucun passage de vos documents ne permet de répondre sur la gestion des fournisseurs de composants d'IA (A.10.3). L'absence de preuve est elle-même une information : cette exigence mérite votre attention. »",
                  },
                  {
                    tone: "dim" as const,
                    head: "◦ Panne du fournisseur LLM — abstention neutre",
                    text: "« Le constat n'a pas pu être établi pour une raison technique. Ce n'est pas un signal de conformité — relancez l'évaluation. »",
                  },
                  {
                    tone: "warn" as const,
                    head: "⚠ Citation approximative — rejetée",
                    text: "« Le brouillon citait un passage qui ne correspond pas exactement à la source. La citation a été retirée, le constat rétrogradé. Vous ne verrez jamais la version non vérifiée. »",
                  },
                ].map((c, i) => (
                  <Reveal i={i + 1} key={c.head}>
                    <div className="rounded-xl border border-ink-foreground/15 bg-ink-foreground/[0.04] px-6 py-5">
                      <p
                        className={
                          "font-mono text-[11px] tracking-[0.12em] uppercase " +
                          (c.tone === "warn"
                            ? "text-warning dark:text-warning-foreground"
                            : "text-ink-foreground/50")
                        }
                      >
                        {c.head}
                      </p>
                      <p className="mt-2.5 text-[13.5px] leading-[1.7] text-ink-foreground/75">
                        {c.text}
                      </p>
                    </div>
                  </Reveal>
                ))}
              </div>
            </div>
          </section>

          {/* MODULES */}
          <section id="modules" className="scroll-mt-20 border-b">
            <div className="mx-auto w-full max-w-6xl px-6 py-20 md:py-24">
              <Reveal i={0}>
                <p className="font-mono text-xs tracking-[0.14em] text-primary uppercase">
                  Les modules
                </p>
                <h2 className="mt-2.5 max-w-2xl font-sans text-[clamp(30px,3.4vw,42px)] leading-[1.1] font-medium tracking-[-0.025em]">
                  Tout le cycle de conformité,{" "}
                  <em className="font-serif font-normal italic">sous la même discipline.</em>
                </h2>
              </Reveal>
              <div className="mt-12 border-t border-border">
                {MODULES.map((m, i) => (
                  <Reveal i={i} key={m.title}>
                    <div className="group grid items-center gap-6 border-b py-8 md:grid-cols-[64px_1fr_1.2fr] md:gap-9">
                      <span className="flex size-[42px] items-center justify-center rounded-[10px] border bg-card text-primary transition-colors group-hover:border-primary">
                        <m.icon className="size-5" aria-hidden="true" />
                      </span>
                      <h3 className="font-sans text-[19px] font-semibold tracking-[-0.015em]">
                        {m.title}
                      </h3>
                      <p className="text-sm leading-[1.7] text-muted-foreground">{m.text}</p>
                    </div>
                  </Reveal>
                ))}
              </div>
            </div>
          </section>

          {/* JOURNAL */}
          <section id="journal" className="scroll-mt-20 border-b bg-secondary/40">
            <div className="mx-auto grid w-full max-w-6xl items-center gap-16 px-6 py-20 md:py-24 lg:grid-cols-[1fr_1.15fr]">
              <Reveal i={0}>
                <p className="font-mono text-xs tracking-[0.14em] text-primary uppercase">
                  La piste d'audit
                </p>
                <h2 className="mt-2.5 font-sans text-[clamp(28px,3.2vw,40px)] leading-[1.1] font-medium tracking-[-0.025em]">
                  Chaque décision laisse{" "}
                  <em className="font-serif font-normal italic">une trace datée.</em>
                </h2>
                <p className="mt-5 max-w-md text-[14.5px] leading-[1.7] text-muted-foreground">
                  Verdicts IA, confirmations, remplacements, ouvertures de cas : le journal est
                  en ajout seul. On peut toujours répondre à la question d'un auditeur — « qui a
                  décidé quoi, quand, sur la foi de quelle preuve ? »
                </p>
              </Reveal>
              <Reveal i={1} className="overflow-hidden rounded-xl border bg-card">
                {JOURNAL.map((j, i) => (
                  <div
                    key={j.label}
                    className={
                      "flex items-center gap-3.5 px-5 py-3.5 text-[13.5px] " +
                      (i > 0 ? "border-t" : "")
                    }
                  >
                    <span aria-hidden="true" className={"size-2 shrink-0 rounded-full " + j.dot} />
                    <span className="min-w-0 truncate">{j.label}</span>
                    <span className="ml-auto shrink-0 font-mono text-[11px] text-muted-foreground/70">
                      {j.meta}
                    </span>
                  </div>
                ))}
              </Reveal>
            </div>
          </section>

          {/* FINAL CTA */}
          <section className="bg-ink text-ink-foreground">
            <div className="mx-auto grid w-full max-w-6xl items-center gap-14 px-6 pt-24 pb-24 md:pt-28 lg:grid-cols-[1.4fr_1fr]">
              <Reveal i={0}>
                <h2 className="font-sans text-[clamp(34px,4.4vw,56px)] leading-[1.05] font-medium tracking-[-0.03em]">
                  La confiance ne se déclare pas.
                  <br />
                  <em
                    className="font-serif font-normal italic"
                    style={{ color: "color-mix(in oklab, var(--primary) 45%, var(--ink-foreground))" }}
                  >
                    Elle se vérifie.
                  </em>
                </h2>
                <p className="mt-5 max-w-md text-[15px] leading-[1.7] text-ink-foreground/65">
                  Créez votre espace, déposez vos politiques, lancez une première évaluation. Le
                  premier verdict qui compte sera le vôtre.
                </p>
              </Reveal>
              <Reveal i={1} className="flex flex-col items-start gap-3.5 lg:justify-self-end">
                {authed ? (
                  <Button asChild size="lg" className="h-11 bg-ink-foreground text-ink hover:bg-ink-foreground/90">
                    <Link to={appHome}>
                      Ouvrir l'application
                      <ArrowRight className="size-4" aria-hidden="true" />
                    </Link>
                  </Button>
                ) : (
                  <Button asChild size="lg" className="h-11 bg-ink-foreground text-ink hover:bg-ink-foreground/90">
                    <Link to="/signup">
                      Créer un espace de conformité
                      <ArrowRight className="size-4" aria-hidden="true" />
                    </Link>
                  </Button>
                )}
                <span className="font-mono text-[11.5px] text-ink-foreground/50">
                  Sans carte bancaire · vos données restent chez vous
                </span>
              </Reveal>
            </div>
            <footer className="border-t border-ink-foreground/15">
              <div className="mx-auto flex w-full max-w-6xl flex-wrap gap-6 px-6 py-6 font-mono text-[11px] tracking-[0.06em] text-ink-foreground/45 uppercase">
                <span>Copilote 42001</span>
                <span className="inline-flex items-center gap-1.5">
                  <Check className="size-3" aria-hidden="true" />
                  L'IA rédige · le code vérifie · l'humain confirme
                </span>
                <span className="ml-auto">2026</span>
              </div>
            </footer>
          </section>
        </main>
      </PageFade>
    </div>
  );
}
