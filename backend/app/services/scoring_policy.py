"""Immutable scoring-policy registry (M8 Node ⑤).

Severity = gap_factor(human_verdict) x control weight, mapped to a
low/medium/high band. Reproducibility contract:

- Each policy version archives its FULL weight map here, permanently. The live
  KB ``weight`` field is only the *authoring source* for the policy that was
  cut from it (a pytest cross-checks KB <-> policy equality for that corpus
  version); reporting NEVER resolves weights from the live KB, so a later
  corpus or policy bump can never silently rescore history.
- Callers may pin ``?scoring_policy_version=`` on reporting endpoints; the
  chosen version is echoed in every response. ``CURRENT_SCORING_POLICY``
  ("m8-1") stays the permanent default for this project unless a documented
  corpus -> policy mapping supersedes it.
- Resolution is by requirement_id. An id absent from the policy map yields
  ``weight=None`` / ``weight_source="unscored_weight"`` and an unscored
  severity — an explicit condition, never a plausible-looking default.

gap_factor: partial=1, non_compliant=2, missing=3; weight in {1,2,3}. The
product's reachable values are {1, 2, 3, 4, 6, 9} — 5, 7 and 8 are
unreachable. Bands: low 1-2, medium 3-4, high 6-9.

Weight rubric (m8-1, authored for corpus_version 1.3.0):
  3 = risk/impact backbone, top-management accountability, controls whose
      absence directly enables harm (data quality/provenance, human oversight,
      V&V before release, misuse prevention, supplier due diligence, the
      corrective-action loop);
  1 = purely documentary / inventory / communication-record controls;
  2 = everything else (default operational/process controls).
"""

from __future__ import annotations

from types import MappingProxyType

GAP_FACTOR = MappingProxyType({"partial": 1, "non_compliant": 2, "missing": 3})

# Severity bands over gap_factor x weight (closed over the reachable set).
SEVERITY_LOW_MAX = 2
SEVERITY_MEDIUM_MAX = 4

_M8_1_WEIGHTS = MappingProxyType({
    "4.1": 2, "4.2": 2, "4.3": 2, "4.4": 3,
    "5.1": 3, "5.2": 3, "5.3": 2,
    "6.1.1": 2, "6.1.2": 3, "6.1.3": 3, "6.1.4": 3, "6.2": 2, "6.3": 1,
    "7.1": 2, "7.2": 2, "7.3": 1, "7.4": 1, "7.5": 2,
    "8.1": 3, "8.2": 3, "8.3": 3, "8.4": 3,
    "9.1": 2, "9.2": 2, "9.3": 2,
    "10.1": 1, "10.2": 3,
    "A.2.2": 3, "A.2.3": 1, "A.2.4": 1,
    "A.3.2": 2, "A.3.3": 2,
    "A.4.2": 1, "A.4.3": 2, "A.4.4": 1, "A.4.5": 1, "A.4.6": 1,
    "A.5.2": 3, "A.5.3": 2, "A.5.4": 3, "A.5.5": 2,
    "A.6.1.2": 2, "A.6.1.3": 3,
    "A.6.2.2": 2, "A.6.2.3": 2, "A.6.2.4": 3, "A.6.2.5": 2,
    "A.6.2.6": 3, "A.6.2.7": 1, "A.6.2.8": 2,
    "A.7.2": 3, "A.7.3": 2, "A.7.4": 3, "A.7.5": 3, "A.7.6": 2,
    "A.8.2": 2, "A.8.3": 2, "A.8.4": 2, "A.8.5": 2,
    "A.9.2": 3, "A.9.3": 2, "A.9.4": 3,
    "A.10.2": 2, "A.10.3": 3, "A.10.4": 1,
})

SCORING_POLICIES = MappingProxyType({
    "m8-1": MappingProxyType({
        # corpus version the weights were authored against (informational —
        # resolution is by requirement_id, not by corpus version)
        "authored_for_corpus_version": "1.3.0",
        "weights": _M8_1_WEIGHTS,
    }),
})

CURRENT_SCORING_POLICY = "m8-1"


def resolve_policy(version: str | None) -> tuple[str, dict]:
    """Return (version, policy). Unknown version raises KeyError with the
    known versions in the message (the API layer maps it to a French 422)."""
    chosen = version or CURRENT_SCORING_POLICY
    if chosen not in SCORING_POLICIES:
        raise KeyError(
            f"unknown scoring policy {chosen!r}; known: {sorted(SCORING_POLICIES)}"
        )
    return chosen, SCORING_POLICIES[chosen]


def resolve_weight(policy: dict, requirement_id: str) -> tuple[int | None, str]:
    """Weight for a requirement under a policy: (weight, weight_source)."""
    weight = policy["weights"].get(requirement_id)
    if weight is None:
        return None, "unscored_weight"
    return weight, "policy"


def severity_band(gap_factor: int, weight: int) -> tuple[int, str]:
    """(severity_score, band) — band in {'low','medium','high'}."""
    score = gap_factor * weight
    if score <= SEVERITY_LOW_MAX:
        return score, "low"
    if score <= SEVERITY_MEDIUM_MAX:
        return score, "medium"
    return score, "high"
