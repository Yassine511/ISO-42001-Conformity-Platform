"""Unit tests for the deterministic citation verifier (M3 node ③ core).

Pure functions — no DB, no Qdrant, no LLM. The real-corpus test reads a
dev-split gold quote (test split is reserved for M6 and never touched).
"""

import json
from pathlib import Path

import pytest

from app.config import settings
from app.pipeline.state import DraftFinding, Verdict
from app.pipeline.verifier import (
    CONFIDENCE_MIN,
    MAX_QUOTE_LEN,
    MIN_QUOTE_LEN,
    PARTIAL_RATIO_MIN,
    find_quote,
    normalize,
    verify,
)

SOURCE = (
    "Le Comité IA de Lumen AI se réunit chaque trimestre pour examiner les risques. "
    "Les collaborateurs doivent signaler tout incident dans un délai de 48 heures. "
    "La revue de la politique est effectuée si nécessaire par la direction générale."
)


def _retrieved(text: str = SOURCE, char_start: int = 100) -> list[dict]:
    return [
        {
            "result_id": "chunk-1",
            "source_type": "policy",
            "text": text,
            "char_start": char_start,
            "page_number": 1,
        }
    ]


def _draft(quote, clause="A.9.2", verdict=Verdict.COMPLIANT, confidence=0.9) -> DraftFinding:
    return DraftFinding(
        verdict=verdict,
        policy_quote=quote,
        clause_ref=clause,
        confidence=confidence,
        rationale="test",
    )


# ------------------------------------------------------------ quote matching


def test_real_gold_dev_quote_accepted_against_its_document():
    gold = json.loads(
        (Path(settings.corpus_path) / "gold" / "gold_labels.json").read_text(encoding="utf-8")
    )
    item = next(
        i for i in gold["items"] if i["split"] == "dev" and i["evidence_quote_fr"]
    )
    doc_text = (Path(settings.corpus_path) / "documents" / item["document"]).read_text(
        encoding="utf-8"
    )
    located = find_quote(item["evidence_quote_fr"], doc_text)
    assert located is not None
    start, end, method, score = located
    # the raw span must slice back to (a normalized-equivalent of) the quote
    assert normalize(doc_text[start:end]).text == normalize(item["evidence_quote_fr"]).text


def test_planted_fake_quote_rejected():
    fake = "Lumen AI applique une politique de tolérance zéro concernant les données biométriques."
    assert find_quote(fake, SOURCE) is None


@pytest.mark.parametrize(
    "variant",
    [
        "Les collaborateurs  doivent   signaler tout incident dans un délai de 48 heures.",
        "LES COLLABORATEURS DOIVENT SIGNALER TOUT INCIDENT DANS UN DÉLAI DE 48 HEURES.",
        "Les collaborateurs doivent signaler tout incident dans un delai de 48 heures.",  # accents stripped
        "Les collaborateurs doivent signaler tout incident dans un délai de 48 heures.",  # NBSP
        "Les collaborateurs doivent signaler tout incident dnas un délai de 48 heures.",  # transposition typo
    ],
)
def test_honest_variants_accepted(variant):
    assert find_quote(variant, SOURCE) is not None


def test_smart_quotes_and_guillemets_accepted():
    source = "L’usage des systèmes dits « critiques » exige une validation préalable du comité."
    quote = 'L\'usage des systèmes dits "critiques" exige une validation préalable du comité.'
    located = find_quote(quote, source)
    # double-quote marks normalize to spaces, so honest typographic quoting
    # («␣critiques␣» vs "critiques") matches EXACTLY — it must not degrade to
    # a fuzzy candidate now that only exact matches verify
    assert located is not None
    assert located[2] == "exact"


def test_verify_treats_fuzzy_match_as_repairable_error():
    source = "Les collaborateurs doivent signaler tout incident dans un délai de 48 heures."
    retrieved = [
        {"source_type": "policy", "result_id": "c1", "text": source, "char_start": 0}
    ]
    fuzzy_quote = source.replace("dans", "dnas")  # transposition: fuzzy, not exact
    result = verify(_draft(fuzzy_quote), retrieved, "A.9.2")
    assert not result.ok
    assert any("citation approximative" in e for e in result.repair_errors)
    assert result.match is not None and result.match.method == "fuzzy"  # kept for review

    exact = verify(_draft(source), retrieved, "A.9.2")
    assert exact.ok and exact.match.method == "exact"


def test_paraphrase_rejected():
    paraphrase = "Le personnel est tenu de déclarer les incidents sous deux jours."
    assert find_quote(paraphrase, SOURCE) is None


def test_deleted_negation_rejected():
    source = (
        "Les données personnelles ne sont pas utilisées pour l'entraînement des modèles "
        "sans le consentement explicite et documenté des personnes concernées par le traitement."
    )
    tampered = (
        "Les données personnelles sont utilisées pour l'entraînement des modèles "
        "sans le consentement explicite et documenté des personnes concernées par le traitement."
    )
    assert find_quote(source, source) is not None
    assert find_quote(tampered, source) is None


def test_changed_number_rejected():
    tampered = "Les collaborateurs doivent signaler tout incident dans un délai de 72 heures."
    assert find_quote(tampered, SOURCE) is None


# Meaning-flipping single-word substitutions score >92 partial_ratio on long
# quotes (audit-reproduced: doivent->peuvent 98.4, obligatoirement->librement
# 95.3) — the token-alignment guard must reject them while keeping typos.
LONG_SOURCE = (
    "Les collaborateurs doivent signaler tout incident dans les meilleurs délais "
    "au responsable de la conformité qui tient le registre à jour et informe la "
    "direction générale après chaque revue trimestrielle du dispositif."
)


@pytest.mark.parametrize(
    ("original", "tampered"),
    [
        ("doivent", "peuvent"),          # obligation -> permission
        ("après", "avant"),              # temporal inversion
        ("doivent", "devraient"),        # obligation -> recommendation
    ],
)
def test_meaning_flipping_substitution_rejected(original, tampered):
    assert find_quote(LONG_SOURCE, LONG_SOURCE) is not None  # sanity
    assert find_quote(LONG_SOURCE.replace(original, tampered), LONG_SOURCE) is None


def test_obligation_adverb_swap_rejected():
    source = (
        "La formation est suivie obligatoirement par tous les collaborateurs "
        "concernés avant toute utilisation des systèmes en production."
    )
    assert find_quote(source.replace("obligatoirement", "librement"), source) is None


def test_mechanical_typos_still_accepted_by_token_guard():
    assert find_quote(LONG_SOURCE.replace("registre", "registtre"), LONG_SOURCE) is not None
    assert find_quote(LONG_SOURCE.replace("dans", "dnas"), LONG_SOURCE) is not None


@pytest.mark.parametrize(
    ("original", "tampered"),
    [
        ("six mois", "dix mois"),   # written number (digit guard can't see it)
        ("les", "des"),             # grammatical change, edit distance 1
        ("dans", "dens"),           # plain substitution: indistinguishable from tampering
    ],
)
def test_one_edit_substitutions_rejected(original, tampered):
    source = (
        "La revue de direction du dispositif de gouvernance est organisée tous "
        "les six mois par le responsable conformité et donne lieu à un compte "
        "rendu diffusé dans les meilleurs délais à la direction générale."
    )
    assert find_quote(source, source) is not None  # sanity
    assert find_quote(source.replace(original, tampered, 1), source) is None


def test_too_short_and_too_long_quotes_rejected():
    assert find_quote("Comité IA", SOURCE) is None  # < MIN_QUOTE_LEN
    long_source = "a" * 400
    assert find_quote("a" * (MAX_QUOTE_LEN + 10), long_source) is None


def test_offset_mapping_with_whitespace_accents_and_ellipsis():
    source = "Préambule.   La   revue annuelle…  est obligatoire chaque année. Fin."
    quote = "La revue annuelle... est obligatoire chaque année."
    located = find_quote(quote, source)
    assert located is not None
    start, end, method, _ = located
    # the stored raw span must highlight the intended source text
    assert source[start:end].startswith("La   revue")
    assert source[start:end].rstrip().endswith("année.")
    assert normalize(source[start:end]).text == normalize(quote).text


# ------------------------------------------------------------ verify()


def test_verify_accepts_valid_draft_with_page_relative_offsets():
    quote = "Les collaborateurs doivent signaler tout incident dans un délai de 48 heures."
    result = verify(_draft(quote), _retrieved(char_start=100), "A.9.2")
    assert result.ok
    assert result.match is not None
    assert result.match.chunk_id == "chunk-1"
    local = SOURCE.find("Les collaborateurs")
    assert result.match.match_start == 100 + local
    assert result.match.method == "exact"


def test_valid_but_wrong_clause_ref_rejected():
    quote = "Les collaborateurs doivent signaler tout incident dans un délai de 48 heures."
    result = verify(_draft(quote, clause="A.7.2"), _retrieved(), "A.9.2")
    assert not result.ok
    assert any("clause_ref invalide" in e for e in result.errors)
    assert result.repair_errors  # retryable


def test_missing_verdict_needs_no_quote():
    draft = _draft(None, verdict=Verdict.MISSING)
    result = verify(draft, [], "A.9.2")
    assert result.ok


def test_missing_verdict_with_nonnull_quote_rejected():
    # "no evidence exists" + a citation is incoherent (prompt requires null)
    draft = _draft("Une citation fabriquée qui ne devrait pas être là.", verdict=Verdict.MISSING)
    result = verify(draft, [], "A.9.2")
    assert not result.ok
    assert any("doit être null" in e for e in result.errors)
    assert result.repair_errors  # retryable


def test_missing_verdict_with_wrong_clause_is_retryable():
    draft = _draft(None, clause="A.7.2", verdict=Verdict.MISSING)
    result = verify(draft, [], "A.9.2")
    assert not result.ok
    assert result.repair_errors


def test_non_missing_verdict_requires_quote():
    result = verify(_draft(None), _retrieved(), "A.9.2")
    assert not result.ok
    assert any("policy_quote manquante" in e for e in result.errors)


def test_low_confidence_flagged_but_never_in_repair_errors():
    quote = "Les collaborateurs doivent signaler tout incident dans un délai de 48 heures."
    result = verify(_draft(quote, confidence=CONFIDENCE_MIN - 0.1), _retrieved(), "A.9.2")
    assert not result.ok
    assert result.low_confidence
    assert result.repair_errors == []  # low confidence alone: abstain, no retry
    assert any("seuil" in e for e in result.errors)


def test_verify_returns_all_applicable_errors():
    fake = "Une citation totalement inventée qui n'existe dans aucun extrait fourni ici."
    result = verify(_draft(fake, clause="A.7.2", confidence=0.1), _retrieved(), "A.9.2")
    assert not result.ok
    assert len(result.errors) == 3  # clause + citation + confidence
    assert len(result.repair_errors) == 2  # confidence excluded from repair


def test_out_of_range_confidence_is_a_schema_error():
    with pytest.raises(Exception):
        _draft("x", confidence=1.5)
