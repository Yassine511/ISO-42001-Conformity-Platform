"""M7b anchor primitive: raw literal equality, all occurrences, overlaps.

Spec (§8): anchor verification for WRITES is stricter than for reads — no
normalization, no fuzzy matching. These tests pin the exact contract the
patch flow builds on (§15 matrix rows: fabricated anchor rejected, verbatim
passes, near-verbatim-at-normalization-level rejected, duplicate rejected).
"""

import unicodedata

import pytest

from app.services.anchors import Span, find_all_exact_anchors

PAGE = (
    "Politique de sécurité des systèmes d'IA.\n"
    "Les revues de risques sont conduites chaque trimestre.\n"
    "Les revues de risques sont conduites chaque trimestre.\n"
)


def test_verbatim_anchor_found_once():
    anchor = "Politique de sécurité des systèmes d'IA."
    spans = find_all_exact_anchors(PAGE, anchor)
    assert spans == [Span(start=0, end=len(anchor))]
    assert PAGE[spans[0].start : spans[0].end] == anchor


def test_fabricated_anchor_not_found():
    assert find_all_exact_anchors(PAGE, "Cette phrase n'existe pas.") == []


def test_duplicate_anchor_returns_every_occurrence():
    anchor = "Les revues de risques sont conduites chaque trimestre."
    spans = find_all_exact_anchors(PAGE, anchor)
    assert len(spans) == 2
    for s in spans:
        assert PAGE[s.start : s.end] == anchor


def test_nfc_nfd_near_match_is_rejected():
    # Same rendered text, different Unicode composition: the read-side verifier
    # would normalize these together; the write-side primitive must NOT.
    anchor_nfd = unicodedata.normalize("NFD", "Politique de sécurité")
    assert unicodedata.is_normalized("NFC", PAGE)
    assert find_all_exact_anchors(PAGE, anchor_nfd) == []
    # sanity: the NFC form IS found
    assert len(find_all_exact_anchors(PAGE, "Politique de sécurité")) == 1


def test_whitespace_near_match_is_rejected():
    assert find_all_exact_anchors(PAGE, "Politique  de sécurité") == []
    assert find_all_exact_anchors(PAGE, "politique de sécurité") == []  # case


def test_overlapping_occurrences_are_all_reported():
    spans = find_all_exact_anchors("aaaa", "aaa")
    assert spans == [Span(0, 3), Span(1, 4)]


def test_empty_anchor_raises():
    with pytest.raises(ValueError):
        find_all_exact_anchors(PAGE, "")


def test_anchor_longer_than_text():
    assert find_all_exact_anchors("court", "beaucoup plus long que le texte") == []


def test_anchor_at_exact_end_of_text():
    spans = find_all_exact_anchors("début et fin", "et fin")
    assert spans == [Span(6, 12)]
