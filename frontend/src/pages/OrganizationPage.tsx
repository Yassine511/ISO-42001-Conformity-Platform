import { useCallback, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Doc } from "../api";

const STATUS_STYLES: Record<Doc["status"], string> = {
  parsed: "bg-emerald-100 text-emerald-700",
  uploaded: "bg-amber-100 text-amber-700",
  failed: "bg-red-100 text-red-700",
};

const STATUS_LABELS: Record<Doc["status"], string> = {
  parsed: "Analysé",
  uploaded: "Téléversé",
  failed: "Échec",
};

export default function OrganizationPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);

  const docs = useQuery({
    queryKey: ["documents", orgId],
    queryFn: () => api.listDocuments(orgId!),
    enabled: !!orgId,
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(orgId!, file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents", orgId] }),
  });

  const remove = useMutation({
    mutationFn: api.deleteDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents", orgId] }),
  });

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files) return;
      setUploadErrors([]);
      for (const file of Array.from(files)) {
        try {
          await upload.mutateAsync(file);
        } catch (err) {
          setUploadErrors((prev) => [...prev, `${file.name} : ${(err as Error).message}`]);
        }
      }
    },
    [upload],
  );

  return (
    <div className="space-y-6">
      <Link to="/" className="text-sm text-indigo-600 hover:underline">
        ← Organisations
      </Link>

      <div>
        <h1 className="text-2xl font-semibold">Documents de politique</h1>
        <p className="mt-1 text-sm text-slate-500">
          PDF, DOCX, TXT ou Markdown — 20 Mo maximum par fichier.
        </p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-xl border-2 border-dashed p-10 text-center transition ${
          dragOver ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-white"
        }`}
      >
        <p className="text-sm text-slate-600">
          Glissez-déposez vos documents ici, ou <span className="text-indigo-600">parcourir</span>
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          className="hidden"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
        {upload.isPending && <p className="mt-2 text-sm text-indigo-600">Téléversement…</p>}
      </div>

      {uploadErrors.map((msg) => (
        <p key={msg} className="text-sm text-red-600">
          {msg}
        </p>
      ))}

      <ul className="divide-y rounded-xl border border-slate-200 bg-white">
        {docs.data?.length === 0 && (
          <li className="p-4 text-sm text-slate-500">Aucun document pour le moment.</li>
        )}
        {docs.data?.map((doc) => (
          <li key={doc.id} className="flex items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{doc.filename}</div>
              <div className="text-xs text-slate-500">
                {doc.page_count} page{doc.page_count > 1 ? "s" : ""}
                {doc.error ? ` — ${doc.error}` : ""}
              </div>
            </div>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[doc.status]}`}
            >
              {STATUS_LABELS[doc.status]}
            </span>
            <button
              onClick={() => remove.mutate(doc.id)}
              className="rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-red-50 hover:text-red-600"
            >
              Supprimer
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
