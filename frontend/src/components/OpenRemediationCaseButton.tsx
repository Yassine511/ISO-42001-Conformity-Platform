import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { api } from "../api";

/** Opens a remediation case from a CONFIRMED gap finding (shared by the
 * review workspace and the risk register). Opening hands control to the
 * remediation workflow, which drafts an AI-suggested triage — scoring stays
 * deterministic, but what follows this click is not AI-free. */
export default function OpenRemediationCaseButton({
  orgId,
  findingId,
}: {
  orgId: string;
  findingId: string;
}) {
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: () => api.createCase(orgId, { finding_id: findingId }),
    onSuccess: (c) => navigate(`/organizations/${orgId}/remediation/${c.id}`),
  });
  return (
    <div className="mt-3">
      <button
        onClick={() => create.mutate()}
        disabled={create.isPending}
        className="min-h-10 rounded-md border border-primary/40 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10 focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
      >
        {create.isPending ? "Ouverture…" : "Ouvrir un cas de remédiation"}
      </button>
      <p className="mt-1 text-xs text-muted-foreground">
        Déclenche le triage assisté par IA du module de remédiation.
      </p>
      {create.isError && (
        <p className="mt-1 text-xs text-destructive">{(create.error as Error).message}</p>
      )}
    </div>
  );
}
