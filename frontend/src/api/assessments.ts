// Assessment runs, findings and human review (M3/M5).
// Domain slice of the API client — assembled into `api` by ./index.ts.
import { json, post } from "./http";
import type {
  Assessment,
  AssessmentDetail,
  FindingDetail,
  KbRequirement,
  ReviewDecision,
} from "./types";

export const assessmentsApi = {
  // assessments
  createAssessment: (orgId: string, body: { requirement_ids?: string[]; k?: number }) =>
    post(`/api/organizations/${orgId}/assessments`, body).then((r) => json<Assessment>(r)),
  listAssessments: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/assessments`).then((r) => json<Assessment[]>(r)),
  getAssessment: (orgId: string, assessmentId: string) =>
    fetch(`/api/organizations/${orgId}/assessments/${assessmentId}`).then((r) =>
      json<AssessmentDetail>(r),
    ),
  resumeAssessment: (orgId: string, assessmentId: string) =>
    post(`/api/organizations/${orgId}/assessments/${assessmentId}/resume`).then((r) =>
      json<Assessment>(r),
    ),
  abandonAssessment: (orgId: string, assessmentId: string) =>
    post(`/api/organizations/${orgId}/assessments/${assessmentId}/abandon`).then((r) =>
      json<Assessment>(r),
    ),
  listKbRequirements: () =>
    fetch("/api/kb/requirements").then((r) => json<KbRequirement[]>(r)),

  // findings / review
  getFinding: (orgId: string, assessmentId: string, findingId: string) =>
    fetch(`/api/organizations/${orgId}/assessments/${assessmentId}/findings/${findingId}`).then(
      (r) => json<FindingDetail>(r),
    ),
  reviewFinding: (
    orgId: string,
    assessmentId: string,
    findingId: string,
    decision: ReviewDecision,
  ) =>
    post(
      `/api/organizations/${orgId}/assessments/${assessmentId}/findings/${findingId}/review`,
      decision,
    ).then((r) => json<FindingDetail>(r)),
};
