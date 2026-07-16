import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Building2, FileCheck2, Plus, Search } from "lucide-react";
import { api } from "../api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ListSkeleton } from "@/components/data-skeletons";
import { EmptyState } from "@/components/empty-state";
import { TechnicalDisclosure } from "@/components/technical-disclosure";
import { ThemeToggle } from "@/components/theme-toggle";
import { PageFade, StaggerGroup, StaggerItem } from "@/components/motion";

/** Organizations home — choose a workspace or create one. Existing
    organizations dominate; creation is secondary; trust wording stays in a
    quiet footer disclosure (spec §8.1). Only real data renders: name +
    creation date, never invented scores. */
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
      (orgs.data ?? []).filter((o) => o.name.toLowerCase().includes(search.trim().toLowerCase())),
    [orgs.data, search],
  );

  // The clear primary path when the flagship workspace exists.
  const lumen = orgs.data?.find((o) => o.name.toLowerCase().startsWith("lumen ai"));

  return (
    <div className="flex min-h-[100dvh] flex-col bg-background">
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-lg bg-ink text-ink-foreground">
              <FileCheck2 className="size-4" aria-hidden="true" />
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight">Copilote ISO/IEC 42001</p>
              <p className="text-xs text-muted-foreground">Gouvernance de l'IA</p>
            </div>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <PageFade className="flex-1">
        <main className="mx-auto w-full max-w-4xl px-6 pb-16">
          <section className="space-y-2 py-10 md:py-14">
            <h1 className="text-3xl font-semibold tracking-tight md:text-[32px]">
              Choisissez une organisation
            </h1>
            <p className="text-base leading-relaxed text-muted-foreground">
              Reprenez votre travail de conformité ou créez un nouvel espace.
            </p>
          </section>

          <section className="space-y-4" aria-label="Organisations existantes">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold tracking-tight">
                Vos organisations
                {orgs.data && (
                  <span className="ml-2 text-sm font-normal text-muted-foreground tabular-nums">
                    {orgs.data.length}
                  </span>
                )}
              </h2>
              <div className="relative">
                <Search
                  className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground"
                  aria-hidden="true"
                />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Rechercher…"
                  aria-label="Rechercher une organisation"
                  className="h-10 w-52 pl-9 sm:w-64"
                />
              </div>
            </div>

            {orgs.isLoading && <ListSkeleton rows={3} />}
            {orgs.isError && (
              <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                Service injoignable — vérifiez que l'application est bien démarrée, puis
                rechargez la page.
              </p>
            )}
            {orgs.data?.length === 0 && (
              <EmptyState
                icon={Building2}
                title="Aucune organisation pour le moment"
                description="Créez votre premier espace ci-dessous pour commencer le travail de conformité."
              />
            )}
            {orgs.data && orgs.data.length > 0 && filtered.length === 0 && (
              <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
                Aucune organisation ne correspond à « {search} ».
              </p>
            )}

            <StaggerGroup className="grid gap-3 sm:grid-cols-2">
              {filtered.map((org) => {
                const isPrimary = lumen?.id === org.id;
                return (
                  <StaggerItem key={org.id}>
                    <Link
                      to={`/organizations/${org.id}`}
                      className="group flex h-full items-center gap-3 rounded-lg border bg-card p-5 transition-colors hover:border-primary/40 hover:bg-accent/40 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                    >
                      <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-muted">
                        <Building2 className="size-4 text-muted-foreground" aria-hidden="true" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold">
                          {isPrimary ? `Ouvrir ${org.name}` : org.name}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Créée le {new Date(org.created_at).toLocaleDateString("fr-FR")}
                        </p>
                      </div>
                      <span
                        className={
                          isPrimary
                            ? "flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground"
                            : "flex size-8 shrink-0 items-center justify-center rounded-full border bg-background text-muted-foreground"
                        }
                      >
                        <ArrowRight className="size-3.5" aria-hidden="true" />
                      </span>
                    </Link>
                  </StaggerItem>
                );
              })}
            </StaggerGroup>
          </section>

          <section className="mt-10 max-w-xl space-y-3" aria-label="Créer une organisation">
            <h2 className="text-sm font-semibold text-muted-foreground">
              Créer un nouvel espace
            </h2>
            <form
              className="flex flex-col gap-2 sm:flex-row"
              onSubmit={(e) => {
                e.preventDefault();
                if (name.trim()) createOrg.mutate(name.trim());
              }}
            >
              <Label htmlFor="org-name" className="sr-only">
                Nom de la nouvelle organisation
              </Label>
              <Input
                id="org-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Nom de l'organisation"
                className="h-10"
              />
              <Button
                type="submit"
                variant="outline"
                className="h-10 shrink-0"
                disabled={createOrg.isPending || !name.trim()}
              >
                <Plus className="size-4" aria-hidden="true" />
                Créer
              </Button>
            </form>
            {createOrg.isError && (
              <p className="text-sm text-destructive">{(createOrg.error as Error).message}</p>
            )}
          </section>

          <div className="mt-12">
            <TechnicalDisclosure summary="Comment les réponses sont vérifiées">
              <p>
                L'IA rédige des propositions ; un code déterministe vérifie que chaque citation
                existe mot pour mot dans vos documents ; toute sortie incertaine devient une
                abstention ; un humain confirme chaque verdict. La pertinence d'une citation
                reste un jugement humain.
              </p>
            </TechnicalDisclosure>
          </div>
        </main>
      </PageFade>
    </div>
  );
}
