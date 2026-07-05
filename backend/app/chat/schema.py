"""Claim-bound chat draft schema (M4).

The grounding contract for chat: the answer is NOT free prose with a detached
citation list — it is a list of claims, each bound to the citations that
support it. Verification strips citations; a claim survives only if EVERY
citation it references verified, and the returned answer is assembled
server-side from surviving claims. Prose whose support failed never reaches
the user.

Same strict-Pydantic-gate pattern as pipeline DraftFinding (strict=True,
extra="forbid", bounds matched to DB columns): the provider's JSON mode only
shapes the response; this module validates it. Contextual rules that need the
retrieved evidence (retrieval_notes coverage) live in service._parse_chat_draft.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=8)  # e.g. "c1", referenced by claims
    type: Literal["policy", "kb"]
    # max_length mirrors verifier.MAX_QUOTE_LEN / findings cap
    policy_quote: str | None = Field(default=None, max_length=300)
    # max_length mirrors the VARCHAR(20) clause columns
    clause_ref: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _shape_by_type(self) -> "ChatCitation":
        if self.type == "policy":
            if not (self.policy_quote or "").strip():
                raise ValueError(
                    f"citation « {self.id} » de type policy : policy_quote est obligatoire"
                )
            if self.clause_ref is not None:
                raise ValueError(
                    f"citation « {self.id} » de type policy : clause_ref doit être null"
                )
        else:  # kb
            if not (self.clause_ref or "").strip():
                raise ValueError(
                    f"citation « {self.id} » de type kb : clause_ref est obligatoire"
                )
            if self.policy_quote is not None:
                raise ValueError(
                    f"citation « {self.id} » de type kb : policy_quote doit être null"
                )
        return self


class ChatClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # ONE assertion; the prompt requires mixed statements split into two claims
    text: str = Field(min_length=1, max_length=1000)
    # organization = asserts YOUR documentary coverage (needs a policy citation)
    # standard     = describes what ISO 42001 requires (needs a KB citation)
    kind: Literal["organization", "standard"]
    citation_ids: list[str] = Field(min_length=1, max_length=4)


class RetrievalNote(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    result_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=300)


class ChatDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claims: list[ChatClaim] = Field(max_length=8)
    no_evidence: bool  # explicit in-schema abstention (mirrors verdict=missing)
    citations: list[ChatCitation] = Field(max_length=10)
    # no_evidence path only: per-passage reasons the displayed passages don't
    # qualify (spec §7 "shows its work"). Coverage against the actually
    # displayed passages is enforced contextually in service._parse_chat_draft.
    retrieval_notes: list[RetrievalNote] | None = None

    @model_validator(mode="after")
    def _cross_checks(self) -> "ChatDraft":
        ids = [c.id for c in self.citations]
        if len(ids) != len(set(ids)):
            raise ValueError("identifiants de citation dupliqués")
        by_id = {c.id: c for c in self.citations}
        for i, claim in enumerate(self.claims, start=1):
            if len(claim.citation_ids) != len(set(claim.citation_ids)):
                raise ValueError(f"claim {i} : citation_ids dupliqués")
            unknown = [cid for cid in claim.citation_ids if cid not in by_id]
            if unknown:
                raise ValueError(
                    f"claim {i} : citation_ids inconnus {unknown} — chaque id doit "
                    "correspondre à une citation déclarée"
                )
            kinds = {by_id[cid].type for cid in claim.citation_ids}
            # kind/citation coherence: an organization claim must rest on at
            # least one policy extract; a standard claim on at least one KB id
            if claim.kind == "organization" and "policy" not in kinds:
                raise ValueError(
                    f"claim {i} (organization) : doit citer au moins une citation "
                    "de type policy — une référence KB seule ne prouve pas la "
                    "couverture documentaire de l'organisation"
                )
            if claim.kind == "standard" and "kb" not in kinds:
                raise ValueError(
                    f"claim {i} (standard) : doit citer au moins une citation de type kb"
                )
        if self.retrieval_notes is not None:
            note_ids = [n.result_id for n in self.retrieval_notes]
            if len(note_ids) != len(set(note_ids)):
                raise ValueError("retrieval_notes : result_id dupliqués")
        return self
