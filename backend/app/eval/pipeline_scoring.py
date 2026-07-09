"""Frozen pipeline scoring rules (eval/m6/regles_notation_pipeline.md).

Scoring is over plain per-finding dicts (the eval runner serializes ORM rows;
tests build them directly): {requirement_id, status, verdict, abstain_reason,
attempts, match_method, confidence}.

Denominators are explicit and distinct (rules §1):
- N          = all split items — availability/coverage denominator; items
               whose only outcome is an infrastructure failure appear there
               as the `infra_failed` category, never silently dropped;
- n_scored   = N - infra_failed — denominator of every quality metric.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.pipeline.state import Verdict, is_infrastructure_failure

from .stats import Metric

EVIDENTIARY_VERDICTS = ("compliant", "partial", "non_compliant")
SYSTEM_LABELS = EVIDENTIARY_VERDICTS + ("abstained",)
GOLD_VERDICTS = EVIDENTIARY_VERDICTS + ("missing",)

LABEL_INFRA_FAILED = "infra_failed"


@dataclass
class GoldItem:
    requirement_id: str
    verdict: str
    split: str
    document: str | None
    evidence_quote_fr: str | None


def load_gold(split: str, corpus_path: str | None = None) -> tuple[str, dict[str, GoldItem]]:
    """(corpus_version, {requirement_id: GoldItem}) for one split, gold order."""
    path = Path(corpus_path or settings.corpus_path) / "gold" / "gold_labels.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    items = {}
    for g in data["items"]:
        if g["split"] != split:
            continue
        items[g["requirement_id"]] = GoldItem(
            requirement_id=g["requirement_id"],
            verdict=g["verdict"],
            split=g["split"],
            document=g.get("document"),
            evidence_quote_fr=g.get("evidence_quote_fr"),
        )
    return data["meta"]["corpus_version"], items


def system_label(finding: dict) -> str:
    """Rules §1: VERIFIED -> its verdict; evidentiary ABSTAINED -> 'abstained';
    infrastructure ABSTAINED -> 'infra_failed' (categorized, never scored)."""
    status = finding["status"]
    if status == "VERIFIED":
        verdict = finding.get("verdict")
        if verdict == Verdict.MISSING.value:
            # structurally impossible (a missing verdict never verifies);
            # reaching this means the pipeline invariant broke
            raise ValueError(
                f"invariant violé : constat VERIFIED avec verdict missing "
                f"({finding.get('requirement_id')})"
            )
        if verdict not in EVIDENTIARY_VERDICTS:
            raise ValueError(f"verdict inconnu : {verdict!r}")
        return verdict
    if status == "ABSTAINED":
        if is_infrastructure_failure(finding.get("abstain_reason")):
            return LABEL_INFRA_FAILED
        return "abstained"
    raise ValueError(f"statut inconnu : {status!r}")


@dataclass
class PipelineScores:
    n_total: int                      # N — availability denominator
    n_scored: int                     # N - infra_failed
    infra_failed_ids: list[str]
    missing_ids: list[str]            # split ids with no finding at all (coverage gap)
    accuracy: Metric | None
    accuracy_by_gold_verdict: dict[str, Metric]
    confusion: dict[str, dict[str, int]]   # gold verdict -> system label -> count
    abstention_precision: Metric | None
    abstention_recall: Metric | None
    verified_rate: Metric | None
    repair_rate: Metric | None             # attempts == 2 among scored
    abstain_reasons: dict[str, int]
    match_methods: dict[str, int]
    confidence_correct: list[float] = field(default_factory=list)
    confidence_incorrect: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        def m(x):
            return x.to_dict() if x is not None else None

        return {
            "n_total": self.n_total,
            "n_scored": self.n_scored,
            "infra_failed_ids": self.infra_failed_ids,
            "missing_ids": self.missing_ids,
            "accuracy": m(self.accuracy),
            "accuracy_by_gold_verdict": {
                k: v.to_dict() for k, v in self.accuracy_by_gold_verdict.items()
            },
            "confusion": self.confusion,
            "abstention_precision": m(self.abstention_precision),
            "abstention_recall": m(self.abstention_recall),
            "verified_rate": m(self.verified_rate),
            "repair_rate": m(self.repair_rate),
            "abstain_reasons": self.abstain_reasons,
            "match_methods": self.match_methods,
            "confidence_correct": self.confidence_correct,
            "confidence_incorrect": self.confidence_incorrect,
        }


def is_correct(gold_verdict: str, label: str) -> bool:
    """Rules §2: correct iff (gold != missing and label == gold) or
    (gold == missing and label == 'abstained')."""
    if label == LABEL_INFRA_FAILED:
        raise ValueError("un item infra_failed n'est jamais noté")
    if gold_verdict == Verdict.MISSING.value:
        return label == "abstained"
    return label == gold_verdict


def score_findings(
    findings: dict[str, dict], gold: dict[str, GoldItem]
) -> PipelineScores:
    """Score one split. `findings` maps requirement_id -> finding dict; a split
    id absent from `findings` is a coverage gap (never scored, reported)."""
    n_total = len(gold)
    confusion: dict[str, dict[str, int]] = {
        gv: {sl: 0 for sl in SYSTEM_LABELS} for gv in GOLD_VERDICTS
    }
    infra_failed_ids: list[str] = []
    missing_ids: list[str] = []
    correct = 0
    per_verdict: dict[str, list[bool]] = {gv: [] for gv in GOLD_VERDICTS}
    abst_on_missing = 0
    abstentions = 0
    verified = 0
    repaired = 0
    abstain_reasons: dict[str, int] = {}
    match_methods: dict[str, int] = {}
    conf_correct: list[float] = []
    conf_incorrect: list[float] = []

    for rid, g in gold.items():
        f = findings.get(rid)
        if f is None:
            missing_ids.append(rid)
            continue
        label = system_label(f)
        if label == LABEL_INFRA_FAILED:
            infra_failed_ids.append(rid)
            reason = f.get("abstain_reason") or "?"
            abstain_reasons[reason] = abstain_reasons.get(reason, 0) + 1
            continue

        confusion[g.verdict][label] += 1
        ok = is_correct(g.verdict, label)
        correct += int(ok)
        per_verdict[g.verdict].append(ok)

        if label == "abstained":
            abstentions += 1
            if g.verdict == Verdict.MISSING.value:
                abst_on_missing += 1
            reason = f.get("abstain_reason") or "?"
            abstain_reasons[reason] = abstain_reasons.get(reason, 0) + 1
        else:
            verified += 1
            method = f.get("match_method") or "?"
            match_methods[method] = match_methods.get(method, 0) + 1
            conf = f.get("confidence")
            if conf is not None:
                (conf_correct if ok else conf_incorrect).append(conf)
        if (f.get("attempts") or 1) >= 2:
            repaired += 1

    n_scored = n_total - len(infra_failed_ids) - len(missing_ids)
    gold_missing_scored = sum(
        1 for rid, g in gold.items()
        if g.verdict == Verdict.MISSING.value
        and rid not in infra_failed_ids and rid not in missing_ids
    )
    return PipelineScores(
        n_total=n_total,
        n_scored=n_scored,
        infra_failed_ids=sorted(infra_failed_ids),
        missing_ids=sorted(missing_ids),
        accuracy=Metric.of(correct, n_scored) if n_scored else None,
        accuracy_by_gold_verdict={
            gv: Metric.of(sum(oks), len(oks))
            for gv, oks in per_verdict.items()
            if oks
        },
        confusion=confusion,
        abstention_precision=Metric.of(abst_on_missing, abstentions) if abstentions else None,
        abstention_recall=(
            Metric.of(abst_on_missing, gold_missing_scored) if gold_missing_scored else None
        ),
        verified_rate=Metric.of(verified, n_scored) if n_scored else None,
        repair_rate=Metric.of(repaired, n_scored) if n_scored else None,
        abstain_reasons=abstain_reasons,
        match_methods=match_methods,
        confidence_correct=conf_correct,
        confidence_incorrect=conf_incorrect,
    )
