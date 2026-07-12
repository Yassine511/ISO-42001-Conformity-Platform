import type { Verdict } from "../api";

// Color-coded verdicts, always paired with a text label (never color-only).
const VERDICT_STYLES: Record<Verdict, { label: string; className: string; dot: string }> = {
  compliant: {
    label: "Conforme",
    className:
      "border-emerald-600/20 bg-emerald-100 text-emerald-800 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-300",
    dot: "bg-emerald-500 dark:bg-emerald-400",
  },
  partial: {
    label: "Partiel",
    className:
      "border-yellow-600/20 bg-yellow-100 text-yellow-800 dark:border-yellow-400/20 dark:bg-yellow-400/10 dark:text-yellow-300",
    dot: "bg-yellow-500 dark:bg-yellow-400",
  },
  non_compliant: {
    label: "Non conforme",
    className:
      "border-red-600/20 bg-red-100 text-red-800 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-300",
    dot: "bg-red-500 dark:bg-red-400",
  },
  missing: {
    label: "Preuve insuffisante",
    className:
      "border-slate-500/20 bg-slate-200 text-slate-700 dark:border-slate-400/20 dark:bg-slate-400/10 dark:text-slate-300",
    dot: "bg-slate-400",
  },
};

export default function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return null;
  const s = VERDICT_STYLES[verdict];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${s.className}`}
    >
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}
