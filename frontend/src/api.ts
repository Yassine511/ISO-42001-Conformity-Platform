export interface Organization {
  id: string;
  name: string;
  created_at: string;
}

export interface Doc {
  id: string;
  organization_id: string;
  filename: string;
  content_type: string;
  status: "uploaded" | "parsed" | "failed";
  error: string | null;
  page_count: number;
  created_at: string;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Erreur ${res.status}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  listOrganizations: () => fetch("/api/organizations").then((r) => json<Organization[]>(r)),
  createOrganization: (name: string) =>
    fetch("/api/organizations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).then((r) => json<Organization>(r)),
  listDocuments: (orgId: string) =>
    fetch(`/api/organizations/${orgId}/documents`).then((r) => json<Doc[]>(r)),
  uploadDocument: (orgId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`/api/organizations/${orgId}/documents`, { method: "POST", body: form }).then(
      (r) => json<Doc>(r),
    );
  },
  deleteDocument: (docId: string) =>
    fetch(`/api/documents/${docId}`, { method: "DELETE" }).then((r) => json<void>(r)),
};
