// M7b document patching: proposals, decisions and artifacts.
// Split out of the 1 929-line RemediationCasePage — see that file.
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { abstainReasonDisplay, versionStateDisplay } from "@/lib/labels";
import { TechnicalDisclosure, TechnicalRow } from "@/components/technical-disclosure";
import {
  api,
  type RemediationArtifactView,
  type RemediationAction,
  type RemediationCaseDetail,
} from "../../api";
import { ErrorText } from "./shared";

// ------------------------------------------------------------ M7b patches

export function PatchPanel({
  orgId,
  c,
  a,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  a: RemediationAction;
  onChanged: () => void;
}) {
  const [docId, setDocId] = useState("");
  const documents = useQuery({
    queryKey: ["documents", orgId],
    queryFn: () => api.listDocuments(orgId),
  });
  const proposals = useQuery({
    queryKey: ["patch-proposals", orgId, c.id, a.id],
    queryFn: () => api.listPatchProposals(orgId, c.id, a.id),
  });
  const artifacts = useQuery({
    queryKey: ["artifacts", orgId, c.id, a.id],
    queryFn: () => api.listArtifacts(orgId, c.id, a.id),
  });
  const parsed = (documents.data ?? []).filter((d) => d.status === "parsed");
  const selected = parsed.find((d) => d.id === docId);
  // Route by the CURRENT version format (server-derived); fall back to the
  // filename extension until a version pointer exists.
  const format = selected ? (selected.filename.toLowerCase().split(".").pop() ?? "") : "";
  const isTextual = format === "txt" || format === "md";

  const propose = useMutation({
    mutationFn: () => api.createPatchProposal(orgId, c.id, a.id, docId),
    onSuccess: () => {
      proposals.refetch();
      onChanged();
    },
  });
  const proposeArtifact = useMutation({
    mutationFn: () => api.createArtifact(orgId, c.id, a.id, docId),
    onSuccess: () => {
      artifacts.refetch();
      onChanged();
    },
  });

  return (
    <div className="space-y-3 rounded-lg border border-primary/20 bg-accent/50 p-3">
      <p className="text-xs font-semibold text-primary">Correctif documentaire</p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={docId}
          onChange={(e) => setDocId(e.target.value)}
          aria-label="Document cible"
          className="min-h-9 rounded-md border border-input px-2 py-1 text-xs"
        >
          <option value="">Choisir le document cible…</option>
          {parsed.map((d) => (
            <option key={d.id} value={d.id}>
              {d.filename}
            </option>
          ))}
        </select>
        {selected &&
          (isTextual ? (
            <button
              onClick={() => propose.mutate()}
              disabled={propose.isPending}
              className="min-h-9 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Proposer un correctif
            </button>
          ) : (
            <button
              onClick={() => proposeArtifact.mutate()}
              disabled={proposeArtifact.isPending}
              className="min-h-9 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Proposer une rédaction (PDF/DOCX)
            </button>
          ))}
      </div>
      {selected && !isTextual && (
        <p className="text-xs text-muted-foreground">
          PDF/DOCX : l'agent produit une proposition Markdown ; le document original reste
          inchangé et seul un téléversement humain crée une nouvelle version.
        </p>
      )}
      <ErrorText error={propose.error || proposeArtifact.error} />

      {(proposals.data ?? []).map((p) => (
        <PatchProposalCard key={p.id} orgId={orgId} c={c} proposalId={p.id} onChanged={onChanged} />
      ))}
      {(artifacts.data ?? [])
        .filter((art) => art.status === "VERIFIED")
        .map((art) => (
          <ArtifactCard key={art.id} orgId={orgId} c={c} art={art} onChanged={onChanged} />
        ))}
    </div>
  );
}

function ArtifactCard({
  orgId,
  c,
  art,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  art: RemediationArtifactView;
  onChanged: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  // A candidate this artifact spawned that never finished activating (a crash /
  // Qdrant outage / assessment conflict). Detecting it on LOAD makes recovery
  // reachable after a refresh, not only within the failed upload's session.
  const versions = useQuery({
    queryKey: ["document-versions", art.document_id],
    queryFn: () => api.listDocumentVersions(art.document_id),
  });
  const refresh = () => {
    versions.refetch();
    onChanged();
  };
  // The superseding upload replaces the version the artifact was drafted
  // against and records the artifact as lineage (action -> artifact -> file ->
  // version).
  const supersede = useMutation({
    mutationFn: (f: File) => api.supersedeUpload(orgId, f, art.document_version_id, art.id),
    onSuccess: () => {
      setFile(null);
      refresh();
    },
  });
  // Recovery re-drives a stranded activation WITHOUT re-uploading the file —
  // it operates on the candidate version the first upload already created.
  const recover = useMutation({
    mutationFn: (versionId: string) => api.recoverUpload(art.document_id, versionId),
    onSuccess: refresh,
  });
  const stranded = (versions.data ?? []).find(
    (v) =>
      v.source_artifact_id === art.id &&
      v.supersedes_version_id === art.document_version_id &&
      (v.state === "PENDING_INDEX" || v.state === "INDEX_FAILED"),
  );
  const result = recover.data ?? supersede.data;
  const outcome = result?.outcome ?? "";
  const inSessionRecoverable =
    outcome === "pending" || outcome === "index_failed" || outcome === "assessment_conflict";
  // recover id: the in-session mutation result, else the stranded version on load
  const recoverVersionId = inSessionRecoverable ? result?.version_id : stranded?.id;
  return (
    <div className="space-y-2 rounded-lg border bg-card p-3 text-xs">
      <p className="font-medium text-foreground/90">
        Proposition de rédaction ({art.canonical_format.toUpperCase()})
      </p>
      <a href={api.artifactDownloadUrl(orgId, c.id, art.id)} className="text-primary underline">
        Télécharger le brouillon Markdown
      </a>
      <p className="text-muted-foreground/80">
        Brouillon IA — préparez le fichier {art.canonical_format.toUpperCase()} révisé, puis
        téléversez-le ici pour créer la nouvelle version (le document original reste inchangé).
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="file"
          aria-label="Fichier révisé à téléverser"
          accept={art.canonical_format === "pdf" ? ".pdf" : ".docx"}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-xs"
        />
        <button
          onClick={() => file && supersede.mutate(file)}
          disabled={!file || supersede.isPending}
          className="min-h-9 rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          Téléverser la version révisée
        </button>
      </div>
      {(outcome === "activated" || outcome === "already_active") && (
        <p className="text-success">
          Nouvelle version créée et activée à partir de votre fichier révisé.
        </p>
      )}
      {outcome === "index_failed" && (
        <p className="text-warning-foreground dark:text-warning">
          Indexation vectorielle échouée ; la version est conservée et peut être reprise.
        </p>
      )}
      {outcome === "pending" && (
        <p className="text-warning-foreground dark:text-warning">
          Activation en attente ; vous pouvez la reprendre.
        </p>
      )}
      {outcome === "assessment_conflict" && (
        <p className="text-warning-foreground dark:text-warning">
          Une évaluation est en cours ; réessayez la reprise une fois qu'elle est terminée.
        </p>
      )}
      {outcome.startsWith("abandoned:") && (
        <p className="text-destructive">
          Activation abandonnée — proposition périmée : retéléversez la version révisée.
        </p>
      )}
      {/* stranded on load (survives a refresh), when no in-session outcome shows it */}
      {!inSessionRecoverable && stranded && (
        <p className="text-warning-foreground dark:text-warning">
          Une activation de version (
          {stranded.state === "INDEX_FAILED" ? "échec d'indexation" : "en attente"}) est restée
          inachevée ; vous pouvez la reprendre.
        </p>
      )}
      {recoverVersionId && (
        <button
          onClick={() => recover.mutate(recoverVersionId)}
          disabled={recover.isPending}
          className="min-h-9 rounded-md border border-primary/40 px-3 py-1 text-primary hover:bg-accent disabled:opacity-50"
        >
          Reprendre l'activation
        </button>
      )}
      <ErrorText error={supersede.error || recover.error} />
    </div>
  );
}

const PATCH_DECISION_LABELS: Record<string, string> = {
  approve: "approuvé",
  edit: "approuvé après relecture",
  reject: "rejeté",
};

function PatchProposalCard({
  orgId,
  c,
  proposalId,
  onChanged,
}: {
  orgId: string;
  c: RemediationCaseDetail;
  proposalId: string;
  onChanged: () => void;
}) {
  const proposal = useQuery({
    queryKey: ["patch-proposal", orgId, c.id, proposalId],
    queryFn: () => api.getPatchProposal(orgId, c.id, proposalId),
  });
  const versions = useQuery({
    queryKey: ["document-versions", proposal.data?.document_id],
    queryFn: () => api.listDocumentVersions(proposal.data!.document_id),
    enabled: !!proposal.data,
  });
  const [editing, setEditing] = useState(false);
  const [finalText, setFinalText] = useState("");
  const refresh = () => {
    proposal.refetch();
    versions.refetch();
    onChanged();
  };
  const decide = useMutation({
    mutationFn: (body: { decision: "approve" | "edit" | "reject"; final_text_fr?: string }) =>
      api.decidePatch(orgId, c.id, proposalId, body),
    onSuccess: () => {
      setEditing(false);
      refresh();
    },
  });
  const recover = useMutation({
    mutationFn: () => api.recoverPatch(orgId, c.id, proposalId),
    onSuccess: refresh,
  });

  const p = proposal.data;
  if (!p) return null;

  if (p.status === "ABSTAINED") {
    return (
      <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-xs text-warning-foreground dark:text-warning">
        <p className="font-medium">
          Correctif en abstention — {abstainReasonDisplay(p.abstain_reason).label}
        </p>
        <p className="mt-1">
          L'agent n'a pas pu ancrer un correctif fiable ; rédigez la modification manuellement.
        </p>
        <TechnicalDisclosure summary="Détails techniques" className="mt-2">
          <TechnicalRow label="Motif brut" value={p.abstain_reason ?? "—"} />
          {p.verifier_errors?.map((e, i) => <TechnicalRow key={i} label="Vérification" value={e} />)}
        </TechnicalDisclosure>
      </div>
    );
  }
  if (p.status === "DRAFTING") {
    return <p className="text-xs text-muted-foreground">Rédaction du correctif en cours…</p>;
  }

  const resultVersion = (versions.data ?? []).find((v) => v.id === p.decision?.result_version_id);
  const stranded =
    resultVersion &&
    (resultVersion.state === "INDEX_FAILED" || resultVersion.state === "PENDING_INDEX");

  return (
    <div className="space-y-2 rounded-lg border bg-card p-3 text-xs">
      <p className="font-medium text-foreground/90">
        Diff proposé ({p.operation === "replace" ? "remplacement" : "insertion"})
      </p>
      {/* Server-derived source slice at the resolved anchor — never the model quote */}
      <div className="rounded bg-muted/50 p-3 font-mono text-[13px] leading-relaxed">
        <span className="text-muted-foreground/80">{p.context_before}</span>
        <mark className="bg-warning/30 text-foreground">{p.anchor_slice}</mark>
        {p.operation === "insert_after" && (
          <ins className="bg-success/15 text-success no-underline dark:text-success">
            {"\n\n"}
            {editing ? finalText || p.new_text_fr : p.new_text_fr}
          </ins>
        )}
        {p.operation === "replace" && (
          <span className="text-muted-foreground/80 line-through">{/* replaced */}</span>
        )}
        <span className="text-muted-foreground/80">{p.context_after}</span>
      </div>
      {p.operation === "replace" && (
        <div className="rounded bg-success/10 p-3 font-mono text-[13px] text-success">
          → {editing ? finalText || p.new_text_fr : p.new_text_fr}
        </div>
      )}
      <p className="text-muted-foreground">Justification IA : {p.rationale}</p>

      {p.decision ? (
        <div className="rounded bg-muted/50 p-2">
          <p className="font-medium text-muted-foreground">
            Décision : {PATCH_DECISION_LABELS[p.decision.decision] ?? p.decision.decision}
            {resultVersion &&
              ` → version ${resultVersion.version_number} (${versionStateDisplay(resultVersion.state).label})`}
          </p>
          {resultVersion?.state === "ACTIVE" &&
            (resultVersion.canonical_format === "txt" ||
              resultVersion.canonical_format === "md") && (
              <a
                href={api.versionDownloadUrl(p.document_id, resultVersion.id)}
                className="text-primary underline"
              >
                Télécharger la nouvelle version
              </a>
            )}
          {stranded && (
            <button
              onClick={() => recover.mutate()}
              disabled={recover.isPending}
              className="mt-1 min-h-9 rounded-md border border-primary/40 px-2 py-0.5 text-primary hover:bg-accent disabled:opacity-50"
            >
              Reprendre l'activation
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {editing && (
            <textarea
              value={finalText}
              onChange={(e) => setFinalText(e.target.value)}
              rows={4}
              placeholder="Texte final (votre rédaction sera appliquée telle quelle)"
              className="w-full rounded-md border border-input px-2 py-1 text-sm"
            />
          )}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => decide.mutate({ decision: "approve" })}
              disabled={decide.isPending}
              className="min-h-9 rounded-md bg-success px-3 py-1 font-medium text-success-foreground hover:bg-success/90 disabled:opacity-50"
            >
              Approuver le correctif
            </button>
            {editing ? (
              <button
                onClick={() => decide.mutate({ decision: "edit", final_text_fr: finalText })}
                disabled={decide.isPending || !finalText.trim()}
                className="min-h-9 rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                Appliquer ma rédaction
              </button>
            ) : (
              <button
                onClick={() => {
                  setFinalText(p.new_text_fr ?? "");
                  setEditing(true);
                }}
                className="min-h-9 rounded-md border border-input px-3 py-1 hover:bg-muted/50"
              >
                Modifier le texte
              </button>
            )}
            <button
              onClick={() => decide.mutate({ decision: "reject" })}
              disabled={decide.isPending}
              className="min-h-9 rounded-md border border-input px-3 py-1 hover:bg-muted/50"
            >
              Rejeter le correctif
            </button>
          </div>
        </div>
      )}
      <ErrorText error={decide.error || recover.error} />
    </div>
  );
}
