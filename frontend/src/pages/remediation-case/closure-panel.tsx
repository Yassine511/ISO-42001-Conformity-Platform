// Closure and reopening.
// Split out of the 1 929-line RemediationCasePage — see that file.
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CLOSURE_RECOMMENDATIONS } from "@/lib/labels";
import { SectionHeading } from "@/components/section-heading";
import {
  api,
  type RemediationCaseDetail,
} from "../../api";
import { ErrorText } from "./shared";

// ---------------------------------------------------------------- closure

export function ClosurePanel({
  orgId,
  c,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  onChanged: () => void;
}) {
  const [note, setNote] = useState("");
  const close = useMutation({
    mutationFn: () => api.closeCase(orgId, c.id, note.trim()),
    onSuccess: onChanged,
  });
  const reopen = useMutation({
    mutationFn: () => api.reopenCase(orgId, c.id),
    onSuccess: onChanged,
  });

  if (c.status === "CLOSED") {
    return (
      <section className="space-y-2 rounded-lg border bg-card p-5">
        <SectionHeading as="h2" title="Clôture" />
        <p className="text-sm">
          Clôturé le {c.closed_at ? new Date(c.closed_at).toLocaleString("fr-FR") : ""} —{" "}
          {c.close_note}
        </p>
        <button
          onClick={() => reopen.mutate()}
          disabled={reopen.isPending}
          className="min-h-10 rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted/50 disabled:opacity-50"
        >
          Rouvrir le cas
        </button>
        <ErrorText error={reopen.error} />
      </section>
    );
  }
  if (!["TRIAGE_APPROVED", "PLAN_READY", "IN_PROGRESS"].includes(c.status)) return null;

  // Server-derived closure-readiness RECOMMENDATIONS — advisory only, the
  // backend does not enforce them at closure (and the UI must not claim so).
  const recommendations = (c.workflow?.closure.recommendations ?? []).filter(
    // keep the plan-level blocker to the plan panel; the closure hints focus
    // on actions and effectiveness
    (k) => k in CLOSURE_RECOMMENDATIONS,
  );

  return (
    <section className="space-y-3 rounded-lg border bg-card p-5">
      <SectionHeading as="h2" title="Clôture" />
      {c.closure_criterion && (
        <p className="text-xs text-muted-foreground">
          Critère de clôture défini : {c.closure_criterion}
        </p>
      )}
      {recommendations.length > 0 && (
        <p className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-warning-foreground dark:text-warning">
          Recommandé avant clôture (non bloquant) :{" "}
          {recommendations.map((k) => CLOSURE_RECOMMENDATIONS[k]).join(" · ")}.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Note de clôture (requise)"
          className="min-h-10 min-w-64 flex-1 rounded-md border border-input px-2 py-1.5 text-sm"
        />
        <button
          onClick={() => close.mutate()}
          disabled={close.isPending || !note.trim()}
          className="min-h-10 rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted/50 disabled:opacity-50"
        >
          Clôturer le cas
        </button>
      </div>
      <ErrorText error={close.error} />
    </section>
  );
}
