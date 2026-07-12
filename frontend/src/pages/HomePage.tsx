import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Building2, FileCheck2, Plus, ShieldCheck } from "lucide-react";
import { api } from "../api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ListSkeleton } from "@/components/data-skeletons";
import { EmptyState } from "@/components/empty-state";
import { ThemeToggle } from "@/components/theme-toggle";

export default function HomePage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const orgs = useQuery({ queryKey: ["organizations"], queryFn: api.listOrganizations });

  const createOrg = useMutation({
    mutationFn: api.createOrganization,
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["organizations"] });
    },
  });

  return (
    <div className="min-h-[100dvh] bg-background">
      <header className="mx-auto flex w-full max-w-4xl items-center justify-between px-6 py-5">
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
      </header>

      <main className="mx-auto w-full max-w-4xl px-6 pb-16">
        <section className="py-10 md:py-14">
          <div className="max-w-2xl space-y-4">
            <p className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium text-muted-foreground">
              <ShieldCheck className="size-3.5 text-primary" aria-hidden="true" />
              Couche de confiance vérifiable — chaque citation est vérifiée par le code
            </p>
            <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
              Organisations
            </h1>
            <p className="text-base leading-relaxed text-muted-foreground">
              Créez une organisation puis téléversez ses documents de politique pour
              l'évaluation ISO/IEC 42001.
            </p>
          </div>

          <form
            className="mt-8 flex max-w-md flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) createOrg.mutate(name.trim());
            }}
          >
            <Label htmlFor="org-name">Nouvelle organisation</Label>
            <div className="flex gap-2">
              <Input
                id="org-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Nom de l'organisation (ex. Lumen AI)"
              />
              <Button type="submit" disabled={createOrg.isPending || !name.trim()}>
                <Plus className="size-4" aria-hidden="true" />
                Créer
              </Button>
            </div>
            {createOrg.isError && (
              <p className="text-sm text-destructive">{(createOrg.error as Error).message}</p>
            )}
          </form>
        </section>

        <section className="space-y-4">
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
          <ul className="grid gap-3 sm:grid-cols-2">
            {orgs.data?.map((org) => (
              <li key={org.id}>
                <Card className="group h-full py-0 transition-colors hover:border-primary/40">
                  <Link
                    to={`/organizations/${org.id}`}
                    className="block rounded-xl focus-visible:outline-2 focus-visible:outline-ring"
                  >
                    <CardContent className="flex items-center gap-3 p-4">
                      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
                        <Building2 className="size-4 text-muted-foreground" aria-hidden="true" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{org.name}</p>
                        <p className="text-xs text-muted-foreground">
                          Créée le {new Date(org.created_at).toLocaleDateString("fr-FR")}
                        </p>
                      </div>
                      <ArrowRight
                        className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    </CardContent>
                  </Link>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}
