import { Link } from "react-router-dom";
import {
  ArrowRight,
  FileCheck2,
  FileSearch,
  FileText,
  ListChecks,
  Quote,
  ShieldCheck,
  UserCheck,
  Wrench,
} from "lucide-react";
import { homeOf, useAuth } from "../auth";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";
import { PageFade, StaggerGroup, StaggerItem } from "@/components/motion";

/** Public landing (M10). Honest and typographic by design: no fake logos,
    no invented metrics, no testimonials — the product's argument IS the
    verifiable trust layer, so the page states exactly what the system does
    and does not claim. */

const STEPS = [
  {
    icon: FileText,
    title: "Importez vos politiques",
    text: "Vos documents internes (politiques, procédures, registres) sont découpés et indexés. Les originaux restent immuables — rien ne modifie jamais le fichier de l'entreprise.",
  },
  {
    icon: FileSearch,
    title: "L'évaluation cite ses sources",
    text: "Pour chaque exigence ISO/IEC 42001, l'IA propose un verdict appuyé sur des citations. Un code déterministe vérifie que chaque citation existe mot pour mot dans vos documents.",
  },
  {
    icon: UserCheck,
    title: "Vous confirmez chaque verdict",
    text: "Rien ne devient officiel sans revue humaine : chaque constat est confirmé, corrigé ou rejeté par vos équipes, avec l'extrait source affiché en regard.",
  },
];

const FEATURES = [
  {
    icon: Quote,
    title: "Citations vérifiées",
    text: "Chaque citation affichée est localisée exactement dans vos documents — jamais une paraphrase du modèle.",
  },
  {
    icon: ShieldCheck,
    title: "Abstention plutôt qu'invention",
    text: "Quand la vérification échoue, le système s'abstient et le signale, au lieu de présenter une réponse douteuse.",
  },
  {
    icon: UserCheck,
    title: "Revue humaine obligatoire",
    text: "Les verdicts de l'IA sont des propositions. La décision finale appartient toujours à un réviseur identifié.",
  },
  {
    icon: Wrench,
    title: "Plans de remédiation",
    text: "Chaque écart confirmé ouvre un dossier : plan d'actions, suivi d'efficacité, réévaluation ciblée.",
  },
  {
    icon: ListChecks,
    title: "Déclaration d'applicabilité",
    text: "La SoA de l'Annexe A est tenue à jour avec un historique de décisions inaltérable.",
  },
  {
    icon: FileText,
    title: "Rapports auditables",
    text: "Scores de conformité, registre des risques et export PDF, chacun traçable jusqu'aux constats confirmés.",
  },
];

export default function LandingPage() {
  const { user, organizations, loading } = useAuth();
  const appHome = homeOf(organizations);

  return (
    <div className="flex min-h-[100dvh] flex-col bg-background">
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-lg bg-ink text-ink-foreground">
              <FileCheck2 className="size-4" aria-hidden="true" />
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight">Copilote ISO/IEC 42001</p>
              <p className="text-xs text-muted-foreground">Gouvernance de l'IA</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            {!loading && user ? (
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
                  <Link to="/signup">Créer un compte</Link>
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <PageFade className="flex-1">
        <main>
          {/* hero */}
          <section className="mx-auto w-full max-w-5xl px-6 pt-16 pb-14 md:pt-24 md:pb-20">
            <div className="max-w-3xl space-y-6">
              <p className="text-xs font-medium tracking-[0.18em] text-muted-foreground uppercase">
                Conformité ISO/IEC 42001 assistée par IA
              </p>
              <h1 className="text-4xl leading-[1.1] font-semibold tracking-tight md:text-5xl">
                La conformité, prouvée ligne par ligne.
              </h1>
              <p className="max-w-2xl text-lg leading-relaxed text-muted-foreground">
                L'IA rédige des constats de conformité, un code déterministe vérifie chaque
                citation dans vos documents, et un humain confirme chaque verdict. Ce qui ne
                peut pas être prouvé devient une abstention — jamais une invention.
              </p>
              <div className="flex flex-wrap items-center gap-3 pt-2">
                {!loading && user ? (
                  <Button asChild size="lg" className="h-11">
                    <Link to={appHome}>
                      Ouvrir l'application
                      <ArrowRight className="size-4" aria-hidden="true" />
                    </Link>
                  </Button>
                ) : (
                  <>
                    <Button asChild size="lg" className="h-11">
                      <Link to="/signup">
                        Créer mon espace
                        <ArrowRight className="size-4" aria-hidden="true" />
                      </Link>
                    </Button>
                    <Button asChild variant="outline" size="lg" className="h-11">
                      <Link to="/login">Se connecter</Link>
                    </Button>
                  </>
                )}
              </div>
            </div>
          </section>

          {/* comment ça marche */}
          <section className="border-y bg-muted/30" aria-labelledby="how-title">
            <div className="mx-auto w-full max-w-5xl px-6 py-14 md:py-18">
              <h2 id="how-title" className="text-2xl font-semibold tracking-tight">
                Comment ça marche
              </h2>
              <StaggerGroup className="mt-8 grid gap-6 md:grid-cols-3">
                {STEPS.map((step, i) => (
                  <StaggerItem key={step.title} className="space-y-3">
                    <div className="flex items-center gap-3">
                      <div className="flex size-9 items-center justify-center rounded-lg bg-ink text-ink-foreground">
                        <step.icon className="size-4" aria-hidden="true" />
                      </div>
                      <span className="font-mono text-xs text-muted-foreground tabular-nums">
                        0{i + 1}
                      </span>
                    </div>
                    <h3 className="text-base font-semibold tracking-tight">{step.title}</h3>
                    <p className="text-sm leading-relaxed text-muted-foreground">{step.text}</p>
                  </StaggerItem>
                ))}
              </StaggerGroup>
            </div>
          </section>

          {/* la couche de confiance */}
          <section className="mx-auto w-full max-w-5xl px-6 py-14 md:py-18" aria-labelledby="trust-title">
            <div className="max-w-2xl space-y-3">
              <h2 id="trust-title" className="text-2xl font-semibold tracking-tight">
                Une couche de confiance vérifiable
              </h2>
              <p className="text-base leading-relaxed text-muted-foreground">
                Les assistants IA classiques affirment ; celui-ci prouve ou s'abstient. Chaque
                sortie est soit vérifiée contre vos documents, soit explicitement marquée comme
                nécessitant votre jugement.
              </p>
            </div>
            <StaggerGroup className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((f) => (
                <StaggerItem key={f.title}>
                  <div className="h-full rounded-lg border bg-card p-5">
                    <f.icon className="size-4 text-muted-foreground" aria-hidden="true" />
                    <h3 className="mt-3 text-sm font-semibold tracking-tight">{f.title}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{f.text}</p>
                  </div>
                </StaggerItem>
              ))}
            </StaggerGroup>
          </section>

          {/* réassurance */}
          <section className="border-y bg-muted/30">
            <div className="mx-auto w-full max-w-5xl px-6 py-12">
              <div className="grid gap-8 md:grid-cols-2">
                <div className="space-y-2">
                  <h2 className="text-lg font-semibold tracking-tight">
                    Vos documents restent immuables
                  </h2>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Les fichiers importés ne sont jamais modifiés. Les corrections proposées
                    deviennent de nouvelles versions, explicitement activées par un humain, et
                    l'historique complet est conservé : un constat cite toujours le texte exact
                    sur lequel il a été rendu.
                  </p>
                </div>
                <div className="space-y-2">
                  <h2 className="text-lg font-semibold tracking-tight">
                    Chaque verdict est traçable
                  </h2>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Tentatives du modèle, vérifications, décisions de revue, plans d'action :
                    tout est journalisé en append-only. Un auditeur peut remonter de chaque
                    chiffre du rapport jusqu'à la citation source et à la personne qui l'a
                    confirmée.
                  </p>
                </div>
              </div>
            </div>
          </section>

          {/* CTA final */}
          <section className="mx-auto w-full max-w-5xl px-6 py-16 text-center md:py-20">
            <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
              Commencez votre évaluation ISO/IEC 42001
            </h2>
            <p className="mx-auto mt-3 max-w-xl text-base leading-relaxed text-muted-foreground">
              Créez votre organisation, importez vos politiques et obtenez des constats dont
              chaque citation est vérifiable.
            </p>
            <div className="mt-6 flex justify-center">
              {!loading && user ? (
                <Button asChild size="lg" className="h-11">
                  <Link to={appHome}>
                    Ouvrir l'application
                    <ArrowRight className="size-4" aria-hidden="true" />
                  </Link>
                </Button>
              ) : (
                <Button asChild size="lg" className="h-11">
                  <Link to="/signup">
                    Créer mon espace
                    <ArrowRight className="size-4" aria-hidden="true" />
                  </Link>
                </Button>
              )}
            </div>
          </section>
        </main>
      </PageFade>

      <footer className="border-t">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 px-6 py-6 text-xs text-muted-foreground">
          <p>Copilote ISO/IEC 42001 — l'IA propose, le code vérifie, un humain confirme.</p>
          <p>
            Les réponses de l'IA sont des brouillons à valider ; la pertinence d'une citation
            reste un jugement humain.
          </p>
        </div>
      </footer>
    </div>
  );
}
