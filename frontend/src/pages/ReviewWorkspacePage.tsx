import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  isInfraAbstain,
  type FindingDetail,
  type FindingSummary,
  type ReviewAction,
  type Verdict,
} from "../api";
import AbstainReasonLabel from "../components/AbstainReasonLabel";
import HighlightedText from "../components/HighlightedText";
import { AssessmentStatusBadge, ReviewStatusBadge } from "../components/StatusBadge";
import VerdictBadge from "../components/VerdictBadge";

type Filter = "all" | "pending" | "abstained" | "confirmed";

const FILTER_LABELS: Record<Filter, string> = {
  all: "Tous",
  pending: "À examiner",
  abstained: "Abstentions",
  confirmed: "Confirmés",
};

const ACTION_LABELS: Record<ReviewAction, string> = {
  approve: "Approuvé",
  edit: "Modifié",
  override: "Remplacé",
};

const VERDICT_OPTIONS: { value: Verdict; label: string }[] = [
  { value: "compliant", label: "Conforme" },
  { value: "partial", label: "Partiel" },
  { value: "non_compliant", label: "Non conforme" },
  { value: "missing", label: "Preuve insuffisante" },
];

export default function ReviewWorkspacePage() {
  const { orgId, assessmentId } = useParams<{ orgId: string; assessmentId: string }>();
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["assessment", orgId, assessmentId],
    queryFn: () => api.getAssessment(orgId!, assessmentId!),
    refetchInterval: (query) =>
      query.state.data?.status === "RUNNING" ? 2000 : false,
  });

  const findings = detail.data?.findings ?? [];
  const filtered = useMemo(
    () =>
      findings.filter((f) => {
        if (filter === "pending") return f.review_status === "PENDING";
        if (filter === "confirmed") return f.review_status === "CONFIRMED";
        if (filter === "abstained") return f.status === "ABSTAINED";
        return true;
      }),
    [findings, filter],
  );
  // resolve the selection against the FILTERED list: a finding excluded by
  // the active filter must never stay displayed in the detail panel
  const selected =
    (selectedId && filtered.find((f) => f.id === selectedId)) || filtered[0] || null;

  if (detail.isError) {
    return <p className="text-sm text-red-600">{(detail.error as Error).message}</p>;
  }
  if (!detail.data) {
    return <p className="text-sm text-slate-500">Chargement…</p>;
  }
  const a = detail.data;

  return (
    <div className="space-y-6">
      <Link to={`/organizations/${orgId}`} className="text-sm text-indigo-600 hover:underline">
        ← Organisation
      </Link>

      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Espace de revue</h1>
        <AssessmentStatusBadge status={a.status} />
        <span aria-live="polite" className="text-sm text-slate-500">
          {a.reviewed_count} / {a.total} confirmés
        </span>
        {a.status === "RUNNING" && (
          <span className="text-sm text-slate-500">
            évaluation en cours — les constats apparaissent au fil de l'eau
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Filtres">
        {(Object.keys(FILTER_LABELS) as Filter[]).map((key) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            aria-pressed={filter === key}
            className={`rounded-full px-3 py-1 text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 ${
              filter === key
                ? "bg-indigo-600 text-white"
                : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            {FILTER_LABELS[key]}
          </button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <FindingList
          findings={filtered}
          selectedId={selected?.id ?? null}
          onSelect={setSelectedId}
        />
        {selected ? (
          <FindingPanel key={selected.id} orgId={orgId!} assessmentId={assessmentId!} findingId={selected.id} />
        ) : (
          <p className="text-sm text-slate-500">Aucun constat pour ce filtre.</p>
        )}
      </div>
    </div>
  );
}

function FindingList({
  findings,
  selectedId,
  onSelect,
}: {
  findings: FindingSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <ul className="max-h-[70vh] space-y-1 overflow-y-auto pr-1" aria-label="Constats">
      {findings.map((f) => {
        const infra = isInfraAbstain(f.abstain_reason);
        return (
          <li key={f.id}>
            <button
              onClick={() => onSelect(f.id)}
              aria-current={f.id === selectedId}
              className={`w-full rounded-lg border p-3 text-left text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 ${
                f.id === selectedId
                  ? "border-indigo-400 bg-indigo-50"
                  : "border-slate-200 bg-white hover:bg-slate-50"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{f.requirement_id}</span>
                <ReviewStatusBadge status={f.review_status} />
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                {f.status === "VERIFIED" ? (
                  <VerdictBadge verdict={f.verdict} />
                ) : infra ? (
                  <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-600">
                    Échec technique — relancez l'évaluation
                  </span>
                ) : (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                    Nécessite votre jugement
                  </span>
                )}
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function FindingPanel({
  orgId,
  assessmentId,
  findingId,
}: {
  orgId: string;
  assessmentId: string;
  findingId: string;
}) {
  const finding = useQuery({
    queryKey: ["finding", orgId, assessmentId, findingId],
    queryFn: () => api.getFinding(orgId, assessmentId, findingId),
  });

  if (finding.isError) {
    return <p className="text-sm text-red-600">{(finding.error as Error).message}</p>;
  }
  if (!finding.data) return <p className="text-sm text-slate-500">Chargement…</p>;
  const f = finding.data;

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-2">
        <RequirementPane finding={f} />
        <EvidencePane finding={f} />
      </div>
      <ReviewSection orgId={orgId} assessmentId={assessmentId} finding={f} />
    </div>
  );
}

function RequirementPane({ finding: f }: { finding: FindingDetail }) {
  const infra = isInfraAbstain(f.abstain_reason);
  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Exigence ISO
      </h2>
      <div>
        <div className="flex items-center gap-2">
          <span className="text-lg font-semibold">{f.requirement_id}</span>
          {f.domain && <span className="text-xs text-slate-500">{f.domain}</span>}
        </div>
        {f.requirement_fr ? (
          <p className="mt-2 text-sm text-slate-700">{f.requirement_fr}</p>
        ) : (
          <p className="mt-2 text-sm text-amber-700">
            Texte de l'exigence indisponible : constat antérieur aux instantanés et version de
            corpus différente ({f.corpus_mismatch ? "corpus modifié depuis" : ""}).
          </p>
        )}
      </div>

      <div
        className={`rounded-lg border p-4 ${
          f.status === "VERIFIED"
            ? "border-slate-200 bg-slate-50"
            : infra
              ? "border-slate-200 bg-slate-100"
              : "border-amber-200 bg-amber-50"
        }`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {f.status === "VERIFIED"
              ? "Brouillon IA — citation localisée, pertinence à confirmer"
              : "Brouillon IA — abstention"}
          </span>
          {f.status === "VERIFIED" ? (
            <VerdictBadge verdict={f.verdict} />
          ) : (
            <AbstainReasonLabel reason={f.abstain_reason} />
          )}
          {f.confidence !== null && (
            <span className="text-xs text-slate-500">confiance {f.confidence.toFixed(2)}</span>
          )}
        </div>
        {f.rationale && <p className="mt-2 text-sm text-slate-700">{f.rationale}</p>}
        {f.status === "ABSTAINED" && !infra && (
          <p className="mt-2 text-xs text-amber-800">
            Le système n'a pas pu produire de citation vérifiable — ce constat nécessite votre
            jugement (action « remplacer »).
          </p>
        )}
      </div>

      <ProvenanceDisclosure finding={f} />
    </section>
  );
}

function ProvenanceDisclosure({ finding: f }: { finding: FindingDetail }) {
  return (
    <details className="rounded-lg border border-slate-200 p-3 text-sm">
      <summary className="cursor-pointer font-medium text-slate-600">
        Provenance ({f.attempts} tentative{f.attempts > 1 ? "s" : ""}
        {f.final_model ? ` · ${f.final_model}` : ""})
      </summary>
      <div className="mt-3 space-y-3 text-xs text-slate-600">
        {f.policy_quote && (
          <p>
            Citation déclarée par le modèle (audit — le texte affiché comme preuve est
            l'extrait source) : « {f.policy_quote} »
          </p>
        )}
        {f.attempt_history.map((att) => (
          <div key={att.attempt_number} className="rounded border border-slate-100 p-2">
            <p className="font-medium">
              Tentative {att.attempt_number} ({att.prompt_version}) —{" "}
              {att.parsed_ok ? "analysée" : "non analysable"}
            </p>
            {att.llm_calls.map((c) => (
              <p key={c.call_number}>
                appel {c.call_number} : {c.provider}/{c.requested_model} → {c.status}
                {c.http_status ? ` (${c.http_status})` : ""}
                {c.error ? ` — ${c.error}` : ""}
              </p>
            ))}
            {att.verifier_errors?.map((e, i) => (
              <p key={i} className="text-amber-700">
                vérif ✗ {e}
              </p>
            ))}
          </div>
        ))}
        {(f.audit_log ?? []).length > 0 && (
          <p>
            Trace : {(f.audit_log ?? []).map((e) => `${e.node}/${e.event}`).join(" → ")}
          </p>
        )}
      </div>
    </details>
  );
}

function EvidencePane({ finding: f }: { finding: FindingDetail }) {
  const matched = f.retrieved.find((r) => r.result_id === f.matched_chunk_id) ?? null;
  const others = f.retrieved.filter((r) => r.result_id !== f.matched_chunk_id);
  const localStart =
    matched && f.match_start !== null ? f.match_start - (matched.char_start ?? 0) : null;
  const localEnd =
    matched && f.match_end !== null ? f.match_end - (matched.char_start ?? 0) : null;

  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Preuves (politiques)
      </h2>

      {matched && (
        <div
          className={`rounded-lg border p-4 ${
            f.source_quote_kind === "candidate"
              ? "border-amber-200 bg-amber-50/50"
              : "border-emerald-200 bg-emerald-50/50"
          }`}
        >
          <p className="text-xs font-medium text-slate-500">
            {matched.filename}
            {matched.page_number ? `, p.${matched.page_number}` : ""} —{" "}
            {f.source_quote_kind === "candidate"
              ? "passage candidat (correspondance approximative)"
              : "passage cité"}
          </p>
          <p className="mt-2 text-sm leading-relaxed text-slate-800">
            <HighlightedText
              text={matched.text}
              start={f.source_quote_error ? null : localStart}
              end={f.source_quote_error ? null : localEnd}
            />
          </p>
          {f.source_quote && f.source_quote_kind === "verified" && (
            <p className="mt-2 text-xs text-slate-500">
              Extrait source (autoritatif) : « {f.source_quote} »
            </p>
          )}
          {f.source_quote && f.source_quote_kind === "candidate" && (
            <p className="mt-2 text-xs font-medium text-amber-700">
              Localisation approximative retenue pour votre revue — ce n'est pas une citation
              vérifiée.
            </p>
          )}
          {f.source_quote_error && (
            <p className="mt-2 text-xs font-medium text-amber-700">
              Provenance non affichable : {f.source_quote_error}
            </p>
          )}
        </div>
      )}
      {!matched && (
        <p className="text-sm text-slate-500">
          Aucun passage cité — extraits récupérés ci-dessous.
        </p>
      )}

      {others.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm font-medium text-slate-600">
            Autres extraits récupérés ({others.length})
          </summary>
          <ul className="mt-3 space-y-3">
            {others.map((r) => (
              <li key={r.result_id} className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-medium text-slate-500">
                  {r.source_type === "policy"
                    ? `${r.filename ?? "document"}${r.page_number ? `, p.${r.page_number}` : ""}`
                    : `Exigence ISO ${r.requirement_id}`}
                </p>
                <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{r.text}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function OpenRemediationCase({ orgId, findingId }: { orgId: string; findingId: string }) {
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: () => api.createCase(orgId, { finding_id: findingId }),
    onSuccess: (c) => navigate(`/organizations/${orgId}/remediation/${c.id}`),
  });
  return (
    <div className="mt-3">
      <button
        onClick={() => create.mutate()}
        disabled={create.isPending}
        className="rounded-lg border border-indigo-300 px-3 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
      >
        {create.isPending ? "Ouverture…" : "Ouvrir un cas de remédiation"}
      </button>
      {create.isError && (
        <p className="mt-1 text-xs text-red-600">{(create.error as Error).message}</p>
      )}
    </div>
  );
}

function ReviewSection({
  orgId,
  assessmentId,
  finding: f,
}: {
  orgId: string;
  assessmentId: string;
  finding: FindingDetail;
}) {
  const queryClient = useQueryClient();
  const [action, setAction] = useState<ReviewAction | null>(null);
  const [humanVerdict, setHumanVerdict] = useState<Verdict>("partial");
  const [rationale, setRationale] = useState("");
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState("");

  const review = useMutation({
    mutationFn: () =>
      api.reviewFinding(orgId, assessmentId, f.id, {
        action: action!,
        human_verdict: action === "override" ? humanVerdict : undefined,
        human_rationale: rationale || undefined,
        review_note: note || undefined,
        reviewer_label: reviewer || undefined,
      }),
    onSuccess: () => {
      setAction(null);
      setRationale("");
      setNote("");
      queryClient.invalidateQueries({ queryKey: ["finding", orgId, assessmentId, f.id] });
      queryClient.invalidateQueries({ queryKey: ["assessment", orgId, assessmentId] });
    },
  });

  const abstained = f.status === "ABSTAINED";
  const needsRationale = action === "edit" || action === "override";
  const submitDisabled = review.isPending || (needsRationale && !rationale.trim());

  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Décision humaine
        </h2>
        <ReviewStatusBadge status={f.review_status} />
      </div>

      {f.review_status === "CONFIRMED" && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{ACTION_LABELS[f.review_action!]}</span>
            <VerdictBadge verdict={f.human_verdict} />
            <span className="text-xs text-slate-500">
              le {f.reviewed_at ? new Date(f.reviewed_at).toLocaleString("fr-FR") : ""}
            </span>
          </div>
          {f.human_rationale && <p className="mt-2 text-slate-700">{f.human_rationale}</p>}
          {f.review_note && (
            <p className="mt-1 text-xs text-slate-500">Note : {f.review_note}</p>
          )}
          <p className="mt-2 text-xs text-slate-500">
            Le brouillon IA reste affiché tel quel ci-dessus — votre décision est enregistrée à
            côté, jamais à sa place. Vous pouvez réviser votre décision : l'historique conserve
            chaque version.
          </p>
          {["partial", "non_compliant", "missing"].includes(f.human_verdict ?? "") && (
            <OpenRemediationCase orgId={orgId} findingId={f.id} />
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2" role="group" aria-label="Actions de revue">
        <button
          onClick={() => setAction("approve")}
          disabled={abstained}
          aria-pressed={action === "approve"}
          title={abstained ? "Un constat en abstention nécessite votre verdict (« remplacer »)" : undefined}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-500 ${
            action === "approve"
              ? "bg-emerald-600 text-white"
              : "border border-emerald-300 text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-40"
          }`}
        >
          Approuver
        </button>
        <button
          onClick={() => setAction("edit")}
          disabled={abstained}
          aria-pressed={action === "edit"}
          title={abstained ? "Un constat en abstention nécessite votre verdict (« remplacer »)" : undefined}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 ${
            action === "edit"
              ? "bg-indigo-600 text-white"
              : "border border-indigo-300 text-indigo-700 hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-40"
          }`}
        >
          Modifier
        </button>
        <button
          onClick={() => setAction("override")}
          aria-pressed={action === "override"}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-500 ${
            action === "override"
              ? "bg-amber-600 text-white"
              : "border border-amber-300 text-amber-700 hover:bg-amber-50"
          }`}
        >
          Remplacer
        </button>
        {abstained && (
          <span className="self-center text-xs text-amber-700">
            Abstention : seul « Remplacer » est possible — le verdict vous appartient.
          </span>
        )}
      </div>

      {action && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            review.mutate();
          }}
        >
          {action === "override" && (
            <label className="block text-sm">
              <span className="font-medium">Votre verdict</span>
              <select
                value={humanVerdict}
                onChange={(e) => setHumanVerdict(e.target.value as Verdict)}
                className="mt-1 block rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
              >
                {VERDICT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="block text-sm">
            <span className="font-medium">
              Justification{needsRationale ? " (requise)" : " (facultative)"}
            </span>
            <textarea
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              rows={3}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="font-medium">Note (facultative)</span>
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium">Votre nom (facultatif, non vérifié)</span>
              <input
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
              />
            </label>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitDisabled}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500"
            >
              {review.isPending ? "Enregistrement…" : "Enregistrer la décision"}
            </button>
            {review.isError && (
              <p className="text-sm text-red-600">{(review.error as Error).message}</p>
            )}
          </div>
        </form>
      )}

      {f.reviews.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer font-medium text-slate-600">
            Historique des décisions ({f.reviews.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {f.reviews.map((r) => (
              <li key={r.sequence} className="rounded-lg border border-slate-200 p-3 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">#{r.sequence}</span>
                  <span>{ACTION_LABELS[r.action]}</span>
                  <VerdictBadge verdict={r.human_verdict} />
                  <span className="text-slate-500">
                    {new Date(r.created_at).toLocaleString("fr-FR")}
                  </span>
                  {r.reviewer_label && (
                    <span className="text-slate-500">par {r.reviewer_label} (non vérifié)</span>
                  )}
                </div>
                {r.human_rationale && <p className="mt-1 text-slate-600">{r.human_rationale}</p>}
                {r.review_note && <p className="mt-1 text-slate-500">Note : {r.review_note}</p>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
