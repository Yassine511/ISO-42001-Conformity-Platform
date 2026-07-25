"""M8 Node ⑤ — deterministic scoring over human-confirmed findings.

No AI anywhere in this module. Every calculator consumes ONE materialized
`ReportingScope` (plain detached data, no lazy ORM relationships): the API
layer opens the session with REPEATABLE READ / READ ONLY on PostgreSQL before
the first query, so one report reflects one database snapshot — a review
landing mid-assembly can never produce a mixed-state report.

Scoring input contract: every finding with review_status='CONFIRMED' is
scored using human_verdict — regardless of whether its AI status was VERIFIED
or ABSTAINED (override is the designed resolution path for AI abstentions).
Coverage gaps are requirements with no finding or only PENDING findings.

Scope contract:
- assessment mode: universe = the frozen requirement_ids manifest.
- organization mode: universe = union of manifests of COMPLETED assessments
  with non-NULL manifests; effective findings = latest CONFIRMED per
  requirement across that same eligible set (max reviewed_at, id tie-break).
  RUNNING/FAILED assessments are excluded and disclosed; legacy NULL-manifest
  assessments are disclosed and flip scope_complete=False (their findings are
  outside the denominator, never silently dropped).
- include_preliminary=True folds RUNNING/FAILED manifests in and marks the
  ENTIRE result preliminary.
- is_official = not is_preliminary and scope_complete.

Weights resolve through the immutable policy registry
(services/scoring_policy.py), never the live KB — see that module's
reproducibility contract. The live KB contributes only domain TITLES
(M8-authored headers, safe for holdout ids; requirement TEXT comes only from
finding snapshots).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session, load_only

from app.models import (
    Assessment,
    AssessmentAttempt,
    ChatMessage,
    Conversation,
    Finding,
    FindingReview,
    RemediationAction,
    RemediationCase,
    RemediationCaseFinding,
    SoaControl,
)
from app.services.retrieval import load_kb
from app.services.scoring_policy import (
    GAP_FACTOR,
    resolve_policy,
    resolve_weight,
    severity_band,
)

CONFORMITY_CREDIT = {"compliant": 1.0, "partial": 0.5, "non_compliant": 0.0, "missing": 0.0}
GAP_VERDICTS = ("partial", "non_compliant", "missing")

# citation-support failures (a quote the source does not verify); the broader
# code histogram is exposed separately
UNSUPPORTED_CITATION_CODES = {"citation_not_found", "citation_fuzzy"}
VERIFIER_ABSTAIN_REASONS = {"verification_failed", "fuzzy_citation"}

SEVERITY_TO_PRIORITY = {"high": "haute", "medium": "normale", "low": "basse"}

# Frozen M6 holdout benchmark (static reference card, never live telemetry).
# The constants are checksum-bound to the committed evaluation artifact:
# tests/test_reporting.py re-hashes eval/m6/rapport_m6.md and fails if either
# the numbers' source file or this pin drifts.
M6_BENCHMARK = {
    "label": "Référence M6 (corpus v1.2.0, holdout n=14)",
    "source_artifact": "eval/m6/rapport_m6.md",
    "source_artifact_sha256": "4e8cac2b6d349fcaa5cfd0bf1f6381e692c0cf55f5c4cf4662998eefb57e04d5",
    "pipeline_verdict_accuracy": "9/14",
    "gate_blocked_unsupported_first_drafts": "3/14",
    "unsupported_citations_displayed": 0,
    "chat_citation_location_validity": "24/24",
    "chat_pair_support_precision": "23/32",
    "chat_faithfulness": "7/10",
}

# Deterministic French risk-statement templates per domain (spec §6: templated
# per Annex A domain; clauses 4-10 covered so clause gaps also register).
# {req} is the requirement id; the register row carries the snapshot text.
RISK_STATEMENT_FR = {
    "4": "Risque de système de management de l'IA mal cadré (contexte, parties intéressées ou périmètre non maîtrisés) : exigence {req} en écart.",
    "5": "Risque de gouvernance de l'IA sans portage par la direction (engagement, politique ou responsabilités insuffisants) : exigence {req} en écart.",
    "6": "Risque de risques et impacts de l'IA non identifiés ou non traités (planification défaillante) : exigence {req} en écart.",
    "7": "Risque de moyens insuffisants pour le système de management de l'IA (ressources, compétences, sensibilisation ou documentation) : exigence {req} en écart.",
    "8": "Risque de dérive opérationnelle des systèmes d'IA (maîtrise d'exploitation, réévaluations ou traitement des risques non réalisés) : exigence {req} en écart.",
    "9": "Risque de défaillances invisibles du système de management de l'IA (surveillance, audit ou revue de direction lacunaires) : exigence {req} en écart.",
    "10": "Risque de non-conformités récurrentes faute d'amélioration continue ou d'actions correctives : exigence {req} en écart.",
    "A.2": "Risque de développement ou d'usage de l'IA sans cadre de politique interne : exigence {req} en écart.",
    "A.3": "Risque de responsabilités IA diluées ou de préoccupations non remontées : exigence {req} en écart.",
    "A.4": "Risque de ressources d'IA non inventoriées (données, outils, calcul, personnes) rendant le système non auditable : exigence {req} en écart.",
    "A.5": "Risque d'impacts sur les individus, les groupes ou la société non évalués avant ou pendant l'exploitation : exigence {req} en écart.",
    "A.6": "Risque de systèmes d'IA conçus, validés ou exploités sans processus responsable de cycle de vie : exigence {req} en écart.",
    "A.7": "Risque de données d'entraînement ou d'exploitation non tracées, de qualité non vérifiée ou de provenance inconnue : exigence {req} en écart.",
    "A.8": "Risque de parties intéressées non informées (limites du système, incidents, signalements) : exigence {req} en écart.",
    "A.9": "Risque d'utilisation de l'IA hors du cadre responsable prévu (supervision humaine, usage prévu) : exigence {req} en écart.",
    "A.10": "Risque de chaîne de responsabilité rompue avec les tiers, fournisseurs ou clients du système d'IA : exigence {req} en écart.",
}


def domain_of(requirement_id: str, snapshot_domain: str | None) -> str:
    if snapshot_domain:
        return snapshot_domain
    if requirement_id.startswith("A."):
        return "A." + requirement_id.split(".")[1]
    return requirement_id.split(".")[0]


@dataclass(frozen=True)
class EffectiveFinding:
    """Detached snapshot of one scoreable (or pending) finding."""

    finding_id: str
    assessment_id: str
    requirement_id: str
    domain: str
    requirement_fr: str | None
    ai_status: str
    abstain_reason: str | None
    review_status: str
    human_verdict: str | None
    review_action: str | None
    reviewed_at: datetime | None


@dataclass(frozen=True)
class Treatment:
    """Remediation linkage of one gap finding (M7 authority preserved)."""

    active_case_id: str | None
    active_case_status: str | None
    approved_action_count: int  # active plan's actions only
    closed_case_ids: tuple[str, ...]


@dataclass
class ReportingScope:
    mode: str  # "organization" | "assessment"
    organization_id: str
    assessment_id: str | None
    assessment_status: str | None
    requirement_universe: list[str]
    scoring_policy_version: str
    policy: dict
    corpus_versions: list[str]
    generated_at: str
    included_assessment_ids: list[str]
    excluded_preliminary_assessment_ids: list[str]
    legacy_manifest_missing_ids: list[str]
    scope_complete: bool
    is_preliminary: bool
    is_official: bool
    official_blockers: list[str]
    include_preliminary: bool
    kb_total_requirements: int  # informational «couverture de la norme : N/65»
    domain_titles: dict[str, str]
    # requirement_id -> the finding that scores it (latest CONFIRMED), or the
    # newest PENDING finding when nothing is confirmed (coverage status only)
    effective: dict[str, EffectiveFinding] = field(default_factory=dict)
    treatments: dict[str, Treatment] = field(default_factory=dict)  # by finding_id
    # frozen manifest of each included assessment — the SAME membership guard
    # applies to every consumer (effective findings AND trust telemetry)
    included_manifests: dict[str, set] = field(default_factory=dict)
    # SoA current-state projection rows (control_id -> plain dict) — SoA and
    # register applicability flags read THIS, never the live table
    soa_projections: dict[str, dict] = field(default_factory=dict)
    # trust-panel raw material, fully detached at build time
    trust_data: dict = field(default_factory=dict)

    def meta(self) -> dict:
        """Scope metadata block, embedded verbatim in every reporting payload.
        requirement_universe makes the exact denominator independently
        auditable; review_cutoff states the review-generation boundary (the
        snapshot instant — decisions after it are not in this report)."""
        return {
            "mode": self.mode,
            "assessment_id": self.assessment_id,
            "assessment_status": self.assessment_status,
            "scoring_policy_version": self.scoring_policy_version,
            "corpus_versions": self.corpus_versions,
            "generated_at": self.generated_at,
            "review_cutoff": self.generated_at,
            "requirement_universe": self.requirement_universe,
            "included_assessment_ids": self.included_assessment_ids,
            "excluded_preliminary_assessment_ids": self.excluded_preliminary_assessment_ids,
            "legacy_manifest_missing_ids": self.legacy_manifest_missing_ids,
            "scope_complete": self.scope_complete,
            "is_preliminary": self.is_preliminary,
            "is_official": self.is_official,
            "official_blockers": self.official_blockers,
            "kb_total_requirements": self.kb_total_requirements,
        }


def build_reporting_scope(
    db: Session,
    org_id: str,
    assessment_id: str | None = None,
    *,
    include_preliminary: bool = False,
    scoring_policy_version: str | None = None,
) -> ReportingScope:
    """Materialize everything the calculators need, inside the caller's
    (isolated) transaction. Raises KeyError for an unknown policy version and
    LookupError for an unknown assessment (the API maps both)."""
    policy_version, policy = resolve_policy(scoring_policy_version)
    kb = load_kb()
    domain_titles = {
        e["domain"]: e["domain_title_fr"] for e in kb["by_id"].values()
    }

    assessments = list(
        db.scalars(select(Assessment).where(Assessment.organization_id == org_id))
    )
    official_blockers: list[str] = []

    if assessment_id is not None:
        target = next((a for a in assessments if a.id == assessment_id), None)
        if target is None:
            raise LookupError("assessment not found in this organization")
        mode = "assessment"
        assessment_status = target.status
        included = [target] if target.requirement_ids else []
        legacy_missing = [] if target.requirement_ids else [target.id]
        excluded_preliminary: list[str] = []
        universe = list(target.requirement_ids or [])
        is_preliminary = include_preliminary or target.status != "COMPLETED"
        if target.status != "COMPLETED":
            official_blockers.append("assessment_not_completed")
    else:
        mode = "organization"
        assessment_status = None
        eligible = [a for a in assessments if a.status == "COMPLETED" and a.requirement_ids]
        excluded_preliminary = sorted(
            a.id for a in assessments if a.status != "COMPLETED"
        )
        legacy_missing = sorted(
            a.id for a in assessments if a.status == "COMPLETED" and not a.requirement_ids
        )
        included = list(eligible)
        if include_preliminary:
            included += [a for a in assessments if a.status != "COMPLETED" and a.requirement_ids]
        universe_set: set[str] = set()
        for a in included:
            universe_set.update(a.requirement_ids or [])
        universe = sorted(universe_set)
        is_preliminary = include_preliminary

    scope_complete = not legacy_missing
    if legacy_missing:
        official_blockers.append("legacy_manifest_missing")
    if include_preliminary:
        official_blockers.append("preliminary_included")
    is_official = not is_preliminary and scope_complete

    included_ids = [a.id for a in included]
    corpus_versions = sorted({a.corpus_version for a in included})

    # ---- effective findings: latest CONFIRMED per requirement across the
    # included assessments; a PENDING-only requirement keeps its newest
    # PENDING finding for coverage status. STRICT manifest membership: a
    # finding whose requirement is not in ITS OWN assessment's frozen
    # manifest is excluded (no DB constraint enforces membership; an
    # out-of-manifest confirmed finding would otherwise inflate the global
    # numerator past 100% — reproduced before this guard existed).
    manifests = {a.id: set(a.requirement_ids or []) for a in included}
    effective: dict[str, EffectiveFinding] = {}
    if included_ids:
        # Only the columns EffectiveFinding carries (+ created_at, the
        # pending tie-break). The full Finding row also holds `retrieved` and
        # `audit_log` — JSON blobs of the whole retrieved-evidence payload
        # (models/_pipeline.py) that nothing here reads. Every reporting
        # endpoint builds a scope, and one dashboard render fires three of
        # them (conformity + trust + risk register), so hydrating those blobs
        # meant deserializing megabytes per page load for nothing. Same
        # discipline as api/assessments.py and remediation/service.py.
        rows = db.scalars(
            select(Finding)
            .options(
                load_only(
                    Finding.id,
                    Finding.assessment_id,
                    Finding.requirement_id,
                    Finding.domain,
                    Finding.requirement_fr,
                    Finding.status,
                    Finding.abstain_reason,
                    Finding.review_status,
                    Finding.human_verdict,
                    Finding.review_action,
                    Finding.reviewed_at,
                    Finding.created_at,
                )
            )
            .where(Finding.assessment_id.in_(included_ids))
        )
        best_pending: dict[str, tuple] = {}
        best_confirmed: dict[str, tuple] = {}
        for f in rows:
            if f.requirement_id not in manifests.get(f.assessment_id, ()):
                continue
            ef = EffectiveFinding(
                finding_id=f.id,
                assessment_id=f.assessment_id,
                requirement_id=f.requirement_id,
                domain=domain_of(f.requirement_id, f.domain),
                requirement_fr=f.requirement_fr,
                ai_status=f.status,
                abstain_reason=f.abstain_reason,
                review_status=f.review_status,
                human_verdict=f.human_verdict,
                review_action=f.review_action,
                reviewed_at=f.reviewed_at,
            )
            if f.review_status == "CONFIRMED" and f.human_verdict:
                key = (f.reviewed_at, f.id)
                prev = best_confirmed.get(f.requirement_id)
                if prev is None or key > prev[0]:
                    best_confirmed[f.requirement_id] = (key, ef)
            else:
                # NEWEST pending, chosen explicitly: the driving query has no
                # ORDER BY, so setdefault() would keep whichever row Postgres
                # happened to return first and the coverage row could change
                # between identical requests. Same (timestamp, id) max as
                # best_confirmed above.
                key = (f.created_at, f.id)
                prev = best_pending.get(f.requirement_id)
                if prev is None or key > prev[0]:
                    best_pending[f.requirement_id] = (key, ef)
        for rid, (_, ef) in best_pending.items():
            if rid not in best_confirmed:
                effective[rid] = ef
        for rid, (_, ef) in best_confirmed.items():
            effective[rid] = ef

    scope = ReportingScope(
        mode=mode,
        organization_id=org_id,
        assessment_id=assessment_id,
        assessment_status=assessment_status,
        requirement_universe=universe,
        scoring_policy_version=policy_version,
        policy=policy,
        corpus_versions=corpus_versions,
        generated_at=datetime.now(timezone.utc).isoformat(),
        included_assessment_ids=included_ids,
        excluded_preliminary_assessment_ids=excluded_preliminary,
        legacy_manifest_missing_ids=legacy_missing,
        scope_complete=scope_complete,
        is_preliminary=is_preliminary,
        is_official=is_official,
        official_blockers=official_blockers,
        include_preliminary=include_preliminary,
        kb_total_requirements=len(kb["by_id"]),
        domain_titles=domain_titles,
        effective=effective,
        included_manifests=manifests,
    )
    scope.treatments = _materialize_treatments(db, scope)
    scope.soa_projections = _materialize_soa_projections(db, scope)
    scope.trust_data = _materialize_trust(db, scope)
    return scope


def _materialize_soa_projections(db: Session, scope: ReportingScope) -> dict[str, dict]:
    """SoA current-state rows as plain dicts — read by soa_table() and by the
    register's applicability flag, never re-queried by calculators."""
    return {
        row.control_id: {
            "applicable": row.applicable,
            "justification_fr": row.justification_fr,
            "editor_label": row.editor_label,
            "decision_count": row.decision_count,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in db.scalars(
            select(SoaControl).where(SoaControl.organization_id == scope.organization_id)
        )
    }


def _materialize_treatments(db: Session, scope: ReportingScope) -> dict[str, Treatment]:
    """Remediation linkage for the scope's gap findings — M7 authority rules:
    the single non-CLOSED case is the active one; approved actions counted on
    the case's active_plan_id only (superseded plans' actions are inert)."""
    gap_finding_ids = [
        ef.finding_id
        for ef in scope.effective.values()
        if ef.review_status == "CONFIRMED" and ef.human_verdict in GAP_VERDICTS
    ]
    if not gap_finding_ids:
        return {}
    links = list(
        db.execute(
            select(RemediationCaseFinding.finding_id, RemediationCase)
            .join(RemediationCase, RemediationCaseFinding.case_id == RemediationCase.id)
            .where(RemediationCaseFinding.finding_id.in_(gap_finding_ids))
        )
    )
    active_plan_ids = [
        case.active_plan_id for _, case in links if case.status != "CLOSED" and case.active_plan_id
    ]
    approved_by_plan: dict[str, int] = {}
    if active_plan_ids:
        # two columns, not whole action rows: the AI draft columns
        # (ai_description/ai_rationale/ai_impacted_requirement_ids) are never
        # read here. RemediationCase above stays a full entity load on
        # purpose — those rows are scalar/Text only, no JSON payload.
        for plan_id, lifecycle in db.execute(
            select(RemediationAction.plan_id, RemediationAction.lifecycle).where(
                RemediationAction.plan_id.in_(active_plan_ids)
            )
        ):
            if lifecycle in ("APPROVED", "IN_PROGRESS", "DONE"):
                approved_by_plan[plan_id] = approved_by_plan.get(plan_id, 0) + 1

    treatments: dict[str, Treatment] = {}
    by_finding: dict[str, list[RemediationCase]] = {}
    for finding_id, case in links:
        by_finding.setdefault(finding_id, []).append(case)
    for finding_id, cases in by_finding.items():
        active = [c for c in cases if c.status != "CLOSED"]  # service-enforced <= 1
        closed = sorted(c.id for c in cases if c.status == "CLOSED")
        current = active[0] if active else None
        treatments[finding_id] = Treatment(
            active_case_id=current.id if current else None,
            active_case_status=current.status if current else None,
            approved_action_count=(
                approved_by_plan.get(current.active_plan_id, 0)
                if current and current.active_plan_id
                else 0
            ),
            closed_case_ids=tuple(closed),
        )
    return treatments


# ---------------------------------------------------------------- conformity


def conformity_summary(scope: ReportingScope) -> dict:
    """Global + per-domain conformity. Denominator = scored (confirmed)
    requirements only; coverage always reported alongside."""
    per_domain: dict[str, dict] = {}
    for rid in scope.requirement_universe:
        dom = domain_of(rid, scope.effective.get(rid).domain if rid in scope.effective else None)
        d = per_domain.setdefault(
            dom,
            {
                "domain": dom,
                "domain_title_fr": scope.domain_titles.get(dom, dom),
                "total_in_scope": 0,
                "scored": 0,
                "credit": 0.0,
                "verdict_counts": {v: 0 for v in CONFORMITY_CREDIT},
                "pending_review": 0,
                "not_assessed": 0,
            },
        )
        d["total_in_scope"] += 1
        ef = scope.effective.get(rid)
        if ef is None:
            d["not_assessed"] += 1
        elif ef.review_status == "CONFIRMED" and ef.human_verdict:
            d["scored"] += 1
            d["credit"] += CONFORMITY_CREDIT[ef.human_verdict]
            d["verdict_counts"][ef.human_verdict] += 1
        else:
            d["pending_review"] += 1

    domains = []
    for dom in sorted(per_domain, key=_domain_sort_key):
        d = per_domain[dom]
        d["pct"] = round(100.0 * d["credit"] / d["scored"], 1) if d["scored"] else None
        del d["credit"]
        domains.append(d)

    scored = sum(d["scored"] for d in domains)
    total = len(scope.requirement_universe)
    credit = sum(
        CONFORMITY_CREDIT[ef.human_verdict]
        for ef in scope.effective.values()
        if ef.review_status == "CONFIRMED" and ef.human_verdict
    )
    verdict_counts = {v: 0 for v in CONFORMITY_CREDIT}
    for ef in scope.effective.values():
        if ef.review_status == "CONFIRMED" and ef.human_verdict:
            verdict_counts[ef.human_verdict] += 1
    return {
        "scope": scope.meta(),
        "global_pct": round(100.0 * credit / scored, 1) if scored else None,
        "scored": scored,
        "total_in_scope": total,
        "coverage_pct": round(100.0 * scored / total, 1) if total else None,
        "verdict_counts": verdict_counts,
        "domains": domains,
    }


def _domain_sort_key(dom: str) -> tuple:
    if dom.startswith("A."):
        return (1, int(dom.split(".")[1]))
    return (0, int(dom))


# ---------------------------------------------------------------- risk register


def severity_for(policy: dict, requirement_id: str, human_verdict: str) -> dict:
    """Deterministic severity of one gap verdict under one policy."""
    gap_factor = GAP_FACTOR[human_verdict]
    weight, weight_source = resolve_weight(policy, requirement_id)
    if weight is None:
        return {
            "gap_factor": gap_factor,
            "weight": None,
            "weight_source": weight_source,
            "severity_score": None,
            "severity": None,  # «non évaluée» in the UI
        }
    score, band = severity_band(gap_factor, weight)
    return {
        "gap_factor": gap_factor,
        "weight": weight,
        "weight_source": weight_source,
        "severity_score": score,
        "severity": band,
    }


def risk_register(scope: ReportingScope) -> dict:
    """One row per latest CONFIRMED gap finding in scope — pure code over
    human-confirmed findings (spec §6), templated French statements."""
    rows = []
    for rid in scope.requirement_universe:
        ef = scope.effective.get(rid)
        if ef is None or ef.review_status != "CONFIRMED":
            continue
        if ef.human_verdict not in GAP_VERDICTS:
            continue
        sev = severity_for(scope.policy, rid, ef.human_verdict)
        treatment = scope.treatments.get(ef.finding_id)
        # SoA applicability ANNOTATES the row (never filters it): a scored
        # risk on a control the human declared non-applicable is disclosed
        soa_row = scope.soa_projections.get(rid)
        applicable = soa_row["applicable"] if soa_row else True
        template = RISK_STATEMENT_FR.get(ef.domain) or RISK_STATEMENT_FR.get(
            domain_of(rid, None), "Risque de non-conformité ISO 42001 : exigence {req} en écart."
        )
        rows.append(
            {
                "requirement_id": rid,
                "domain": ef.domain,
                "domain_title_fr": scope.domain_titles.get(ef.domain, ef.domain),
                "requirement_fr": ef.requirement_fr,  # finding snapshot only
                "human_verdict": ef.human_verdict,
                **sev,
                "applicable": applicable,
                "applicability_justification_fr": (
                    soa_row["justification_fr"] if soa_row and not applicable else None
                ),
                "risk_statement_fr": template.format(req=rid),
                "finding_id": ef.finding_id,
                "assessment_id": ef.assessment_id,
                "reviewed_at": ef.reviewed_at.isoformat() if ef.reviewed_at else None,
                "treatment": (
                    {
                        "active_case_id": treatment.active_case_id,
                        "active_case_status": treatment.active_case_status,
                        "approved_action_count": treatment.approved_action_count,
                        "closed_case_ids": list(treatment.closed_case_ids),
                    }
                    if treatment
                    else None
                ),
            }
        )
    order = {"high": 0, "medium": 1, "low": 2, None: 3}
    rows.sort(key=lambda r: (order[r["severity"]], -(r["severity_score"] or 0), r["requirement_id"]))
    return {
        "scope": scope.meta(),
        "rows": rows,
        "counts": {
            "high": sum(1 for r in rows if r["severity"] == "high"),
            "medium": sum(1 for r in rows if r["severity"] == "medium"),
            "low": sum(1 for r in rows if r["severity"] == "low"),
            "unscored": sum(1 for r in rows if r["severity"] is None),
        },
    }


# ---------------------------------------------------------------- suggested priority


def suggested_priority_for_action(
    action_requirement_ids: list[str],
    case_link_snapshots: list[tuple[str, str]],  # (requirement_id, human_verdict) at link time
    scoring_policy_version: str | None = None,
) -> dict:
    """Severity-derived priority suggestion for one remediation action.

    Derived from the IMMUTABLE case-link snapshots (finding_human_verdict at
    link time), never the finding's later mutable review projection, and from
    the action's own effective scope — so two actions of one case can differ.
    Read-only: the human priority decision stays mandatory.
    """
    version, policy = resolve_policy(scoring_policy_version)
    snapshot_by_req = {}
    for req_id, verdict in case_link_snapshots:
        if verdict in GAP_VERDICTS:
            # keep the worst verdict if a requirement appears in several links
            prev = snapshot_by_req.get(req_id)
            if prev is None or GAP_FACTOR[verdict] > GAP_FACTOR[prev]:
                snapshot_by_req[req_id] = verdict
    matching = [rid for rid in action_requirement_ids if rid in snapshot_by_req]
    if not matching:
        return {
            "suggested_priority": None,
            "suggested_priority_reason": "no_linked_gap_in_action_scope",
            "suggested_priority_policy_version": version,
        }
    best: tuple[int, str] | None = None
    for rid in matching:
        sev = severity_for(policy, rid, snapshot_by_req[rid])
        if sev["severity"] is not None:
            key = (sev["severity_score"], sev["severity"])
            if best is None or key > best:
                best = key
    if best is None:
        return {
            "suggested_priority": None,
            "suggested_priority_reason": "all_matching_weights_unscored",
            "suggested_priority_policy_version": version,
        }
    return {
        "suggested_priority": SEVERITY_TO_PRIORITY[best[1]],
        "suggested_priority_reason": None,
        "suggested_priority_policy_version": version,
    }


# ---------------------------------------------------------------- trust panel


def _manifest_predicate(manifests: dict[str, set], assessment_col, requirement_col):
    """SQL form of the manifest membership guard: a row counts only when its
    requirement is in the frozen manifest of its OWN assessment.

    Built ONCE and reused for attempts and findings so the two can never
    diverge. An empty manifest set collapses to false for that assessment —
    correct, and `false()` for no assessments at all (never an empty or_(),
    which SQLAlchemy renders as an always-true empty conjunction)."""
    clauses = [
        and_(assessment_col == assessment_id, requirement_col.in_(requirement_ids))
        for assessment_id, requirement_ids in manifests.items()
        if requirement_ids
    ]
    return or_(*clauses) if clauses else false()


def _materialize_trust(db: Session, scope: ReportingScope) -> dict:
    """Trust-panel metrics computed AT BUILD TIME into plain data — the
    calculator (trust_panel) then works from the detached scope alone, like
    every other section. The manifest guard applies here exactly as it does
    to the effective findings: attempts/findings on a requirement outside
    their OWN assessment's frozen manifest are out of scope for telemetry
    too (they would otherwise inflate the gate counts and review rates).

    Counting is done by the DATABASE (COUNT/GROUP BY under the manifest
    predicate), not by streaming rows into Python: these tables are the full
    append-only history of the organization and grow without bound, so the old
    row-by-row scans made the trust panel slower every day it was used. Two
    narrow single-column scans remain, and only because both inspect the
    CONTENTS of a JSON array — a per-code histogram and a sum of array lengths
    need dialect-specific unnesting (`json_each` on SQLite,
    `json_array_elements_text` on PostgreSQL), which would make the test suite
    and production exercise different code. Both are documented at their site.

    Everything here runs inside the caller's REPEATABLE READ / READ ONLY
    snapshot, so splitting one scan into several aggregate queries cannot mix
    database states.
    """
    included = scope.included_assessment_ids
    manifests = scope.included_manifests
    in_manifest = _manifest_predicate(
        manifests, AssessmentAttempt.assessment_id, AssessmentAttempt.requirement_id
    )

    outcome_counts = {"parsed": 0, "schema_invalid": 0, "provider_failure": 0, "legacy_unclassified": 0}
    code_counts: dict[str, int] = {}
    drafts_with_unsupported = 0
    classified_with_codes = 0
    if included:
        for attempt_outcome, n in db.execute(
            select(AssessmentAttempt.attempt_outcome, func.count())
            .where(AssessmentAttempt.assessment_id.in_(included), in_manifest)
            .group_by(AssessmentAttempt.attempt_outcome)
        ):
            outcome_counts[attempt_outcome] = outcome_counts.get(attempt_outcome, 0) + n

        # JSON-array contents: one column, bounded by the scope's assessments x
        # their manifests, not by the whole attempt history.
        #
        # The `codes is None` guard is NOT redundant with a SQL IS NOT NULL:
        # SQLAlchemy's JSON type persists Python None as JSON `null`, which is
        # not SQL NULL, so such a row passes any SQL null test and still
        # deserializes to None. Filtering in Python is the only reading that
        # matches how the rows were written (legacy row, or the verify node
        # never completed the attempt).
        for (codes,) in db.execute(
            select(AssessmentAttempt.verifier_error_codes).where(
                AssessmentAttempt.assessment_id.in_(included), in_manifest
            )
        ):
            if codes is None:
                continue
            classified_with_codes += 1
            for code in codes:
                code_counts[code] = code_counts.get(code, 0) + 1
            if UNSUPPORTED_CITATION_CODES & set(codes):
                drafts_with_unsupported += 1

    abstain_counts: dict[str, int] = {}
    findings_abstained_by_verifier = 0
    status_counts = {"VERIFIED": 0, "ABSTAINED": 0}
    review_events = 0
    intervention_events = 0
    override_events = 0
    if included:
        finding_in_manifest = _manifest_predicate(
            manifests, Finding.assessment_id, Finding.requirement_id
        )
        for status, reason, n in db.execute(
            select(Finding.status, Finding.abstain_reason, func.count())
            .where(Finding.assessment_id.in_(included), finding_in_manifest)
            .group_by(Finding.status, Finding.abstain_reason)
        ):
            status_counts[status] = status_counts.get(status, 0) + n
            if reason:
                abstain_counts[reason] = abstain_counts.get(reason, 0) + n
                if reason in VERIFIER_ABSTAIN_REASONS:
                    findings_abstained_by_verifier += n

        # Immutable review EVENTS (append-only history), never the mutable
        # projection: re-reviews each count as one event. Joined to Finding so
        # the manifest guard applies in SQL — the previous form materialized
        # every in-scope finding id and passed them back as one IN (...) list.
        for action, n in db.execute(
            select(FindingReview.action, func.count())
            .join(Finding, FindingReview.finding_id == Finding.id)
            .where(Finding.assessment_id.in_(included), finding_in_manifest)
            .group_by(FindingReview.action)
        ):
            review_events += n
            if action in ("edit", "override"):
                intervention_events += n
            if action == "override":
                override_events += n

    drafts_total = sum(outcome_counts.values())
    # Chat rows are owned by conversations (no assessment/org column) — join.
    # Status tallies are a GROUP BY; the stripped-citation total needs the
    # LENGTH of a JSON array per row, so it keeps a one-column scan for the
    # same dialect reason given above.
    chat_counts: dict[str, int] = {}
    for status, n in db.execute(
        select(ChatMessage.status, func.count())
        .join(Conversation, ChatMessage.conversation_id == Conversation.id)
        .where(Conversation.organization_id == scope.organization_id)
        .group_by(ChatMessage.status)
    ):
        chat_counts[status] = n
    stripped_count = sum(
        len(stripped or [])
        for (stripped,) in db.execute(
            select(ChatMessage.stripped_citations)
            .join(Conversation, ChatMessage.conversation_id == Conversation.id)
            .where(Conversation.organization_id == scope.organization_id)
        )
    )
    chat_messages = sum(chat_counts.values())

    return {
        "gate": {
            "drafts_total": drafts_total,
            "drafts_parsed": outcome_counts["parsed"],
            "drafts_schema_invalid": outcome_counts["schema_invalid"],
            "drafts_provider_failure": outcome_counts["provider_failure"],
            "legacy_unclassified": outcome_counts["legacy_unclassified"],
            "drafts_with_unsupported_citation": drafts_with_unsupported,
            "unsupported_draft_rate_pct": (
                round(100.0 * drafts_with_unsupported / classified_with_codes, 1)
                if classified_with_codes
                else None
            ),
            "verifier_error_code_counts": dict(sorted(code_counts.items())),
            "findings_verified": status_counts.get("VERIFIED", 0),
            "findings_abstained": status_counts.get("ABSTAINED", 0),
            "findings_abstained_by_verifier": findings_abstained_by_verifier,
            "abstentions_by_reason": dict(sorted(abstain_counts.items())),
            # structural invariant (post-gate rendering is server-slice only),
            # checked empirically in M6 — a CHECKED property, not a measurement
            "unsupported_citations_displayed": 0,
        },
        "review": {
            "review_events": review_events,
            "approve_events": review_events - intervention_events,
            "edit_or_override_events": intervention_events,
            "override_events": override_events,
            "intervention_rate_pct": (
                round(100.0 * intervention_events / review_events, 1) if review_events else None
            ),
            "verdict_override_rate_pct": (
                round(100.0 * override_events / review_events, 1) if review_events else None
            ),
        },
        "chat": {
            "metric_scope": "organization",  # chat has no assessment binding
            "messages": chat_messages,
            "answered": chat_counts.get("ANSWERED", 0),
            "abstained": chat_counts.get("ABSTAINED", 0),
            "stripped_citation_count": stripped_count,
        },
    }


def trust_panel(scope: ReportingScope) -> dict:
    """Defensible operational metrics over typed telemetry, served from the
    detached scope (materialized at build time). Pipeline and review metrics
    follow the scope; chat metrics have no assessment binding and are ALWAYS
    organization-wide (metric_scope makes that explicit). Never labelled a
    "hallucination rate" — the zero displayed-unsupported-citations line is a
    structural invariant, checked rather than measured."""
    return {
        "scope": scope.meta(),
        **scope.trust_data,
        "m6_benchmark": M6_BENCHMARK,
    }
