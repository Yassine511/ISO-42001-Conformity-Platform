"""Shared source-slice derivation (chat M4 + finding review M5).

The UI never renders a model-provided quote as evidence: the authoritative
display text is the raw source characters at the persisted match offsets,
derived fail-closed here. Extracted from app.chat.service so pipeline-finding
review uses the exact same rules.
"""

from app.pipeline.verifier import normalize


def source_slice(
    source: dict, match: dict, model_quote: str | None = None
) -> tuple[str | None, str | None]:
    """Raw source characters at the matched span, FAIL-CLOSED.

    Match offsets are page-relative ([start, end), zero-based raw offsets into
    the page text); the chunk's text is the authoritative page slice
    [char_start:char_end], so the local slice is offset by char_start.

    Returns (slice, None) only when the offsets are in-bounds AND the slice
    normalizes to the same text as the verified model quote (when given) —
    corrupted legacy provenance must yield (None, French error), never a
    plausible-looking wrong slice presented as authoritative."""
    text = source.get("text")
    start, end = match.get("match_start"), match.get("match_end")
    if text is None or start is None or end is None:
        return None, "provenance incomplète : texte source ou offsets manquants."
    base = source.get("char_start") or 0
    local_start, local_end = start - base, end - base
    if not (0 <= local_start < local_end <= len(text)):
        return None, (
            f"offsets de citation invalides : [{start}:{end}) hors des bornes du "
            f"segment source [{base}:{base + len(text)})."
        )
    sliced = text[local_start:local_end]
    if model_quote is not None and normalize(sliced).text != normalize(model_quote).text:
        return None, (
            "incohérence de provenance : la tranche source aux offsets enregistrés "
            "ne correspond pas à la citation vérifiée."
        )
    return sliced, None
