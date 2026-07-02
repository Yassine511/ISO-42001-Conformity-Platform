import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";

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
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Organisations</h1>
        <p className="mt-1 text-sm text-slate-500">
          Créez une organisation puis téléversez ses documents de politique pour l'évaluation
          ISO/IEC 42001.
        </p>
      </div>

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) createOrg.mutate(name.trim());
        }}
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Nom de l'organisation (ex. Lumen AI)"
          className="w-80 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <button
          type="submit"
          disabled={createOrg.isPending || !name.trim()}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          Créer
        </button>
      </form>
      {createOrg.isError && (
        <p className="text-sm text-red-600">{(createOrg.error as Error).message}</p>
      )}

      {orgs.isLoading && <p className="text-sm text-slate-500">Chargement…</p>}
      {orgs.isError && (
        <p className="text-sm text-red-600">
          API injoignable — vérifiez que le backend est démarré (docker compose up).
        </p>
      )}

      <ul className="grid gap-3 sm:grid-cols-2">
        {orgs.data?.map((org) => (
          <li key={org.id}>
            <Link
              to={`/organizations/${org.id}`}
              className="block rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-indigo-300 hover:shadow"
            >
              <div className="font-medium">{org.name}</div>
              <div className="mt-1 text-xs text-slate-500">
                Créée le {new Date(org.created_at).toLocaleDateString("fr-FR")}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
