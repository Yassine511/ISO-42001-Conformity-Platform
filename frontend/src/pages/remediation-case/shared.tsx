// Pieces shared by more than one panel of the remediation case page.
// Split out of the 1 929-line RemediationCasePage — see that file.
import {
  OPERATIONAL_ABORT_REASONS,
} from "../../api";

export const isOperationalAbort = (reason: string | null) =>
  reason !== null && (OPERATIONAL_ABORT_REASONS as readonly string[]).includes(reason);

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-sm text-destructive">{(error as Error).message}</p>;
}
