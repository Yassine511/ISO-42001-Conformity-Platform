"""M8 scoring-policy registry: immutability and KB cross-check contracts."""

import json
from pathlib import Path

import pytest

from app.services import scoring_policy as sp

REPO_ROOT = Path(__file__).resolve().parents[2]
KB_PATH = REPO_ROOT / "corpus" / "kb" / "iso42001_kb.json"


def _kb() -> dict:
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


def test_m8_1_weights_match_their_authoring_kb():
    """The live KB `weight` field is the authoring source of m8-1: as long as
    the KB is at the corpus version m8-1 was cut from, the two must be equal
    (the policy map is the archived copy reporting actually reads)."""
    kb = _kb()
    policy = sp.SCORING_POLICIES["m8-1"]
    if kb["meta"]["corpus_version"] != policy["authored_for_corpus_version"]:
        pytest.skip("KB moved past m8-1's authoring corpus version (expected: archive only)")
    kb_weights = {e["id"]: e["weight"] for e in kb["requirements"]}
    assert dict(policy["weights"]) == kb_weights


def test_m8_1_covers_all_65_requirements_with_valid_weights():
    weights = sp.SCORING_POLICIES["m8-1"]["weights"]
    assert len(weights) == 65
    assert set(weights.values()) <= {1, 2, 3}


def test_resolve_policy_default_and_unknown():
    version, policy = sp.resolve_policy(None)
    assert version == sp.CURRENT_SCORING_POLICY == "m8-1"
    assert policy is sp.SCORING_POLICIES["m8-1"]
    with pytest.raises(KeyError) as exc:
        sp.resolve_policy("m9-99")
    assert "m8-1" in str(exc.value)  # known versions listed for the 422 body


def test_resolve_weight_unscored_is_explicit():
    _, policy = sp.resolve_policy(None)
    assert sp.resolve_weight(policy, "A.7.4") == (3, "policy")
    assert sp.resolve_weight(policy, "Z.99") == (None, "unscored_weight")


def test_severity_bands_over_the_reachable_set():
    """gap_factor x weight reaches exactly {1,2,3,4,6,9}: low 1-2, medium 3-4,
    high 6-9 (5, 7, 8 unreachable)."""
    seen = {}
    for gf in sp.GAP_FACTOR.values():
        for w in (1, 2, 3):
            score, band = sp.severity_band(gf, w)
            seen[score] = band
    assert sorted(seen) == [1, 2, 3, 4, 6, 9]
    assert {s: b for s, b in seen.items()} == {
        1: "low", 2: "low", 3: "medium", 4: "medium", 6: "high", 9: "high",
    }


def test_registry_is_read_only():
    with pytest.raises(TypeError):
        sp.SCORING_POLICIES["m8-1"]["weights"]["4.1"] = 9  # type: ignore[index]
