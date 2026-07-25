// Scoped re-assessments launched to check action effectiveness.
// Split out of the 1 929-line RemediationCasePage — see that file.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { SectionHeading } from "@/components/section-heading";
import {
  api,
  type RemediationCaseDetail,
  type RemediationPlan,
} from "../../api";
import { ErrorText } from "./shared";

// ---------------------------------------------------------- reassessments

const REASSESSMENT_STATUS_LABELS: Record<string, string> = {
  PENDING: "En attente de lancement",
  LAUNCHED: "Réévaluation lancée",
  LAUNCH_FAILED: "Échec du lancement",
};

export function ReassessmentPanel({
  orgId,
  c,
  activePlan,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  activePlan: RemediationPlan | null;
  onChanged: () => void;
}) {
  const reassessments = useQuery({
    queryKey: ["reassessments", orgId, c.id],
    queryFn: () => api.listReassessments(orgId, c.id),
  });
  const doneActions = (activePlan?.actions ?? []).filter((a) => a.lifecycle === "DONE");
  const [selected, setSelected] = useState<string[]>([]);
  const launch = useMutation({
    mutationFn: () => api.launchReassessment(orgId, c.id, selected),
    onSuccess: () => {
      setSelected([]);
      reassessments.refetch();
      onChanged();
    },
  });

  if (doneActions.length === 0 && (reassessments.data?.length ?? 0) === 0) return null;

  return (
    <section className="space-y-3 rounded-lg border bg-card p-5">
      <SectionHeading
        as="h2"
        title="Réévaluations ciblées"
        description="Une réévaluation confirmée est la meilleure preuve d'efficacité d'une action."
      />
      {doneActions.length > 0 && c.status === "IN_PROGRESS" && (
        <div className="space-y-2 text-sm">
          {doneActions.map((a) => (
            <label key={a.id} className="flex min-h-9 items-center gap-2">
              <input
                type="checkbox"
                checked={selected.includes(a.id)}
                onChange={(e) =>
                  setSelected((prev) =>
                    e.target.checked ? [...prev, a.id] : prev.filter((x) => x !== a.id),
                  )
                }
              />
              <span>
                #{a.position} — {a.description ?? a.ai_description}
              </span>
            </label>
          ))}
          <button
            onClick={() => launch.mutate()}
            disabled={launch.isPending || selected.length === 0}
            className="min-h-10 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Lancer une réévaluation
          </button>
        </div>
      )}
      {(reassessments.data?.length ?? 0) > 0 && (
        <ul className="space-y-2 text-sm">
          {reassessments.data!.map((r) => (
            <li key={r.id} className="rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
                  {REASSESSMENT_STATUS_LABELS[r.status] ?? "Réévaluation"}
                </span>
                {r.assessment_id && (
                  <Link
                    to={`/organizations/${orgId}/assessments/${r.assessment_id}`}
                    className="text-xs text-primary hover:underline"
                  >
                    Voir l'évaluation
                  </Link>
                )}
                <span className="text-xs text-muted-foreground">
                  {new Date(r.created_at).toLocaleString("fr-FR")}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Exigences réévaluées : {r.included_requirement_ids.join(", ") || "—"}
              </p>
              {r.excluded_holdout_ids.length > 0 && (
                <p className="mt-1 text-xs text-warning-foreground dark:text-warning">
                  Exclues (réservées au jeu de test de référence, jamais réévaluées ici) :{" "}
                  {r.excluded_holdout_ids.join(", ")}
                </p>
              )}
              {r.error && <p className="mt-1 text-xs text-destructive">{r.error}</p>}
            </li>
          ))}
        </ul>
      )}
      <ErrorText error={launch.error} />
    </section>
  );
}
