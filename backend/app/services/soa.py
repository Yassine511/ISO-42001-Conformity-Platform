"""M8 Statement of Applicability — per Annex A control (spec §14 / roadmap
line 539: «per Annex A control: applicable Y/N + justification + status»).

The 38 rows are GENERATED from the KB's Annex A metadata (ids + domain
titles — M8-authored headers, safe for holdout ids); requirement TEXT comes
only from finding snapshots (holdout posture). Defaults: every control is
applicable until a human records otherwise. Decisions are append-only
(soa_decisions) with a current-state projection (soa_controls); the next
sequence is allocated under the ORGANIZATION row lock so concurrent PUTs
serialize (PG-verified; SQLite ignores FOR UPDATE).

Applicability ANNOTATES: a non-applicable control keeps its recorded finding
status and stays in conformity/risk outputs (flagged, never filtered) — the
SoA documents the human's applicability position, it does not rewrite scores.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SoaControl, SoaDecision
from app.services.retrieval import load_kb
from app.services.run_guard import lock_organization
from app.services.scoring import GAP_VERDICTS, ReportingScope
from app.services.scoring_policy import resolve_weight


class SoaUnknownControlError(LookupError):
    pass


class SoaOrganizationNotFoundError(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def annex_a_controls() -> list[dict]:
    """All Annex A control entries from the KB, in domain/id order."""
    kb = load_kb()
    entries = [e for e in kb["by_id"].values() if e["id"].startswith("A.")]
    entries.sort(key=lambda e: [int(p) for p in e["id"][2:].split(".")])
    return entries


def soa_table(db: Session, scope: ReportingScope) -> dict:
    """The SoA over the given reporting scope. The applicability columns are
    ORGANIZATION-CURRENT state (they have no assessment binding) even when
    the finding-status column is assessment-scoped — labelled in the payload."""
    projections = {
        row.control_id: row
        for row in db.scalars(
            select(SoaControl).where(SoaControl.organization_id == scope.organization_id)
        )
    }
    controls = []
    domain_summaries: dict[str, dict] = {}
    for entry in annex_a_controls():
        cid = entry["id"]
        proj = projections.get(cid)
        ef = scope.effective.get(cid)
        confirmed = ef is not None and ef.review_status == "CONFIRMED"
        if confirmed and ef.human_verdict in GAP_VERDICTS:
            status = "ecart"
        elif confirmed:
            status = "conforme"
        else:
            status = "non_evalue"
        weight, weight_source = resolve_weight(scope.policy, cid)
        controls.append(
            {
                "control_id": cid,
                "domain": entry["domain"],
                "domain_title_fr": entry["domain_title_fr"],
                # holdout posture: text only from the finding snapshot
                "requirement_fr": ef.requirement_fr if ef is not None else None,
                "applicable": proj.applicable if proj else True,
                "justification_fr": proj.justification_fr if proj else None,
                "editor_label": proj.editor_label if proj else None,
                "decision_count": proj.decision_count if proj else 0,
                "updated_at": proj.updated_at.isoformat() if proj else None,
                "is_default": proj is None,
                "status": status,
                "human_verdict": ef.human_verdict if confirmed else None,
                "in_scope": cid in scope.requirement_universe,
                "finding_id": ef.finding_id if ef is not None else None,
                "assessment_id": ef.assessment_id if ef is not None else None,
                "weight": weight,
                "weight_source": weight_source,
            }
        )
        d = domain_summaries.setdefault(
            entry["domain"],
            {
                "domain": entry["domain"],
                "domain_title_fr": entry["domain_title_fr"],
                "controls": 0,
                "applicable": 0,
                "conforme": 0,
                "ecart": 0,
                "non_evalue": 0,
            },
        )
        d["controls"] += 1
        d["applicable"] += 1 if (proj.applicable if proj else True) else 0
        d[status] += 1

    return {
        "scope": scope.meta(),
        # applicability is org-current even in assessment-scoped reports
        "applicability_scope": "organization_current",
        "controls": controls,
        "domains": [domain_summaries[k] for k in sorted(domain_summaries, key=lambda d: int(d[2:]))],
    }


def record_decision(
    db: Session,
    org_id: str,
    control_id: str,
    *,
    applicable: bool,
    justification_fr: str,
    editor_label: str | None = None,
) -> SoaControl:
    """Append one immutable decision + update the projection. Commits.
    The organization row lock serializes concurrent PUTs so sequence
    allocation and the projection can never interleave."""
    if lock_organization(db, org_id) is None:
        db.rollback()
        raise SoaOrganizationNotFoundError(org_id)
    if control_id not in {e["id"] for e in annex_a_controls()}:
        db.rollback()
        raise SoaUnknownControlError(control_id)

    last = db.scalar(
        select(SoaDecision.sequence)
        .where(
            SoaDecision.organization_id == org_id,
            SoaDecision.control_id == control_id,
        )
        .order_by(SoaDecision.sequence.desc())
        .limit(1)
    )
    sequence = (last or 0) + 1
    now = _now()
    db.add(
        SoaDecision(
            organization_id=org_id,
            control_id=control_id,
            sequence=sequence,
            applicable=applicable,
            justification_fr=justification_fr,
            editor_label=editor_label,
            created_at=now,
        )
    )
    projection = db.scalar(
        select(SoaControl).where(
            SoaControl.organization_id == org_id,
            SoaControl.control_id == control_id,
        )
    )
    if projection is None:
        projection = SoaControl(
            organization_id=org_id,
            control_id=control_id,
            applicable=applicable,
            justification_fr=justification_fr,
            editor_label=editor_label,
            decision_count=sequence,
            updated_at=now,
        )
        db.add(projection)
    else:
        projection.applicable = applicable
        projection.justification_fr = justification_fr
        projection.editor_label = editor_label
        projection.decision_count = sequence
        projection.updated_at = now
    db.commit()
    return projection


def decision_history(db: Session, org_id: str, control_id: str) -> list[SoaDecision]:
    if control_id not in {e["id"] for e in annex_a_controls()}:
        raise SoaUnknownControlError(control_id)
    return list(
        db.scalars(
            select(SoaDecision)
            .where(
                SoaDecision.organization_id == org_id,
                SoaDecision.control_id == control_id,
            )
            .order_by(SoaDecision.sequence)
        )
    )
