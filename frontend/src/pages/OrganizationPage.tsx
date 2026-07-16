import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  FileText,
  FileUp,
  MoreHorizontal,
  Play,
  Trash2,
  UserCheck,
} from "lucide-react";
import { api, type Assessment, type Doc } from "../api";
import { docStatusDisplay } from "@/lib/labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/empty-state";
import { NextActionPanel } from "@/components/next-action-panel";
import { PageHeader } from "@/components/page-header";
import { SectionHeading } from "@/components/section-heading";
import { StatusLabel } from "@/components/status-label";
import { TechnicalDisclosure, TechnicalRow } from "@/components/technical-disclosure";

// Pipeline node names -> French progress labels (raw node names never render)
const NODE_LABELS: Record<string, string> = {
  retrieve: "récupération",
  judge: "jugement",
  verify: "vérification",
};

/** Preuves et évaluations — evaluations dominate, the document library is the
    narrower column (spec §8.3). An evaluation always uses every prepared
    document: there is deliberately no document-selection UI. */
export default function OrganizationPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const [searchParams] = useSearchParams();
  const vue = searchParams.get("vue");
  const uploadRef = useRef<HTMLInputElement>(null);

  const docs = useQuery({
    queryKey: ["documents", orgId],
    queryFn: () => api.listDocuments(orgId!),
  });
  const assessments = useQuery({
    queryKey: ["assessments", orgId],
    queryFn: () => api.listAssessments(orgId!),
    // Poll while any run is live: findings persist row-by-row, so the list
    // payload is authoritative progress; stop polling once nothing runs.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((a) => a.status === "RUNNING") ? 2000 : false,
  });

  return (
    <div className="space-y-8">
      <PageHeader
        title="Preuves et évaluations"
        description="Déposez les documents de l'organisation, puis lancez des évaluations : l'IA propose un constat par exigence, que vous confirmez ensuite."
      />

      {vue === "revue" && <ReviewRedirectNotice assessments={assessments.data} />}

      <EvaluationNextAction
        orgId={orgId!}
        assessments={assessments.data}
        docs={docs.data}
        onAddEvidence={() => uploadRef.current?.click()}
      />

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
        <AssessmentsSection orgId={orgId!} docs={docs.data} assessments={assessments} />
        <DocumentsSection orgId={orgId!} docs={docs} uploadRef={uploadRef} highlight={vue === "preuves"} />
      </div>
    </div>
  );
}

/** « Revue humaine » landed here because no assessment has findings yet. */
function ReviewRedirectNotice({ assessments }: { assessments: Assessment[] | undefined }) {
  if (!assessments) return null;
  const reviewable = assessments.some((a) => a.findings_done > 0);
  if (reviewable) return null;
  return (
    <div className="flex items-start gap-3 rounded-lg border bg-card p-4">
      <UserCheck className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <div className="text-sm leading-relaxed">
        <p className="font-medium">Rien à revoir pour le moment</p>
        <p className="text-muted-foreground">
          La revue humaine s'ouvre dès qu'une évaluation a produit des constats. Lancez une
          évaluation ci-dessous — chaque constat de l'IA attendra ensuite votre confirmation.
        </p>
      </div>
    </div>
  );
}

// ------------------------------------------------------------- next action

function EvaluationNextAction({
  orgId,
  assessments,
  docs,
  onAddEvidence,
}: {
  orgId: string;
  assessments: Assessment[] | undefined;
  docs: Doc[] | undefined;
  onAddEvidence: () => void;
}) {
  if (!assessments || !docs) return null;
  const base = `/organizations/${orgId}`;
  const running = assessments.find((a) => a.status === "RUNNING");
  if (running) {
    return (
      <NextActionPanel
        title="Une évaluation est en cours"
        description="Suivez la progression ci-dessous ; les constats apparaissent au fur et à mesure."
      />
    );
  }
  const pending = [...assessments]
    .filter((a) => a.status === "COMPLETED" && a.reviewed_count < a.findings_done)
    .sort((a, b) => b.started_at.localeCompare(a.started_at))[0];
  if (pending) {
    const remaining = pending.findings_done - pending.reviewed_count;
    return (
      <NextActionPanel
        title={`Confirmer ${remaining} constat${remaining > 1 ? "s" : ""} de la dernière évaluation`}
        description="Les verdicts proposés par l'IA ne comptent dans la conformité qu'après votre décision."
        actionLabel="Ouvrir la revue humaine"
        actionTo={`${base}/assessments/${pending.id}`}
      />
    );
  }
  if (docs.length === 0) {
    return (
      <NextActionPanel
        title="Commencez par préparer vos preuves"
        description="Déposez les politiques et procédures de l'organisation (PDF, DOCX, TXT ou Markdown)."
        actionLabel="Ajouter des preuves"
        onAction={onAddEvidence}
      />
    );
  }
  if (assessments.length === 0) {
    return (
      <NextActionPanel
        title="Lancez une première évaluation"
        description="Toutes les preuves préparées seront évaluées automatiquement, exigence par exigence."
      />
    );
  }
  return null;
}

// ------------------------------------------------------------- documents

function DocumentsSection({
  orgId,
  docs,
  uploadRef,
  highlight,
}: {
  orgId: string;
  docs: ReturnType<typeof useQuery<Doc[]>>;
  uploadRef: React.RefObject<HTMLInputElement | null>;
  highlight: boolean;
}) {
  const queryClient = useQueryClient();
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);

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

  const list = docs.data ?? [];
  const parsed = list.filter((d) => d.status === "parsed").length;
  const failed = list.filter((d) => d.status === "failed").length;

  return (
    <section
      aria-label="Bibliothèque de preuves"
      className={highlight ? "space-y-4 rounded-lg ring-2 ring-primary/30 ring-offset-4 ring-offset-background" : "space-y-4"}
    >
      <SectionHeading
        as="h2"
        title="Preuves"
        description="Chaque évaluation utilise automatiquement tous les documents préparés."
      />

      <div className="rounded-lg border bg-card p-4">
        <dl className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-sm">
          <div>
            <dt className="sr-only">Documents</dt>
            <dd>
              <span className="text-2xl font-semibold tabular-nums">{list.length}</span>{" "}
              <span className="text-muted-foreground">document{list.length > 1 ? "s" : ""}</span>
            </dd>
          </div>
          <div className="text-muted-foreground">
            {parsed} prêt{parsed > 1 ? "s" : ""}
            {failed > 0 && <span className="text-destructive"> · {failed} en échec</span>}
          </div>
        </dl>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => uploadRef.current?.click()}>
            <FileUp className="size-3.5" aria-hidden="true" />
            Ajouter des preuves
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => index.mutate()}
            disabled={index.isPending}
          >
            {index.isPending ? "Préparation…" : "Préparer pour l'évaluation"}
          </Button>
        </div>
        <input
          ref={uploadRef}
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
        <p aria-live="polite" className="mt-2 text-xs text-muted-foreground">
          {index.isSuccess &&
            `Index à jour : ${index.data.chunks} extraits (${index.data.added} ajoutés, ${index.data.removed} retirés).`}
          {index.isError && (
            <span className="text-destructive">{(index.error as Error).message}</span>
          )}
        </p>
      </div>

      {uploadErrors.map((msg) => (
        <p key={msg} className="text-sm text-destructive">
          {msg}
        </p>
      ))}
      {removeError && <p className="text-sm text-destructive">{removeError}</p>}

      <ul className="divide-y overflow-hidden rounded-lg border bg-card">
        {list.length === 0 && (
          <li className="p-4 text-sm text-muted-foreground">
            Aucun document pour le moment — PDF, DOCX, TXT ou Markdown, 20 Mo maximum.
          </li>
        )}
        {list.map((doc) => (
          <li key={doc.id} className="flex items-center gap-3 p-3">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-muted/50">
              <FileText className="size-3.5 text-muted-foreground" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-medium">{doc.filename}</div>
              <div className="text-xs text-muted-foreground">
                {doc.page_count} page{doc.page_count > 1 ? "s" : ""}
                {doc.error ? ` — ${doc.error}` : ""}
              </div>
            </div>
            <StatusLabel display={docStatusDisplay(doc.status)} dot={false} />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Actions pour ${doc.filename}`}
                  className="size-10"
                >
                  <MoreHorizontal className="size-4" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem variant="destructive" onClick={() => remove.mutate(doc.id)}>
                  <Trash2 className="size-3.5" aria-hidden="true" />
                  Supprimer
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ------------------------------------------------------------ assessments

function AssessmentsSection({
  orgId,
  docs,
  assessments,
}: {
  orgId: string;
  docs: Doc[] | undefined;
  assessments: ReturnType<typeof useQuery<Assessment[]>>;
}) {
  const queryClient = useQueryClient();
  const [launchError, setLaunchError] = useState<string | null>(null);

  const hasParsedDoc = (docs ?? []).some((d) => d.status === "parsed");

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
    <section aria-label="Évaluations" className="space-y-4">
      <SectionHeading
        as="h2"
        title="Évaluations"
        description="Un constat par exigence : citation localisée par le code, verdict à confirmer par vous."
      />

      <div className="rounded-lg border bg-card p-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => launch.mutate()}
            disabled={launch.isPending || running || !hasParsedDoc}
          >
            <Play className="size-4" aria-hidden="true" />
            {launch.isPending ? "Indexation puis lancement…" : "Lancer l'évaluation"}
          </Button>
          <p className="text-sm text-muted-foreground">
            Toutes les preuves préparées sont évaluées automatiquement.
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
      </div>

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

      <TechnicalDisclosure summary="Détails techniques des évaluations">
        <p>
          Chaque exigence passe par récupération → jugement → vérification. Le périmètre par
          défaut est le jeu d'exigences de développement (51) ; le jeu de test est réservé à
          l'évaluation de référence et n'est pas accessible depuis cette interface. Les
          métadonnées de corpus et de recherche figurent sur chaque évaluation ci-dessus.
        </p>
      </TechnicalDisclosure>
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

  const startedAt = useMemo(() => new Date(a.started_at).toLocaleString("fr-FR"), [a.started_at]);
  const progressLabel =
    a.status === "RUNNING" && a.progress
      ? `Exigence ${Math.min(a.progress.done + 1, a.total)}/${a.total} — ${a.progress.requirement_id} · nœud : ${NODE_LABELS[a.progress.node] ?? "traitement"}`
      : null;

  const statusBadge =
    a.status === "RUNNING" ? (
      <Badge variant="info" className="gap-1.5">
        <span aria-hidden className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
        En cours
      </Badge>
    ) : a.status === "COMPLETED" ? (
      <Badge variant="success">Terminée</Badge>
    ) : (
      <Badge variant="danger">Échouée</Badge>
    );

  return (
    <li className="space-y-3 rounded-lg border bg-card p-5">
      <div className="flex flex-wrap items-center gap-3">
        {statusBadge}
        <span className="text-sm font-medium">{startedAt}</span>
        {!a.manifest_complete && (
          <Badge variant="neutral">manifeste incomplet (évaluation antérieure)</Badge>
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
          className="h-2 w-full overflow-hidden rounded [&::-moz-progress-bar]:bg-primary [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:bg-primary"
          value={a.findings_done}
          max={Math.max(a.total, 1)}
          aria-label="Progression de l'évaluation"
        />
        <div aria-live="polite" className="flex flex-wrap gap-x-4 text-xs text-muted-foreground">
          <span className="tabular-nums">
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

      <div className="flex flex-wrap items-center justify-between gap-3">
        {a.findings_done > 0 ? (
          <Link
            to={`/organizations/${orgId}/assessments/${a.id}`}
            className="inline-flex min-h-10 items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
          >
            Ouvrir l'espace de revue
            <ArrowRight className="size-3.5" aria-hidden="true" />
          </Link>
        ) : (
          <span />
        )}
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer list-none rounded font-medium select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
            Détails techniques
          </summary>
          <div className="mt-2 rounded-md border border-dashed bg-muted/30 p-2">
            <TechnicalRow label="Identifiant" value={a.id} />
            <TechnicalRow label="Version du corpus" value={a.corpus_version} />
            <TechnicalRow label="Profondeur de recherche" value={String(a.retrieval_k)} />
            {a.document_manifest && (
              <TechnicalRow
                label="Manifeste documentaire"
                value={`${a.document_manifest.documents.length} documents · ${a.document_manifest.chunk_count} extraits`}
              />
            )}
          </div>
        </details>
      </div>
    </li>
  );
}
