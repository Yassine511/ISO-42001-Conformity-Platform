import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  ConformityDomain,
  ConformityReport,
  ReportingScopeMeta,
  TrustPanel as TrustPanelData,
  Verdict,
} from "../api";

const VERDICT_LABELS: Record<Verdict, string> = {
  compliant: "conforme",
  partial: "partiel",
  non_compliant: "non conforme",
  missing: "absent",
};

const VERDICT_COLORS: Record<Verdict, string> = {
  compliant: "#059669", // emerald-600
  partial: "#d97706", // amber-600
  non_compliant: "#dc2626", // red-600
  missing: "#64748b", // slate-500
};

export default function DashboardPage() {
  const { orgId } = useParams<{ orgId: string }>();
  // "" = organisation (derniers verdicts confirmés)
  const [assessmentId, setAssessmentId] = useState("");
  const [includePreliminary, setIncludePreliminary] = useState(false);

  const params = {
    assessmentId: assessmentId || undefined,
    includePreliminary: includePreliminary || undefined,
  };
  const assessments = useQuery({
    queryKey: ["assessments", orgId],
    queryFn: () => api.listAssessments(orgId!),
  });
  const conformity = useQuery({
    queryKey: ["conformity", orgId, assessmentId, includePreliminary],
    queryFn: () => api.getConformity(orgId!, params),
  });
  const trust = useQuery({
    queryKey: ["trust", orgId, assessmentId, includePreliminary],
    queryFn: () => api.getTrustPanel(orgId!, params),
  });

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <Link to={`/organizations/${orgId}`} className="text-sm text-indigo-600 hover:underline">
          ← Organisation
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-slate-600" htmlFor="scope-select">
            Périmètre
          </label>
          <select
            id="scope-select"
            value={assessmentId}
            onChange={(e) => setAssessmentId(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm"
          >
            <option value="">Organisation — derniers verdicts confirmés</option>
            {(assessments.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                Évaluation {a.id.slice(0, 8)} · {a.status === "COMPLETED" ? "terminée" : `${a.status} (préliminaire)`}
              </option>
            ))}
          </select>
          {!assessmentId && (
            <label className="flex items-center gap-1.5 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={includePreliminary}
                onChange={(e) => setIncludePreliminary(e.target.checked)}
              />
              inclure les évaluations préliminaires
            </label>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Tableau de bord de conformité</h1>
        <a
          href={api.reportDownloadUrl(orgId!, params)}
          className="rounded-lg border border-indigo-300 px-3 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-50"
          download
        >
          ⬇ Exporter le rapport PDF
        </a>
      </div>

      {conformity.data && <ScopeBanners scope={conformity.data.scope} />}

      {conformity.isLoading && <p className="text-sm text-slate-500">Chargement…</p>}
      {conformity.error && (
        <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {(conformity.error as Error).message}
        </p>
      )}
      {conformity.data && <ConformitySection data={conformity.data} />}
      {trust.data && <TrustSection data={trust.data} />}
    </div>
  );
}

function ScopeBanners({ scope }: { scope: ReportingScopeMeta }) {
  return (
    <div className="space-y-2">
      {scope.is_preliminary && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
          Résultat <strong>préliminaire</strong> — il inclut des évaluations non terminées et ne
          constitue pas un état officiel.
        </p>
      )}
      {!scope.scope_complete && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
          Périmètre incomplet : {scope.legacy_manifest_missing_ids.length} évaluation(s) sans
          manifeste d'exigences (antérieures) sont hors du dénominateur — leurs constats ne sont
          pas comptés. Ce rapport ne peut pas être qualifié d'officiel.
        </p>
      )}
    </div>
  );
}

// ------------------------------------------------------------- conformity

function ConformitySection({ data }: { data: ConformityReport }) {
  return (
    <section className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <Donut pct={data.global_pct} />
          <p className="mt-3 text-center text-sm text-slate-600">
            Conformité calculée sur <strong>{data.scored}</strong> exigence(s) confirmée(s) /{" "}
            <strong>{data.total_in_scope}</strong> du périmètre
            {data.coverage_pct !== null && <> ({data.coverage_pct}% couvert)</>}
          </p>
          <p className="mt-1 text-center text-xs text-slate-500">
            Couverture de la norme : {data.total_in_scope}/{data.scope.kb_total_requirements}{" "}
            exigences · politique {data.scope.scoring_policy_version}
          </p>
          <VerdictLegend counts={data.verdict_counts} />
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Conformité par domaine</h2>
          <div className="space-y-2">
            {data.domains.map((d) => (
              <DomainBar key={d.domain} d={d} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function Donut({ pct }: { pct: number | null }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const filled = pct === null ? 0 : (pct / 100) * c;
  return (
    <svg viewBox="0 0 140 140" className="mx-auto block h-40 w-40" role="img"
      aria-label={pct === null ? "Conformité globale : non évaluée" : `Conformité globale : ${pct}%`}>
      <circle cx="70" cy="70" r={r} fill="none" stroke="#e2e8f0" strokeWidth="14" />
      <circle
        cx="70"
        cy="70"
        r={r}
        fill="none"
        stroke="#4f46e5"
        strokeWidth="14"
        strokeLinecap="round"
        strokeDasharray={`${filled} ${c - filled}`}
        transform="rotate(-90 70 70)"
      />
      <text x="70" y="76" textAnchor="middle" className="fill-slate-900" fontSize="24" fontWeight="600">
        {pct === null ? "—" : `${pct}%`}
      </text>
    </svg>
  );
}

function VerdictLegend({ counts }: { counts: Record<Verdict, number> }) {
  return (
    <ul className="mt-3 space-y-1 text-xs text-slate-600">
      {(Object.keys(VERDICT_LABELS) as Verdict[]).map((v) => (
        <li key={v} className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: VERDICT_COLORS[v] }} />
          {VERDICT_LABELS[v]} : {counts[v] ?? 0}
        </li>
      ))}
    </ul>
  );
}

function DomainBar({ d }: { d: ConformityDomain }) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium text-slate-700">
          {d.domain} · {d.domain_title_fr}
        </span>
        <span className="text-slate-500">
          {d.pct === null ? "non évalué" : `${d.pct}%`} — {d.scored}/{d.total_in_scope} confirmées
        </span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100">
        {d.pct !== null && (
          <div className="h-full rounded-full bg-indigo-500" style={{ width: `${d.pct}%` }} />
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------- trust panel

function TrustSection({ data }: { data: TrustPanelData }) {
  const { gate, review, chat, m6_benchmark } = data;
  return (
    <section className="space-y-4">
      <h2 className="text-sm font-semibold text-slate-700">
        Panneau de confiance — « peut-on croire l'IA ? »
      </h2>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
          <h3 className="font-medium text-slate-700">Barrière de vérification</h3>
          <dl className="mt-2 space-y-1 text-slate-600">
            <Row k="Brouillons IA" v={gate.drafts_total} />
            <Row k="→ citation non vérifiable" v={gate.drafts_with_unsupported_citation} />
            <Row
              k="Taux de brouillons non étayés"
              v={gate.unsupported_draft_rate_pct === null ? "—" : `${gate.unsupported_draft_rate_pct}%`}
            />
            <Row k="Schéma invalide" v={gate.drafts_schema_invalid} />
            <Row k="Constats en abstention" v={gate.findings_abstained} />
            {gate.legacy_unclassified > 0 && (
              <Row k="Anciennes tentatives non classées" v={gate.legacy_unclassified} />
            )}
          </dl>
          <p className="mt-2 rounded bg-emerald-50 px-2 py-1 text-xs text-emerald-700">
            Citations non étayées affichées : {gate.unsupported_citations_displayed} —{" "}
            <strong>invariant structurel</strong> (vérifié, pas mesuré)
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
          <h3 className="font-medium text-slate-700">Revue humaine</h3>
          <dl className="mt-2 space-y-1 text-slate-600">
            <Row k="Décisions de revue" v={review.review_events} />
            <Row k="Approbations" v={review.approve_events} />
            <Row
              k="Taux d'intervention (modifier + remplacer)"
              v={review.intervention_rate_pct === null ? "—" : `${review.intervention_rate_pct}%`}
            />
            <Row
              k="Taux de remplacement du verdict"
              v={review.verdict_override_rate_pct === null ? "—" : `${review.verdict_override_rate_pct}%`}
            />
          </dl>
          <p className="mt-2 text-xs text-slate-500">
            Calculé sur l'historique immuable des décisions (re-revues comprises).
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
          <h3 className="font-medium text-slate-700">Copilote (chat)</h3>
          <dl className="mt-2 space-y-1 text-slate-600">
            <Row k="Messages" v={chat.messages} />
            <Row k="Réponses citées" v={chat.answered} />
            <Row k="Abstentions" v={chat.abstained} />
            <Row k="Citations retirées par la vérification" v={chat.stripped_citation_count} />
          </dl>
          <p className="mt-2 text-xs text-slate-500">
            Portée : organisation entière (les messages ne sont pas liés à une évaluation).
          </p>
        </div>
      </div>
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm">
        <h3 className="font-medium text-slate-700">{String(m6_benchmark.label)}</h3>
        <p className="mt-1 text-xs text-slate-500">
          Référence statique issue de l'évaluation gelée — jamais des données courantes de
          l'organisation. Artefact : {String(m6_benchmark.source_artifact)} (sha256{" "}
          {String(m6_benchmark.source_artifact_sha256).slice(0, 12)}…)
        </p>
        <dl className="mt-2 grid gap-x-6 gap-y-1 text-slate-600 sm:grid-cols-2">
          <Row k="Justesse des verdicts (pipeline)" v={String(m6_benchmark.pipeline_verdict_accuracy)} />
          <Row k="Brouillons non étayés bloqués" v={String(m6_benchmark.gate_blocked_unsupported_first_drafts)} />
          <Row k="Localisation des citations (chat)" v={String(m6_benchmark.chat_citation_location_validity)} />
          <Row k="Fidélité des réponses (chat)" v={String(m6_benchmark.chat_faithfulness)} />
        </dl>
      </div>
    </section>
  );
}

function Row({ k, v }: { k: string; v: string | number }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt>{k}</dt>
      <dd className="font-medium text-slate-800">{v}</dd>
    </div>
  );
}
