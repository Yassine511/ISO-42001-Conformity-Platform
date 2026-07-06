import type { AssessmentStatus } from "../api";

const ASSESSMENT_STYLES: Record<AssessmentStatus, { label: string; className: string }> = {
  RUNNING: { label: "En cours", className: "bg-indigo-100 text-indigo-700" },
  COMPLETED: { label: "Terminée", className: "bg-emerald-100 text-emerald-700" },
  FAILED: { label: "Échouée", className: "bg-red-100 text-red-700" },
};

export function AssessmentStatusBadge({ status }: { status: AssessmentStatus }) {
  const s = ASSESSMENT_STYLES[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${s.className}`}
    >
      {status === "RUNNING" && (
        <span
          aria-hidden
          className="h-2 w-2 animate-pulse rounded-full bg-indigo-500"
        />
      )}
      {s.label}
    </span>
  );
}

export function ReviewStatusBadge({ status }: { status: "PENDING" | "CONFIRMED" }) {
  return status === "CONFIRMED" ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
      ✓ Confirmé
    </span>
  ) : (
    <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
      À examiner
    </span>
  );
}
