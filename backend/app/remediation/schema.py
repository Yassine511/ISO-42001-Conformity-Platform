"""Strict Pydantic gates for the remediation agent's LLM outputs (M7a).

Same pattern as pipeline DraftFinding / chat ChatDraft: strict=True,
extra="forbid", bounds matched to DB columns. The provider's JSON mode only
shapes the response; these models validate it. Contextual rules that need
server data (requirement binding against allowed_requirement_ids, quote
binding against the retrieved evidence) live in triage.py / planner.py —
the schema alone can never prove grounding.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Classification = Literal[
    "evidence_gap", "observation", "improvement_opportunity", "nonconformity"
]
Scope = Literal["local", "related_requirements", "organization_wide"]
ActionType = Literal[
    "document_amendment",
    "new_document",
    "process_change",
    "training",
    "risk_treatment_update",
    "other",
]


class TriageDraft(BaseModel):
    """AI triage proposal — always human-approved/overridden before use."""

    model_config = ConfigDict(extra="forbid", strict=True)

    classification: Classification
    # immediate correction + consequence handling (ISO 10.2 a)
    correction_note: str = Field(min_length=1, max_length=2000)
    scope: Scope
    scope_rationale: str = Field(min_length=1, max_length=2000)


class RootCauseHypothesis(BaseModel):
    """LABELED hypothesis (spec §8) — never presented as established fact."""

    model_config = ConfigDict(extra="forbid", strict=True)

    label: str = Field(min_length=1, max_length=100)  # e.g. "H1"
    hypothesis: str = Field(min_length=1, max_length=1000)


class ActionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action_type: ActionType
    description: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=2000)
    # suggested owner ROLE, never a person (no identity layer)
    owner_role: str = Field(min_length=1, max_length=200)
    # verifiable completion criterion
    success_criterion: str = Field(min_length=1, max_length=1000)
    # must be a subset of the server-owned allowed_requirement_ids
    # (checked contextually in planner.py — requirement binding)
    impacted_requirement_ids: list[str] = Field(min_length=1, max_length=10)
    # optional supporting quote; source binding checked in planner.py
    policy_quote: str | None = Field(default=None, max_length=300)
    quote_source_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _checks(self) -> "ActionDraft":
        if len(self.impacted_requirement_ids) != len(set(self.impacted_requirement_ids)):
            raise ValueError("impacted_requirement_ids : identifiants dupliqués")
        for rid in self.impacted_requirement_ids:
            if not rid.strip() or len(rid) > 20:
                raise ValueError(f"impacted_requirement_ids : identifiant invalide « {rid} »")
        # both-or-neither: a quote without its claimed source (or vice versa)
        # is unverifiable and rejected at the schema gate
        has_quote = bool((self.policy_quote or "").strip())
        has_source = bool((self.quote_source_id or "").strip())
        if has_quote != has_source:
            raise ValueError(
                "policy_quote et quote_source_id doivent être fournis ensemble "
                "ou tous deux null"
            )
        if not has_quote:
            # normalize empty strings to None so persistence sees one shape
            object.__setattr__(self, "policy_quote", None)
            object.__setattr__(self, "quote_source_id", None)
        return self


class PatchDraft(BaseModel):
    """AI anchored-patch proposal (M7b). The anchor must be copied VERBATIM
    from the served page text: location verification is raw literal equality
    (services/anchors.py) requiring exactly one occurrence — checked
    contextually in patcher.py, never here. TXT/MD parse to a single page, so
    anchor_page must be 1 (also enforced in the verifier for a typed error)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    anchor_quote: str = Field(min_length=20, max_length=500)
    anchor_page: int = Field(ge=1)
    operation: Literal["insert_after", "replace"]
    new_text_fr: str = Field(min_length=1, max_length=8000)
    rationale: str = Field(min_length=1, max_length=2000)


class ArtifactDraft(BaseModel):
    """AI Markdown revision proposal for a PDF/DOCX target (M7b). Never a
    document version — a clearly labelled draft a human may use when
    preparing the real revised file for a superseding upload."""

    model_config = ConfigDict(extra="forbid", strict=True)

    content_md: str = Field(min_length=1, max_length=20000)
    rationale: str = Field(min_length=1, max_length=2000)


class PlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    gap_restatement: str = Field(min_length=1, max_length=4000)
    root_cause_hypotheses: list[RootCauseHypothesis] = Field(min_length=1, max_length=5)
    actions: list[ActionDraft] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def _checks(self) -> "PlanDraft":
        labels = [h.label for h in self.root_cause_hypotheses]
        if len(labels) != len(set(labels)):
            raise ValueError("root_cause_hypotheses : labels dupliqués")
        return self
