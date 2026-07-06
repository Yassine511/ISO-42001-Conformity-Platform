import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Assessment, type Doc } from "../api";
import { AssessmentStatusBadge } from "../components/StatusBadge";

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

// Pipeline node names -> French progress labels
const NODE_LABELS: Record<string, string> = {
  retrieve: "récupération",
  judge: "jugement",
  verify: "vérification",
};

export default function OrganizationPage() {
  const { orgId } = useParams<{ orgId: string }>();
  return (
    <div className="space-y-10">
      <div className="flex items-center justify-between">
        <Link to="/" className="text-sm text-indigo-600 hover:underline">
          ← Organisations
        </Link>
        <Link
          to={`/organizations/${orgId}/chat`}
          className="rounded-lg border border-indigo-300 px-3 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
        >
          💬 Copilote
        </Link>
      </div>
      <DocumentsSection orgId={orgId!} />
      <AssessmentsSection orgId={orgId!} />
    </div>
  );
}

// ------------------------------------------------------------- documents

function DocumentsSection({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);

  const docs = useQuery({
    queryKey: ["documents", orgId],
    queryFn: () => api.listDocuments(orgId),
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(orgId, file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents", orgId] }),
  });

  const remove = useMutation({
    mutationFn: api.deleteDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents", orgId] }),
  });
  // The backend deliberately refuses some deletes (409: cited as evidence by a
  // finding, or an assessment is running; 503: vector index down) — those
  // refusals must be visible.
  const removeError = remove.isError ? (remove.error as Error).message : null;

  const index = useMutation({ mutationFn: () => api.indexOrganization(orgId) });

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
    <section className="space-y-6">
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
        className={`rounded-xl border-2 border-dashed p-10 text-center transition ${
          dragOver ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-white"
        }`}
      >
        <p className="text-sm text-slate-600">
          Glissez-déposez vos documents ici, ou{" "}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="rounded text-indigo-600 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
          >
            parcourir vos fichiers
          </button>
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          aria-label="Téléverser des documents de politique"
          className="sr-only"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
        {upload.isPending && (
          <p aria-live="polite" className="mt-2 text-sm text-indigo-600">
            Téléversement…
          </p>
        )}
      </div>

      {uploadErrors.map((msg) => (
        <p key={msg} className="text-sm text-red-600">
          {msg}
        </p>
      ))}

      {removeError && <p className="text-sm text-red-600">{removeError}</p>}

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
              className="rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-red-50 hover:text-red-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-500"
            >
              Supprimer
            </button>
          </li>
        ))}
      </ul>

      <div className="flex items-center gap-3">
        <button
          onClick={() => index.mutate()}
          disabled={index.isPending}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
        >
          {index.isPending ? "Indexation…" : "Indexer les documents"}
        </button>
        <span aria-live="polite" className="text-sm text-slate-500">
          {index.isSuccess &&
            `Index à jour : ${index.data.chunks} extraits (${index.data.added} ajoutés, ${index.data.removed} retirés).`}
          {index.isError && (
            <span className="text-red-600">{(index.error as Error).message}</span>
          )}
        </span>
      </div>
    </section>
  );
}

// ------------------------------------------------------------ assessments

function AssessmentsSection({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const [launchError, setLaunchError] = useState<string | null>(null);

  const docs = useQuery({
    queryKey: ["documents", orgId],
    queryFn: () => api.listDocuments(orgId),
  });
  const hasParsedDoc = (docs.data ?? []).some((d) => d.status === "parsed");

  const assessments = useQuery({
    queryKey: ["assessments", orgId],
    queryFn: () => api.listAssessments(orgId),
    // Poll while any run is live: findings persist row-by-row, so the list
    // payload is authoritative progress; stop polling once nothing runs.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((a) => a.status === "RUNNING") ? 2000 : false,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["assessments", orgId] });

  const launch = useMutation({
    mutationFn: () => api.createAssessment(orgId, {}),
    onSuccess: () => {
      setLaunchError(null);
      invalidate();
    },
    onError: (err) => setLaunchError((err as Error).message),
  });

  const running = (assessments.data ?? []).some((a) => a.status === "RUNNING");

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Évaluations de conformité</h2>
        <p className="mt-1 text-sm text-slate-500">
          Chaque exigence passe par récupération → jugement → vérification ; les citations sont
          vérifiées par le code, puis chaque constat attend votre confirmation.
        </p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-center gap-4">
          <button
            onClick={() => launch.mutate()}
            disabled={launch.isPending || running || !hasParsedDoc}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500"
          >
            {launch.isPending ? "Indexation puis lancement…" : "Lancer l'évaluation"}
          </button>
          <p className="text-sm text-slate-500">
            Exigences de développement (51) — le jeu de test est réservé à l'évaluation M6.
          </p>
        </div>
        {!hasParsedDoc && (
          <p className="mt-3 text-sm text-amber-700">
            Téléversez au moins un document analysé avant de lancer une évaluation.
          </p>
        )}
        {running && (
          <p className="mt-3 text-sm text-slate-500">
            Une évaluation est déjà en cours — attendez sa fin ou abandonnez-la.
          </p>
        )}
        {launchError && <p className="mt-3 text-sm text-red-600">{launchError}</p>}
      </div>

      <ul className="space-y-3">
        {assessments.data?.length === 0 && (
          <li className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">
            Aucune évaluation pour le moment.
          </li>
        )}
        {assessments.data?.map((a) => (
          <AssessmentCard key={a.id} orgId={orgId} assessment={a} onChanged={invalidate} />
        ))}
      </ul>
    </section>
  );
}

function AssessmentCard({
  orgId,
  assessment: a,
  onChanged,
}: {
  orgId: string;
  assessment: Assessment;
  onChanged: () => void;
}) {
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmAbandon, setConfirmAbandon] = useState(false);

  const resume = useMutation({
    mutationFn: () => api.resumeAssessment(orgId, a.id),
    onSuccess: onChanged,
    onError: (err) => setActionError((err as Error).message),
  });
  const abandon = useMutation({
    mutationFn: () => api.abandonAssessment(orgId, a.id),
    onSuccess: () => {
      setConfirmAbandon(false);
      onChanged();
    },
    onError: (err) => setActionError((err as Error).message),
  });

  const startedAt = useMemo(
    () => new Date(a.started_at).toLocaleString("fr-FR"),
    [a.started_at],
  );
  const progressLabel =
    a.status === "RUNNING" && a.progress
      ? `Exigence ${Math.min(a.progress.done + 1, a.total)}/${a.total} — ${a.progress.requirement_id} · nœud : ${NODE_LABELS[a.progress.node] ?? a.progress.node}`
      : null;

  return (
    <li className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-3">
        <AssessmentStatusBadge status={a.status} />
        <span className="text-sm text-slate-600">{startedAt}</span>
        <span className="text-xs text-slate-400">corpus {a.corpus_version} · k={a.retrieval_k}</span>
        {!a.manifest_complete && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            manifeste incomplet (antérieure à M5)
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {a.status === "RUNNING" && a.cancel_requested && (
            <span className="text-xs text-slate-500">Annulation en cours…</span>
          )}
          {a.status === "RUNNING" && !a.cancel_requested && (
            <>
              <button
                onClick={() => resume.mutate()}
                className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
              >
                Reprendre
              </button>
              {confirmAbandon ? (
                <span className="flex items-center gap-2 text-xs">
                  Abandonner cette évaluation ?
                  <button
                    onClick={() => abandon.mutate()}
                    className="rounded-lg bg-red-600 px-2.5 py-1 font-medium text-white hover:bg-red-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-500"
                  >
                    Confirmer
                  </button>
                  <button
                    onClick={() => setConfirmAbandon(false)}
                    className="rounded-lg border border-slate-300 px-2.5 py-1 text-slate-600 hover:bg-slate-50"
                  >
                    Non
                  </button>
                </span>
              ) : (
                <button
                  onClick={() => setConfirmAbandon(true)}
                  className="rounded-lg border border-red-200 px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-500"
                >
                  Abandonner
                </button>
              )}
            </>
          )}
        </div>
      </div>

      <div className="space-y-1">
        <progress
          className="h-2 w-full overflow-hidden rounded [&::-moz-progress-bar]:bg-indigo-500 [&::-webkit-progress-bar]:bg-slate-100 [&::-webkit-progress-value]:bg-indigo-500"
          value={a.findings_done}
          max={Math.max(a.total, 1)}
          aria-label="Progression de l'évaluation"
        />
        <div aria-live="polite" className="flex flex-wrap gap-x-4 text-xs text-slate-500">
          <span>
            {a.findings_done}/{a.total} constats
          </span>
          <span className="text-emerald-700">{a.verified_count} vérifiés</span>
          <span className="text-amber-700">{a.abstained_count} abstentions</span>
          <span>{a.reviewed_count} confirmés</span>
          {progressLabel && <span className="text-indigo-600">{progressLabel}</span>}
        </div>
      </div>

      {a.error && <p className="text-xs text-red-600">{a.error}</p>}
      {actionError && <p className="text-xs text-red-600">{actionError}</p>}

      {a.findings_done > 0 && (
        <Link
          to={`/organizations/${orgId}/assessments/${a.id}`}
          className="inline-block text-sm font-medium text-indigo-600 hover:underline"
        >
          Ouvrir l'espace de revue →
        </Link>
      )}
    </li>
  );
}
