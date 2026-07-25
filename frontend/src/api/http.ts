// Fetch plumbing shared by every domain module: the error type carrying the
// HTTP status, the two response readers, and the POST helper with its
// last-resort client deadline.
import { UNAUTHORIZED_EVENT } from "./types";
import type { ActivationResult } from "./types";

/** An API failure, carrying the HTTP status so callers (and the react-query
    retry policy) can tell a deterministic client error from a transient one.
    `message` stays the server's French `detail` — every existing
    `(err as Error).message` reader is unaffected. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    if (res.status === 401) {
      // session expired/revoked: the AuthProvider listens and clears the
      // user, which sends the guard back to /login (harmless on the login
      // form itself, where the user is already null)
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.detail ?? `Erreur ${res.status}`, res.status);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

// Activation endpoints convey their outcome IN the body across several status
// codes (200 activated, 202 pending, 409 assessment_conflict/abandoned, 503
// index_failed). Any body carrying `outcome` is a result to surface, not an
// error; a genuine failure (404/422, or a 409 with only `detail`) still throws.
export async function activation(res: Response): Promise<ActivationResult> {
  const body = await res.json().catch(() => null);
  if (body && typeof body.outcome === "string") return body as ActivationResult;
  throw new ApiError(body?.detail ?? `Erreur ${res.status}`, res.status);
}

// Last-resort client deadline for writes. Deliberately ABOVE nginx's
// proxy_read_timeout (300 s) so a slow-but-alive request still ends as a real
// 504 with a server message; this only catches a connection that stalls with
// no response at all, which would otherwise spin the UI forever. The
// LLM-backed endpoints are bounded server-side by
// settings.llm_call_budget_seconds — this is not the mechanism that protects
// the worker, only the one that protects the user's screen.
const WRITE_TIMEOUT_MS = 330_000;

export const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(WRITE_TIMEOUT_MS),
  });
