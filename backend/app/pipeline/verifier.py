"""Deterministic citation verifier (M3 node ③).

Tolerant-but-strict quote matching: honest quotes survive whitespace, casing,
accent and typographic differences; fabricated or paraphrased quotes do not.

Normalization keeps an index map (normalized char -> original offsets) because
whitespace collapse, ellipsis expansion and accent-mark removal change string
lengths — offsets found in normalized space must be converted back to raw
chunk offsets for M5 source highlighting.

Accent-stripping deliberately duplicates the idiom of services/bm25.py:analyze
WITHOUT reusing it: the BM25 analyzer also stems and drops stopwords, which
must never be applied to citation matching.

Thresholds are documented policy constants, pinned by boundary tests:
- PARTIAL_RATIO_MIN = 92.0 tolerates roughly one typo per ~12 characters while
  rejecting paraphrase. Fuzzy acceptance additionally requires the digit
  sequence and the French negation-token multiset of the quote to match the
  aligned source window — a high partial_ratio alone would accept a deleted
  "ne … pas" in a long quote (~96 for a 200-char quote), which flips meaning.
- CONFIDENCE_MIN is an UNCALIBRATED policy threshold on a model-generated
  number, kept because the spec (§6) gates on it; the raw value is persisted
  as telemetry and M6 measures whether it correlates with correctness. A
  confidence failure is never fed back to the model for repair (that only
  teaches it to emit a higher number).
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.pipeline.state import DraftFinding, QuoteMatch, Verdict, VerificationResult

PARTIAL_RATIO_MIN = 92.0
MIN_QUOTE_LEN = 15   # normalized chars; shorter quotes match almost anything
MAX_QUOTE_LEN = 300  # grounding contract cap (schema also enforces)
CONFIDENCE_MIN = 0.5

# Typographic equivalences (French corpus uses smart quotes, guillemets,
# non-breaking spaces). Multi-char expansions are supported by the index map.
_TRANSLATE = {
    "’": "'", "‘": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "«": '"', "»": '"',
    " ": " ", " ": " ", " ": " ",
    "–": "-", "—": "-",
    "…": "...",
}

_NEGATION_TOKENS = {"ne", "n", "pas", "non", "jamais", "aucun", "aucune", "sans", "interdit"}


@dataclass
class NormalizedText:
    text: str
    # per normalized character: original [start, end) offsets
    starts: list[int]
    ends: list[int]

    def to_original_span(self, nstart: int, nend: int) -> tuple[int, int]:
        """Map a normalized [nstart, nend) span back to original offsets."""
        return self.starts[nstart], self.ends[nend - 1]


def normalize(text: str) -> NormalizedText:
    """NFC-per-char -> typographic translate -> casefold -> strip accents ->
    collapse whitespace, tracking original offsets for every emitted char."""
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    pending_space: tuple[int, int] | None = None  # (orig_start, orig_end) of ws run

    for i, ch in enumerate(text):
        piece = unicodedata.normalize("NFC", ch)
        piece = "".join(_TRANSLATE.get(c, c) for c in piece)
        piece = piece.casefold()
        piece = "".join(
            c for c in unicodedata.normalize("NFD", piece) if not unicodedata.combining(c)
        )
        for c in piece:
            if c.isspace():
                if pending_space is None:
                    pending_space = (i, i + 1)
                else:
                    pending_space = (pending_space[0], i + 1)
                continue
            if pending_space is not None:
                if out:  # no leading space
                    out.append(" ")
                    starts.append(pending_space[0])
                    ends.append(pending_space[1])
                pending_space = None
            out.append(c)
            starts.append(i)
            ends.append(i + 1)
    # trailing whitespace dropped
    return NormalizedText("".join(out), starts, ends)


def _digit_sequence(text: str) -> list[str]:
    return re.findall(r"\d+", text)


def _negation_counts(text: str) -> Counter:
    tokens = re.findall(r"\w+", text, flags=re.UNICODE)
    return Counter(t for t in tokens if t in _NEGATION_TOKENS)


def find_quote(quote: str, chunk_text: str) -> tuple[int, int, str, float] | None:
    """Locate `quote` in `chunk_text`. Returns raw (start, end, method, score)
    offsets into chunk_text, or None if the quote cannot be verified."""
    nq = normalize(quote)
    nc = normalize(chunk_text)
    if not (MIN_QUOTE_LEN <= len(nq.text) <= MAX_QUOTE_LEN):
        return None

    # 1) exact after normalization — covers whitespace/case/accents/typography
    idx = nc.text.find(nq.text)
    if idx != -1:
        start, end = nc.to_original_span(idx, idx + len(nq.text))
        return start, end, "exact", 100.0

    # 2) windowed edit distance, then deterministic content guards
    alignment = fuzz.partial_ratio_alignment(nq.text, nc.text)
    if alignment is None or alignment.score < PARTIAL_RATIO_MIN:
        return None
    window = nc.text[alignment.dest_start:alignment.dest_end]
    if _digit_sequence(nq.text) != _digit_sequence(window):
        return None
    if _negation_counts(nq.text) != _negation_counts(window):
        return None
    if alignment.dest_end <= alignment.dest_start:
        return None
    start, end = nc.to_original_span(alignment.dest_start, alignment.dest_end)
    return start, end, "fuzzy", float(alignment.score)


def find_quote_in_retrieved(quote: str, retrieved: list[dict]) -> QuoteMatch | None:
    """Try each retrieved policy chunk; return page-relative raw offsets."""
    for item in retrieved:
        if item.get("source_type") != "policy":
            continue
        located = find_quote(quote, item["text"])
        if located is not None:
            start, end, method, score = located
            base = item.get("char_start") or 0
            return QuoteMatch(
                chunk_id=item["result_id"],
                match_start=base + start,
                match_end=base + end,
                method=method,
                score=score,
            )
    return None


def verify(draft: DraftFinding, retrieved: list[dict], requirement_id: str) -> VerificationResult:
    """Deterministic checks over a schema-valid draft.

    errors        = every applicable failure (persisted provenance)
    repair_errors = the subset fed back to the model on the single retry
                    (excludes the confidence policy threshold — see module doc)
    """
    errors: list[str] = []
    repair_errors: list[str] = []
    match: QuoteMatch | None = None
    low_confidence = False

    if draft.clause_ref != requirement_id:
        msg = (
            f"clause_ref invalide : « {draft.clause_ref} » ne correspond pas à "
            f"l'exigence évaluée ; utilisez exactement « {requirement_id} »."
        )
        errors.append(msg)
        repair_errors.append(msg)

    if draft.verdict != Verdict.MISSING:
        quote = (draft.policy_quote or "").strip()
        if not quote:
            msg = (
                "policy_quote manquante : tout verdict autre que « missing » exige "
                "une citation exacte extraite des extraits fournis."
            )
            errors.append(msg)
            repair_errors.append(msg)
        else:
            nq_len = len(normalize(quote).text)
            if nq_len < MIN_QUOTE_LEN:
                msg = (
                    f"policy_quote trop courte ({nq_len} caractères utiles) : "
                    f"citez un passage d'au moins {MIN_QUOTE_LEN} caractères."
                )
                errors.append(msg)
                repair_errors.append(msg)
            elif nq_len > MAX_QUOTE_LEN:
                msg = (
                    f"policy_quote trop longue ({nq_len} caractères) : "
                    f"maximum {MAX_QUOTE_LEN} caractères."
                )
                errors.append(msg)
                repair_errors.append(msg)
            else:
                match = find_quote_in_retrieved(quote, retrieved)
                if match is None:
                    msg = (
                        "citation introuvable : la policy_quote doit exister mot pour "
                        "mot dans les extraits fournis ; citez un passage verbatim, "
                        "sans reformulation."
                    )
                    errors.append(msg)
                    repair_errors.append(msg)

    if draft.confidence < CONFIDENCE_MIN:
        low_confidence = True
        # Provenance-only error: never sent to the model for repair.
        errors.append(
            f"confiance {draft.confidence:.2f} sous le seuil de politique "
            f"{CONFIDENCE_MIN} (seuil non calibré, télémesure M6)."
        )

    return VerificationResult(
        ok=not errors,
        errors=errors,
        repair_errors=repair_errors,
        match=match,
        low_confidence=low_confidence,
    )
