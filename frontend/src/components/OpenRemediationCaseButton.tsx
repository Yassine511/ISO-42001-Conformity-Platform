import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

/** Opens an M7 remediation case from a CONFIRMED gap finding (shared by the
 * review workspace and the M8 risk register). Opening hands control to the
 * remediation workflow, which drafts an AI-suggested triage — Node ⑤ scoring
 * stays deterministic, but what follows this click is not AI-free. */
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
        className="rounded-lg border border-indigo-300 px-3 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
      >
        {create.isPending ? "Ouverture…" : "Ouvrir un cas de remédiation"}
      </button>
      <p className="mt-1 text-xs text-slate-500">
        Déclenche le triage assisté par IA du module de remédiation.
      </p>
      {create.isError && (
        <p className="mt-1 text-xs text-red-600">{(create.error as Error).message}</p>
      )}
    </div>
  );
}
