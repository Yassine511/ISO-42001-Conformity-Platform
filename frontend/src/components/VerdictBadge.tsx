import type { Verdict } from "../api";
import { StatusLabel } from "@/components/status-label";
import { verdictDisplay } from "@/lib/labels";

/** Verdict badge — label + tone from the central display module, never
    color-only. */
export default function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return null;
  return <StatusLabel display={verdictDisplay(verdict)} />;
}
