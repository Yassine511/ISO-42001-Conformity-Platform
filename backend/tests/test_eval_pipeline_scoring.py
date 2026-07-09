"""Frozen pipeline scoring rules (M6 harness) — every gold×system cell.

Pure functions over finding dicts — no DB, no LLM.
"""

import pytest

from app.eval.pipeline_scoring import (
    LABEL_INFRA_FAILED,
    GoldItem,
    is_correct,
    score_findings,
    system_label,
)


def _gold(rid: str, verdict: str) -> GoldItem:
    return GoldItem(
        requirement_id=rid,
        verdict=verdict,
        split="dev",
        document=None if verdict == "missing" else "doc.md",
        evidence_quote_fr=None if verdict == "missing" else "extrait",
    )


def _finding(rid: str, status: str, verdict=None, abstain_reason=None, **kw) -> dict:
    return {
        "requirement_id": rid,
        "status": status,
        "verdict": verdict,
        "abstain_reason": abstain_reason,
        "attempts": kw.get("attempts", 1),
        "match_method": kw.get("match_method"),
        "confidence": kw.get("confidence"),
    }


# ---------------------------------------------------------------- system_label


def test_verified_maps_to_its_verdict():
    for verdict in ("compliant", "partial", "non_compliant"):
        assert system_label(_finding("4.1", "VERIFIED", verdict)) == verdict


def test_evidentiary_abstentions_map_to_abstained():
    for reason in ("model_abstained", "verification_failed", "fuzzy_citation", "low_confidence"):
        assert system_label(_finding("4.1", "ABSTAINED", abstain_reason=reason)) == "abstained"


def test_infrastructure_abstentions_are_categorized_not_scored():
    for reason in ("llm_error", "rate_limited"):
        assert (
            system_label(_finding("4.1", "ABSTAINED", abstain_reason=reason))
            == LABEL_INFRA_FAILED
        )


def test_verified_missing_is_impossible():
    with pytest.raises(ValueError, match="invariant"):
        system_label(_finding("4.1", "VERIFIED", "missing"))


def test_unknown_status_raises():
    with pytest.raises(ValueError):
        system_label(_finding("4.1", "CONFIRMED"))


# ---------------------------------------------------------------- is_correct


@pytest.mark.parametrize(
    "gold,label,expected",
    [
        # gold non-missing: correct only on exact verdict match
        ("compliant", "compliant", True),
        ("compliant", "partial", False),
        ("compliant", "non_compliant", False),
        ("compliant", "abstained", False),
        ("partial", "partial", True),
        ("partial", "compliant", False),
        ("partial", "abstained", False),
        ("non_compliant", "non_compliant", True),
        ("non_compliant", "compliant", False),
        ("non_compliant", "abstained", False),
        # gold missing: only abstention is correct
        ("missing", "abstained", True),
        ("missing", "compliant", False),
        ("missing", "partial", False),
        ("missing", "non_compliant", False),
    ],
)
def test_every_gold_system_cell(gold, label, expected):
    assert is_correct(gold, label) is expected


def test_infra_failed_is_never_scored():
    with pytest.raises(ValueError):
        is_correct("compliant", LABEL_INFRA_FAILED)


# ---------------------------------------------------------------- score_findings


def _score_fixture():
    gold = {
        "A": _gold("A", "compliant"),
        "B": _gold("B", "partial"),
        "C": _gold("C", "non_compliant"),
        "D": _gold("D", "missing"),
        "E": _gold("E", "missing"),
        "F": _gold("F", "compliant"),
    }
    findings = {
        "A": _finding("A", "VERIFIED", "compliant", match_method="exact", confidence=0.9),
        "B": _finding("B", "VERIFIED", "compliant", match_method="exact", confidence=0.6),  # wrong
        "C": _finding("C", "ABSTAINED", abstain_reason="fuzzy_citation", attempts=2),  # wrong
        "D": _finding("D", "ABSTAINED", abstain_reason="model_abstained"),  # correct
        "E": _finding("E", "ABSTAINED", abstain_reason="rate_limited"),  # infra
        # F: no finding at all (coverage gap)
    }
    return gold, findings


def test_score_findings_denominators_and_accuracy():
    gold, findings = _score_fixture()
    scores = score_findings(findings, gold)
    assert scores.n_total == 6
    assert scores.infra_failed_ids == ["E"]
    assert scores.missing_ids == ["F"]
    # n_scored excludes infra AND unfound coverage gaps
    assert scores.n_scored == 4
    assert scores.accuracy.count == 2 and scores.accuracy.n == 4


def test_score_findings_abstention_precision_recall():
    gold, findings = _score_fixture()
    scores = score_findings(findings, gold)
    # evidentiary abstentions: C (gold non_compliant) and D (gold missing)
    assert scores.abstention_precision.count == 1
    assert scores.abstention_precision.n == 2
    # gold missing among scored items: only D (E is infra-failed)
    assert scores.abstention_recall.count == 1
    assert scores.abstention_recall.n == 1


def test_score_findings_confusion_and_telemetry():
    gold, findings = _score_fixture()
    scores = score_findings(findings, gold)
    assert scores.confusion["compliant"]["compliant"] == 1
    assert scores.confusion["partial"]["compliant"] == 1
    assert scores.confusion["non_compliant"]["abstained"] == 1
    assert scores.confusion["missing"]["abstained"] == 1
    # infra item appears in no confusion cell
    assert sum(sum(row.values()) for row in scores.confusion.values()) == 4
    assert scores.verified_rate.count == 2
    assert scores.repair_rate.count == 1
    assert scores.confidence_correct == [0.9]
    assert scores.confidence_incorrect == [0.6]
    assert scores.abstain_reasons["rate_limited"] == 1
    assert scores.match_methods == {"exact": 2}
