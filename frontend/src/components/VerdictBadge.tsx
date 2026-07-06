import type { Verdict } from "../api";

// Color-coded verdicts, always paired with a text label (never color-only).
const VERDICT_STYLES: Record<Verdict, { label: string; className: string; dot: string }> = {
  compliant: {
    label: "Conforme",
    className: "bg-emerald-100 text-emerald-800",
    dot: "bg-emerald-500",
  },
  partial: { label: "Partiel", className: "bg-yellow-100 text-yellow-800", dot: "bg-yellow-500" },
  non_compliant: {
    label: "Non conforme",
    className: "bg-red-100 text-red-800",
    dot: "bg-red-500",
  },
  missing: {
    label: "Preuve insuffisante",
    className: "bg-slate-200 text-slate-700",
    dot: "bg-slate-400",
  },
};

export default function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return null;
  const s = VERDICT_STYLES[verdict];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${s.className}`}
    >
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}
