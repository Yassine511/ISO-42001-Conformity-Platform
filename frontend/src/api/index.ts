/**
 * The API client, assembled from per-domain slices.
 *
 * This file exists to keep ONE import surface: every caller still does
 * `import { api, type Doc } from "../api"` exactly as it did when this was a
 * single 1 259-line module. The split is internal — domain modules are never
 * imported directly, so a call site never has to know which slice owns an
 * endpoint, and moving one between slices stays a local change.
 *
 *   types.ts   every request/response interface + shared constants
 *   http.ts    ApiError, the two response readers, the POST helper
 *   auth.ts | assessments.ts | remediation.ts | reporting.ts | chat.ts
 */

import { assessmentsApi } from "./assessments";
import { authApi } from "./auth";
import { chatApi } from "./chat";
import { remediationApi } from "./remediation";
import { reportingApi } from "./reporting";

export * from "./types";
export { ApiError } from "./http";

export const api = {
  ...authApi,
  ...assessmentsApi,
  ...remediationApi,
  ...reportingApi,
  ...chatApi,
};
