"""Deterministic paragraph-aware chunking with exact provenance offsets.

Invariants (unit-tested, relied on by the M3 citation verifier):
  - page_text[chunk.char_start:chunk.char_end] == chunk.text, always;
  - every non-whitespace character of the page belongs to at least one chunk;
  - same input -> same chunks (no randomness, no state).

Strategy: pack consecutive paragraphs (blank-line separated) up to
TARGET_CHARS. A single paragraph longer than HARD_MAX_CHARS is split at
sentence boundaries, then at whitespace as a last resort; only those forced
splits receive a small backward overlap so a quote near the cut is fully
contained in one of the two chunks.
"""

import hashlib
import re
from dataclasses import dataclass

# "2": the forward-only cut cursor (last_cut) changed cut-point selection for
# long paragraphs; that change shipped without a bump, so "1" ambiguously
# covers both behaviours. Reindex after deploying.
CHUNKER_VERSION = "2"
TARGET_CHARS = 1000
HARD_MAX_CHARS = 1200
FORCED_SPLIT_OVERLAP = 100

_SENTENCE_END = re.compile(r"[.!?…]+[\s»)\"]*\s")


@dataclass(frozen=True)
class ChunkSpan:
    char_start: int
    char_end: int
    text: str


def make_chunk_id(document_id: str, parser_version: str, page_number: int, char_start: int, char_end: int) -> str:
    key = f"{document_id}:{parser_version}:{CHUNKER_VERSION}:{page_number}:{char_start}:{char_end}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def chunk_page(page_text: str) -> list[ChunkSpan]:
    spans: list[tuple[int, int]] = []
    buf: tuple[int, int] | None = None

    for p_start, p_end in _paragraph_spans(page_text):
        if p_end - p_start > HARD_MAX_CHARS:
            if buf is not None:
                spans.append(buf)
                buf = None
            spans.extend(_split_long_paragraph(page_text, p_start, p_end))
            continue
        if buf is None:
            buf = (p_start, p_end)
        elif p_end - buf[0] <= TARGET_CHARS:
            buf = (buf[0], p_end)
        else:
            spans.append(buf)
            buf = (p_start, p_end)
    if buf is not None:
        spans.append(buf)

    return [ChunkSpan(s, e, page_text[s:e]) for s, e in spans]


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Spans of blank-line-separated blocks, trimmed of edge whitespace."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    end = 0
    pos = 0
    for line in text.splitlines(keepends=True):
        if line.strip():
            if start is None:
                start = pos + (len(line) - len(line.lstrip()))
            end = pos + len(line.rstrip())
        elif start is not None:
            spans.append((start, end))
            start = None
        pos += len(line)
    if start is not None:
        spans.append((start, end))
    return spans


def _split_long_paragraph(text: str, p_start: int, p_end: int) -> list[tuple[int, int]]:
    """Split an oversized paragraph at sentence, then whitespace boundaries."""
    # Candidate cut positions: just after each sentence end inside the paragraph.
    # finditer(text, pos, endpos) yields matches with ABSOLUTE offsets already.
    cuts = [m.end() for m in _SENTENCE_END.finditer(text, p_start, p_end)]
    pieces: list[tuple[int, int]] = []
    seg_start = p_start
    # Forward-only cut cursor: the overlap moves seg_start BACKWARD, so
    # without this floor the previous cut stays eligible and the loop
    # degenerates into tiny creeping duplicates (e.g. 804-900, 808-900, ...).
    last_cut = p_start
    while p_end - seg_start > HARD_MAX_CHARS:
        low = max(seg_start, last_cut)
        # Prefer a sentence boundary within the target; failing that, accept
        # one anywhere up to the hard max — a sentence cut at 1101 beats a
        # mid-sentence whitespace cut at 1196.
        in_target = [c for c in cuts if low < c <= seg_start + TARGET_CHARS]
        in_hard_max = [c for c in cuts if low < c <= seg_start + HARD_MAX_CHARS]
        if in_target:
            cut = in_target[-1]
        elif in_hard_max:
            cut = in_hard_max[-1]
        else:
            cut = _last_whitespace_before(text, seg_start + HARD_MAX_CHARS, low)
            if cut is None:
                cut = seg_start + HARD_MAX_CHARS  # pathological: no whitespace at all
        last_cut = cut
        pieces.append((seg_start, cut))
        # Forced split: back the next piece up by a small overlap, whitespace-
        # aligned. First skip the whitespace run at the cut itself (the
        # sentence regex consumes it), otherwise the backtrack lands on `cut`
        # and the overlap silently becomes zero.
        content_end = cut
        while content_end > seg_start and text[content_end - 1].isspace():
            content_end -= 1
        # Aim FORCED_SPLIT_OVERLAP chars back, then align forward to the next
        # word boundary so the overlap is ~the full budget, not one word.
        target = max(seg_start, content_end - FORCED_SPLIT_OVERLAP)
        i = target
        while i < content_end and not text[i].isspace():
            i += 1
        while i < content_end and text[i].isspace():
            i += 1
        seg_start = i if i < content_end else cut
    pieces.append((seg_start, p_end))
    # Trim edge whitespace of every piece so the slice invariant stays tidy.
    trimmed = []
    for s, e in pieces:
        seg = text[s:e]
        s2 = s + (len(seg) - len(seg.lstrip()))
        e2 = s + len(seg.rstrip())
        if e2 > s2:
            trimmed.append((s2, e2))
    return trimmed


def _last_whitespace_before(text: str, before: int, not_before: int) -> int | None:
    """Index just after the last whitespace char in (not_before, before), or None."""
    for i in range(before - 1, not_before, -1):
        if text[i].isspace():
            return i + 1
    return None
