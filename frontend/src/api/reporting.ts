// Conformity, risk register, SoA, trust panel and PDF export (M8).
// Domain slice of the API client — assembled into `api` by ./index.ts.
import { json } from "./http";
import type {
  ConformityReport,
  ReportingParams,
  RiskRegister,
  SoaDecision,
  SoaTable,
  TrustPanel,
} from "./types";

// Query-string builder for the reporting endpoints: private to this slice,
// since every reporting route takes the same optional scope parameters.
function reportingQuery(params?: ReportingParams): string {
  const q = new URLSearchParams();
  if (params?.assessmentId) q.set("assessment_id", params.assessmentId);
  if (params?.scoringPolicyVersion) q.set("scoring_policy_version", params.scoringPolicyVersion);
  if (params?.includePreliminary) q.set("include_preliminary", "true");
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const reportingApi = {
  // reporting (M8)
  getConformity: (orgId: string, params?: ReportingParams) =>
    fetch(`/api/organizations/${orgId}/reporting/conformity${reportingQuery(params)}`).then(
      (r) => json<ConformityReport>(r),
    ),
  getTrustPanel: (orgId: string, params?: ReportingParams) =>
    fetch(`/api/organizations/${orgId}/reporting/trust${reportingQuery(params)}`).then((r) =>
      json<TrustPanel>(r),
    ),
  getRiskRegister: (orgId: string, params?: ReportingParams) =>
    fetch(`/api/organizations/${orgId}/reporting/risk-register${reportingQuery(params)}`).then(
      (r) => json<RiskRegister>(r),
    ),

  getSoa: (orgId: string, params?: ReportingParams) =>
    fetch(`/api/organizations/${orgId}/reporting/soa${reportingQuery(params)}`).then((r) =>
      json<SoaTable>(r),
    ),
  putSoaControl: (
    orgId: string,
    controlId: string,
    body: { applicable: boolean; justification_fr: string; editor_label?: string },
  ) =>
    fetch(`/api/organizations/${orgId}/reporting/soa/${controlId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) =>
      json<{
        control_id: string;
        applicable: boolean;
        justification_fr: string;
        decision_count: number;
      }>(r),
    ),
  // server-generated PDF, used directly as <a href> (versionDownloadUrl pattern)
  reportDownloadUrl: (orgId: string, params?: ReportingParams) =>
    `/api/organizations/${orgId}/reporting/report.pdf${reportingQuery(params)}`,
  getSoaHistory: (orgId: string, controlId: string) =>
    fetch(`/api/organizations/${orgId}/reporting/soa/${controlId}/history`).then((r) =>
      json<SoaDecision[]>(r),
    ),
};
