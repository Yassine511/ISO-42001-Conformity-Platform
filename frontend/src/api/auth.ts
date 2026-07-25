// Auth, organizations, members and invitations (M10).
// Domain slice of the API client — assembled into `api` by ./index.ts.
import { activation, json, post } from "./http";
import type {
  Doc,
  IndexReport,
  InvitationCreated,
  InvitationPublic,
  Organization,
  OrganizationMember,
  PendingInvitation,
  SessionInfo,
} from "./types";

export const authApi = {
  // -- auth (M10). Cookies ride along automatically (same-origin fetch).
  me: () => fetch("/api/auth/me").then((r) => json<SessionInfo>(r)),
  login: (email: string, password: string) =>
    post("/api/auth/login", { email, password }).then((r) => json<SessionInfo>(r)),
  signup: (body: {
    email: string;
    password: string;
    display_name: string;
    organization_name: string;
  }) => post("/api/auth/signup", body).then((r) => json<SessionInfo>(r)),
  logout: () => post("/api/auth/logout").then((r) => json<void>(r)),
  createInvitation: (orgId: string, email: string) =>
    post(`/api/organizations/${orgId}/invitations`, { email }).then((r) =>
      json<InvitationCreated>(r),
    ),
  invitationInfo: (token: string) =>
    fetch(`/api/auth/invitations/${token}`).then((r) => json<InvitationPublic>(r)),
  // display_name is required only when the invitation creates a NEW account;
  // an existing user joins by authenticating with `password`
  acceptInvitation: (token: string, body: { password: string; display_name?: string }) =>
    post(`/api/auth/invitations/${token}/accept`, body).then((r) => json<SessionInfo>(r)),
  listInvitations: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/invitations`).then((r) =>
      json<PendingInvitation[]>(r),
    ),
  revokeInvitation: (orgId: string, invitationId: string) =>
    fetch(`/api/organizations/${orgId}/invitations/${invitationId}`, {
      method: "DELETE",
    }).then((r) => json<void>(r)),
  listMembers: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/members`).then((r) => json<OrganizationMember[]>(r)),
  removeMember: (orgId: string, userId: string) =>
    fetch(`/api/organizations/${orgId}/members/${userId}`, { method: "DELETE" }).then(
      (r) => json<void>(r),
    ),

  listOrganizations: () => fetch("/api/organizations").then((r) => json<Organization[]>(r)),
  createOrganization: (name: string) =>
    post("/api/organizations", { name }).then((r) => json<Organization>(r)),
  listDocuments: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/documents`).then((r) => json<Doc[]>(r)),
  uploadDocument: (orgId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`/api/organizations/${orgId}/documents`, { method: "POST", body: form }).then(
      (r) => json<Doc>(r),
    );
  },
  // Explicit human superseding re-upload — the only way a PDF/DOCX gets a new
  // version; optionally carries the artifact lineage to close the loop.
  supersedeUpload: (
    orgId: string,
    file: File,
    supersedesVersionId: string,
    remediationArtifactId?: string,
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("supersedes_version_id", supersedesVersionId);
    if (remediationArtifactId) form.append("remediation_artifact_id", remediationArtifactId);
    return fetch(`/api/organizations/${orgId}/documents`, { method: "POST", body: form }).then(
      (r) => activation(r),
    );
  },
  deleteDocument: (docId: string) =>
    fetch(`/api/documents/${docId}`, { method: "DELETE" }).then((r) => json<void>(r)),
  indexOrganization: (orgId: string) =>
    post(`/api/organizations/${orgId}/index`).then((r) => json<IndexReport>(r)),
};
