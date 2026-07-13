import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Building2, FileCheck2, Plus, Search, ShieldCheck } from "lucide-react";
import { api } from "../api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ListSkeleton } from "@/components/data-skeletons";
import { EmptyState } from "@/components/empty-state";
import { ThemeToggle } from "@/components/theme-toggle";
import { PageFade, StaggerGroup, StaggerItem } from "@/components/motion";

export default function HomePage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [search, setSearch] = useState("");

  const orgs = useQuery({ queryKey: ["organizations"], queryFn: api.listOrganizations });

  const createOrg = useMutation({
    mutationFn: api.createOrganization,
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["organizations"] });
    },
  });

  const filtered = useMemo(
    () =>
      (orgs.data ?? []).filter((o) =>
        o.name.toLowerCase().includes(search.trim().toLowerCase()),
      ),
    [orgs.data, search],
  );

  return (
    <div className="min-h-[100dvh] bg-background">
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <FileCheck2 className="size-4" aria-hidden="true" />
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight">Copilote ISO/IEC 42001</p>
              <p className="text-xs text-muted-foreground">INT102 · Teamwill</p>
            </div>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <PageFade>
        <main className="mx-auto w-full max-w-5xl px-6 pb-24">
          <section className="grid gap-10 py-12 md:grid-cols-[1fr_360px] md:items-start md:py-16">
            <div className="max-w-xl space-y-4">
              <p className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                <ShieldCheck className="size-3.5" aria-hidden="true" />
                Couche de confiance vérifiable
              </p>
              <h1 className="text-4xl font-semibold leading-tight tracking-tight md:text-5xl">
                Organisations
              </h1>
              <p className="text-base leading-relaxed text-muted-foreground">
                Créez une organisation puis téléversez ses documents de politique pour
                l'évaluation ISO/IEC 42001 — chaque citation est vérifiée par le code, chaque
                verdict confirmé par un humain.
              </p>
            </div>

            <Card className="py-6">
              <CardContent className="space-y-3 px-6">
                <p className="text-sm font-semibold">Nouvelle organisation</p>
                <form
                  className="flex flex-col gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (name.trim()) createOrg.mutate(name.trim());
                  }}
                >
                  <Label htmlFor="org-name" className="sr-only">
                    Nouvelle organisation
                  </Label>
                  <Input
                    id="org-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Nom de l'organisation (ex. Lumen AI)"
                  />
                  <Button
                    type="submit"
                    className="w-full rounded-full"
                    disabled={createOrg.isPending || !name.trim()}
                  >
                    <Plus className="size-4" aria-hidden="true" />
                    Créer
                  </Button>
                  {createOrg.isError && (
                    <p className="text-sm text-destructive">
                      {(createOrg.error as Error).message}
                    </p>
                  )}
                </form>
              </CardContent>
            </Card>
          </section>

          <section className="space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold tracking-tight">
                Continuer le travail
                {orgs.data && (
                  <span className="ml-2 text-sm font-normal text-muted-foreground">
                    {orgs.data.length} organisation{orgs.data.length > 1 ? "s" : ""}
                  </span>
                )}
              </h2>
              {(orgs.data?.length ?? 0) > 3 && (
                <div className="relative">
                  <Search
                    className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <Input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Filtrer…"
                    aria-label="Filtrer les organisations"
                    className="h-9 w-56 rounded-full pl-9"
                  />
                </div>
              )}
            </div>

            {orgs.isLoading && <ListSkeleton rows={3} />}
            {orgs.isError && (
              <p className="text-sm text-destructive">
                API injoignable — vérifiez que le backend est démarré (docker compose up).
              </p>
            )}
            {orgs.data?.length === 0 && (
              <EmptyState
                icon={Building2}
                title="Aucune organisation pour le moment"
                description="Créez votre première organisation ci-dessus pour commencer l'évaluation de conformité."
              />
            )}
            <StaggerGroup className="grid gap-3 sm:grid-cols-2">
              {filtered.map((org) => (
                <StaggerItem key={org.id}>
                  <Card className="group h-full py-0 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_14px_35px_-15px_rgba(0,0,0,0.18)]">
                    <Link
                      to={`/organizations/${org.id}`}
                      className="block rounded-xl focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      <CardContent className="flex items-center gap-3 p-5">
                        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl border bg-muted">
                          <Building2 className="size-4 text-muted-foreground" aria-hidden="true" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold">{org.name}</p>
                          <p className="text-xs text-muted-foreground">
                            Créée le {new Date(org.created_at).toLocaleDateString("fr-FR")}
                          </p>
                        </div>
                        <span className="flex size-8 shrink-0 items-center justify-center rounded-full border bg-background transition-transform duration-300 group-hover:translate-x-0.5">
                          <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
                        </span>
                      </CardContent>
                    </Link>
                  </Card>
                </StaggerItem>
              ))}
            </StaggerGroup>
          </section>
        </main>
      </PageFade>
    </div>
  );
}
