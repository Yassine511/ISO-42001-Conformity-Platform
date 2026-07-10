"""Raw-equality anchor search for document WRITES (M7b patch flow).

Deliberately the OPPOSITE of the read-side verifier (app/pipeline/verifier.py):
no NFC normalization, no casefolding, no whitespace folding, no fuzzy matching.
The model saw the extracted page text and can copy an anchor exactly; a write
that cannot be located by literal equality must not be applied.

The primitive is a pure text search over the stored `DocumentPage.text` string
as-is. Policy (minimum anchor length, exactly-one-match requirement) belongs to
the patch-validation layer, not here: this function honestly reports EVERY
occurrence — including overlapping ones (the scan advances by one character,
not by the anchor length) — so ambiguity detection cannot be fooled by
self-overlapping anchors.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """Half-open [start, end) character offsets into the searched text,
    satisfying text[start:end] == anchor_quote."""

    start: int
    end: int


def find_all_exact_anchors(text: str, anchor_quote: str) -> list[Span]:
    """Return every span where `anchor_quote` occurs in `text` by raw literal
    equality, in ascending start order, overlapping occurrences included.

    Raises ValueError on an empty anchor (an empty string "occurs" everywhere;
    callers must never get a silently meaningless result).
    """
    if anchor_quote == "":
        raise ValueError("anchor_quote must not be empty")
    spans: list[Span] = []
    start = text.find(anchor_quote)
    while start != -1:
        spans.append(Span(start=start, end=start + len(anchor_quote)))
        start = text.find(anchor_quote, start + 1)  # +1, not +len: overlaps count
    return spans
