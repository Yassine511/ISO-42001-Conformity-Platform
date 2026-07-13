import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FileText, FileUp, MoreHorizontal, Play, Trash2 } from "lucide-react";
import { api, type Assessment, type Doc } from "../api";
import { AssessmentStatusBadge } from "../components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { cn } from "@/lib/utils";

const STATUS_VARIANTS: Record<Doc["status"], "success" | "warning" | "danger"> = {
  parsed: "success",
  uploaded: "warning",
  failed: "danger",
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
    <div className="space-y-12">
      <PageHeader
        title="Évaluations & documents"
        description="Téléversez vos documents de politique, préparez-les pour l'évaluation, puis lancez et suivez les évaluations de conformité."
      />
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
    <section className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Bibliothèque documentaire</h2>
        <p className="mt-1 text-sm text-muted-foreground">
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
        className={cn(
          "rounded-2xl border-2 border-dashed p-12 text-center transition-colors duration-300",
          dragOver ? "border-foreground bg-accent" : "border-border bg-card",
        )}
      >
        <div className="mx-auto flex size-11 items-center justify-center rounded-full border bg-muted">
          <FileUp className="size-5 text-muted-foreground" aria-hidden="true" />
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          Glissez-déposez vos documents ici, ou{" "}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="rounded font-medium text-foreground underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-ring"
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
          <p aria-live="polite" className="mt-2 text-sm font-medium">
            Téléversement…
          </p>
        )}
      </div>

      {uploadErrors.map((msg) => (
        <p key={msg} className="text-sm text-destructive">
          {msg}
        </p>
      ))}

      {removeError && <p className="text-sm text-destructive">{removeError}</p>}

      <ul className="divide-y overflow-hidden rounded-2xl border bg-card shadow-xs">
        {docs.data?.length === 0 && (
          <li className="p-5 text-sm text-muted-foreground">Aucun document pour le moment.</li>
        )}
        {docs.data?.map((doc) => (
          <li key={doc.id} className="flex items-center gap-3 p-4 transition-colors hover:bg-muted/40">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-muted/50">
              <FileText className="size-4 text-muted-foreground" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{doc.filename}</div>
              <div className="text-xs text-muted-foreground">
                {doc.page_count} page{doc.page_count > 1 ? "s" : ""}
                {doc.error ? ` — ${doc.error}` : ""}
              </div>
            </div>
            <Badge variant={STATUS_VARIANTS[doc.status]}>{STATUS_LABELS[doc.status]}</Badge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Actions pour ${doc.filename}`}
                  className="size-9"
                >
                  <MoreHorizontal className="size-4" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  variant="destructive"
                  onClick={() => remove.mutate(doc.id)}
                >
                  <Trash2 className="size-3.5" aria-hidden="true" />
                  Supprimer
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          className="rounded-full"
          onClick={() => index.mutate()}
          disabled={index.isPending}
        >
          {index.isPending ? "Préparation…" : "Préparer les documents pour l'évaluation"}
        </Button>
        <span aria-live="polite" className="text-sm text-muted-foreground">
          {index.isSuccess &&
            `Index à jour : ${index.data.chunks} extraits (${index.data.added} ajoutés, ${index.data.removed} retirés).`}
          {index.isError && (
            <span className="text-destructive">{(index.error as Error).message}</span>
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
    <section className="space-y-5 border-t pt-10">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Évaluations de conformité</h2>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Chaque exigence passe par récupération → jugement → vérification ; les citations sont
          vérifiées par le code, puis chaque constat attend votre confirmation.
        </p>
      </div>

      <Card className="py-5">
        <CardContent className="px-5">
          <div className="flex flex-wrap items-center gap-4">
            <Button
              className="rounded-full"
              onClick={() => launch.mutate()}
              disabled={launch.isPending || running || !hasParsedDoc}
            >
              <Play className="size-4" aria-hidden="true" />
              {launch.isPending ? "Indexation puis lancement…" : "Lancer l'évaluation"}
            </Button>
            <p className="text-sm text-muted-foreground">
              Exigences de développement (51) — le jeu de test est réservé à l'évaluation M6.
            </p>
          </div>
          {!hasParsedDoc && (
            <p className="mt-3 text-sm text-warning-foreground dark:text-warning">
              Téléversez au moins un document analysé avant de lancer une évaluation.
            </p>
          )}
          {running && (
            <p className="mt-3 text-sm text-muted-foreground">
              Une évaluation est déjà en cours — attendez sa fin ou abandonnez-la.
            </p>
          )}
          {launchError && <p className="mt-3 text-sm text-destructive">{launchError}</p>}
        </CardContent>
      </Card>

      <ul className="space-y-3">
        {assessments.data?.length === 0 && (
          <li>
            <EmptyState
              icon={FileText}
              title="Aucune évaluation pour le moment."
              description="Lancez une première évaluation dès qu'un document est analysé."
            />
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
    <li className="space-y-3 rounded-2xl border bg-card p-5 shadow-xs transition-shadow duration-300 hover:shadow-[0_10px_30px_-14px_rgba(0,0,0,0.15)]">
      <div className="flex flex-wrap items-center gap-3">
        <AssessmentStatusBadge status={a.status} />
        <span className="text-sm font-medium">{startedAt}</span>
        <span className="font-mono text-xs text-muted-foreground">
          corpus {a.corpus_version} · k={a.retrieval_k}
        </span>
        {!a.manifest_complete && (
          <Badge variant="neutral">manifeste incomplet (antérieure à M5)</Badge>
        )}
        <div className="ml-auto flex items-center gap-2">
          {a.status === "RUNNING" && a.cancel_requested && (
            <span className="text-xs text-muted-foreground">Annulation en cours…</span>
          )}
          {a.status === "RUNNING" && !a.cancel_requested && (
            <>
              <Button variant="outline" size="sm" onClick={() => resume.mutate()}>
                Reprendre
              </Button>
              {confirmAbandon ? (
                <span className="flex items-center gap-2 text-xs">
                  Abandonner cette évaluation ?
                  <Button variant="destructive" size="sm" onClick={() => abandon.mutate()}>
                    Confirmer
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setConfirmAbandon(false)}>
                    Non
                  </Button>
                </span>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  onClick={() => setConfirmAbandon(true)}
                >
                  Abandonner
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      <div className="space-y-1.5">
        <progress
          className="h-2 w-full overflow-hidden rounded [&::-moz-progress-bar]:bg-foreground [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:bg-foreground"
          value={a.findings_done}
          max={Math.max(a.total, 1)}
          aria-label="Progression de l'évaluation"
        />
        <div aria-live="polite" className="flex flex-wrap gap-x-4 text-xs text-muted-foreground">
          <span>
            {a.findings_done}/{a.total} constats
          </span>
          <span className="text-success">{a.verified_count} vérifiés</span>
          <span className="text-warning-foreground dark:text-warning">
            {a.abstained_count} abstentions
          </span>
          <span>{a.reviewed_count} confirmés</span>
          {progressLabel && <span className="font-medium text-foreground">{progressLabel}</span>}
        </div>
      </div>

      {a.error && <p className="text-xs text-destructive">{a.error}</p>}
      {actionError && <p className="text-xs text-destructive">{actionError}</p>}

      {a.findings_done > 0 && (
        <Link
          to={`/organizations/${orgId}/assessments/${a.id}`}
          className="inline-flex items-center gap-1 text-sm font-medium underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
        >
          Ouvrir l'espace de revue
          <ArrowRight className="size-3.5" aria-hidden="true" />
        </Link>
      )}
    </li>
  );
}
