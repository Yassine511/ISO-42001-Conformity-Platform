// Remediation cases, plans, actions, patches and versions (M7).
// Domain slice of the API client — assembled into `api` by ./index.ts.
import { activation, json, post } from "./http";
import type {
  Classification,
  DocumentVersionSummary,
  LinkSuggestion,
  PatchProposalView,
  Reassessment,
  RemediationAction,
  RemediationArtifactView,
  RemediationCase,
  RemediationCaseDetail,
  RemediationPlan,
  RemediationScope,
  TriageDraft,
} from "./types";

export const remediationApi = {
  // remediation
  listCases: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/remediation-cases`).then((r) =>
      json<RemediationCase[]>(r),
    ),
  getCase: (orgId: string, caseId: string) =>
    fetch(`/api/organizations/${orgId}/remediation-cases/${caseId}`).then((r) =>
      json<RemediationCaseDetail>(r),
    ),
  createCase: (orgId: string, body: { finding_id: string; title?: string }) =>
    post(`/api/organizations/${orgId}/remediation-cases`, body).then((r) =>
      json<RemediationCaseDetail>(r),
    ),
  linkSuggestions: (orgId: string, caseId: string) =>
    fetch(`/api/organizations/${orgId}/remediation-cases/${caseId}/link-suggestions`).then(
      (r) => json<LinkSuggestion[]>(r),
    ),
  linkFinding: (
    orgId: string,
    caseId: string,
    body: {
      finding_id: string;
      decision: "link" | "reject";
      link_source?: "search_suggested" | "manual";
      link_note?: string;
    },
  ) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/findings`, body).then(
      (r) => json<RemediationCaseDetail>(r),
    ),
  unlinkFinding: (orgId: string, caseId: string, findingId: string) =>
    fetch(`/api/organizations/${orgId}/remediation-cases/${caseId}/findings/${findingId}`, {
      method: "DELETE",
    }).then((r) => json<RemediationCaseDetail>(r)),
  redraftTriage: (orgId: string, caseId: string) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/triage/redraft`, {}).then(
      (r) => json<TriageDraft>(r),
    ),
  approveTriage: (
    orgId: string,
    caseId: string,
    body: {
      triage_draft_id: string;
      classification?: Classification;
      correction_note?: string;
      scope?: RemediationScope;
      scope_rationale?: string;
      reviewer_label?: string;
    },
  ) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/triage/approve`, body).then(
      (r) => json<RemediationCaseDetail>(r),
    ),
  reopenTriage: (orgId: string, caseId: string) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/triage/reopen`, {}).then(
      (r) => json<RemediationCaseDetail>(r),
    ),
  draftPlan: (orgId: string, caseId: string) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/plans`, {}).then((r) =>
      json<RemediationPlan>(r),
    ),
  reviewAction: (
    orgId: string,
    caseId: string,
    actionId: string,
    body: {
      action: "approve" | "edit" | "reject";
      description?: string;
      rationale?: string;
      owner_role?: string;
      success_criterion?: string;
      priority?: "haute" | "normale" | "basse";
      due_date?: string; // ISO date — omitted keeps the current value
      impacted_requirement_ids?: string[];
      review_note?: string;
      reviewer_label?: string;
    },
  ) =>
    post(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/actions/${actionId}/review`,
      body,
    ).then((r) => json<RemediationAction>(r)),
  changeLifecycle: (
    orgId: string,
    caseId: string,
    actionId: string,
    lifecycle: "IN_PROGRESS" | "DONE" | "CANCELLED",
  ) =>
    post(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/actions/${actionId}/lifecycle`,
      { lifecycle },
    ).then((r) => json<RemediationAction>(r)),
  recordEffectiveness: (
    orgId: string,
    caseId: string,
    actionId: string,
    body: {
      effectiveness: "EFFECTIVE" | "PARTIALLY_EFFECTIVE" | "INEFFECTIVE";
      note: string;
      reassessment_id?: string | null;
    },
  ) =>
    post(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/actions/${actionId}/effectiveness`,
      body,
    ).then((r) => json<RemediationAction>(r)),
  launchReassessment: (orgId: string, caseId: string, selectedActionIds: string[]) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/reassessments`, {
      selected_action_ids: selectedActionIds,
    }).then((r) => json<Reassessment>(r)),
  listReassessments: (orgId: string, caseId: string) =>
    fetch(`/api/organizations/${orgId}/remediation-cases/${caseId}/reassessments`).then((r) =>
      json<Reassessment[]>(r),
    ),
  closeCase: (orgId: string, caseId: string, closeNote: string) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/close`, {
      close_note: closeNote,
    }).then((r) => json<RemediationCaseDetail>(r)),
  reopenCase: (orgId: string, caseId: string) =>
    post(`/api/organizations/${orgId}/remediation-cases/${caseId}/reopen`, {}).then((r) =>
      json<RemediationCaseDetail>(r),
    ),
  // 0018 human case-planning update under an optimistic revision check
  // (a stale expected_revision is a 409, never a silent overwrite)
  updateCasePlanning: (
    orgId: string,
    caseId: string,
    body: {
      expected_revision: number;
      owner_role?: string | null;
      due_date?: string | null;
      closure_criterion?: string | null;
      editor_label?: string | null;
    },
  ) =>
    fetch(`/api/organizations/${orgId}/remediation-cases/${caseId}/planning`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => json<RemediationCaseDetail>(r)),

  // M7b document versions + patch flow
  listDocumentVersions: (docId: string) =>
    fetch(`/api/documents/${docId}/versions`).then((r) => json<DocumentVersionSummary[]>(r)),
  versionDownloadUrl: (docId: string, versionId: string) =>
    `/api/documents/${docId}/versions/${versionId}/download`,
  // Re-drive a stranded superseding-upload activation (INDEX_FAILED after a
  // Qdrant outage, or PENDING_INDEX after an assessment conflict).
  recoverUpload: (docId: string, versionId: string) =>
    post(`/api/documents/${docId}/versions/${versionId}/recover`, {}).then((r) => activation(r)),
  createPatchProposal: (orgId: string, caseId: string, actionId: string, documentId: string) =>
    post(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/actions/${actionId}/patch-proposals`,
      { document_id: documentId },
    ).then((r) => json<PatchProposalView>(r)),
  listPatchProposals: (orgId: string, caseId: string, actionId: string) =>
    fetch(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/actions/${actionId}/patch-proposals`,
    ).then((r) => json<PatchProposalView[]>(r)),
  getPatchProposal: (orgId: string, caseId: string, proposalId: string) =>
    fetch(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/patch-proposals/${proposalId}`,
    ).then((r) => json<PatchProposalView>(r)),
  decidePatch: (
    orgId: string,
    caseId: string,
    proposalId: string,
    body: { decision: "approve" | "edit" | "reject"; final_text_fr?: string; actor_label?: string },
  ) =>
    post(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/patch-proposals/${proposalId}/decision`,
      body,
    ).then((r) => activation(r)),
  recoverPatch: (orgId: string, caseId: string, proposalId: string) =>
    post(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/patch-proposals/${proposalId}/recover`,
      {},
    ).then((r) => activation(r)),
  createArtifact: (orgId: string, caseId: string, actionId: string, documentId: string) =>
    post(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/actions/${actionId}/artifacts`,
      { document_id: documentId },
    ).then((r) => json<RemediationArtifactView>(r)),
  listArtifacts: (orgId: string, caseId: string, actionId: string) =>
    fetch(
      `/api/organizations/${orgId}/remediation-cases/${caseId}/actions/${actionId}/artifacts`,
    ).then((r) => json<RemediationArtifactView[]>(r)),
  artifactDownloadUrl: (orgId: string, caseId: string, artifactId: string) =>
    `/api/organizations/${orgId}/remediation-cases/${caseId}/artifacts/${artifactId}/download`,
};
