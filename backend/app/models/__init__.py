"""SQLAlchemy models — a package, not a module.

Every submodule is imported here and its public names re-exported, so
`from app.models import Finding` (and `from app import models` in
alembic/env.py, which relies on the import populating Base.metadata) behave
exactly as they did when this was a single file. Submodules are private
(`_name`) precisely so nobody imports one directly and bypasses this file.

Grouping follows the milestone boundaries the file already used:
  _documents    organizations, documents, versions, pages, chunks (M1/M2/M7b)
  _pipeline     assessments, findings, reviews, attempts, llm calls (M3)
  _chat         conversations, messages, chat llm calls (M4)
  _remediation  cases, triage, plans, actions, events, patches, artifacts (M7)
  _reporting    Statement of Applicability decisions and projection (M8)
  _auth         users, memberships, sessions, invitations (M10)

Keep the __all__ below in sync when adding a model — the drift test
tests/test_models_package.py fails if a class is reachable in a submodule but
not exported here.
"""

from app.models._documents import (  # noqa: F401
    CANONICAL_FORMATS,
    CHUNK_ID_SCHEMES,
    Chunk,
    DOCUMENT_VERSION_STATES,
    Document,
    DocumentPage,
    DocumentStatus,
    DocumentVersion,
    Organization,
    VERSION_ABANDONED_REASONS,
)
from app.models._pipeline import (  # noqa: F401
    Assessment,
    AssessmentAttempt,
    Finding,
    FindingReview,
    LlmCall,
)
from app.models._chat import (  # noqa: F401
    ChatLlmCall,
    ChatMessage,
    Conversation,
)
from app.models._remediation import (  # noqa: F401
    DOCUMENT_VERSION_EVENT_TYPES,
    DocumentVersionEvent,
    PATCH_ABSTAIN_REASONS,
    PatchDecision,
    PatchProposal,
    REMEDIATION_ABSTAIN_REASONS,
    REMEDIATION_EVENT_TYPES,
    RemediationAction,
    RemediationActionRequirement,
    RemediationArtifact,
    RemediationAttempt,
    RemediationCase,
    RemediationCaseFinding,
    RemediationEvent,
    RemediationLlmCall,
    RemediationPlan,
    RemediationReassessment,
    RemediationTriageDraft,
)
from app.models._reporting import (  # noqa: F401
    SoaControl,
    SoaDecision,
)
from app.models._auth import (  # noqa: F401
    AuthSession,
    Invitation,
    OrganizationMember,
    User,
)

__all__ = [
    "Assessment",
    "AssessmentAttempt",
    "AuthSession",
    "CANONICAL_FORMATS",
    "CHUNK_ID_SCHEMES",
    "ChatLlmCall",
    "ChatMessage",
    "Chunk",
    "Conversation",
    "DOCUMENT_VERSION_EVENT_TYPES",
    "DOCUMENT_VERSION_STATES",
    "Document",
    "DocumentPage",
    "DocumentStatus",
    "DocumentVersion",
    "DocumentVersionEvent",
    "Finding",
    "FindingReview",
    "Invitation",
    "LlmCall",
    "Organization",
    "OrganizationMember",
    "PATCH_ABSTAIN_REASONS",
    "PatchDecision",
    "PatchProposal",
    "REMEDIATION_ABSTAIN_REASONS",
    "REMEDIATION_EVENT_TYPES",
    "RemediationAction",
    "RemediationActionRequirement",
    "RemediationArtifact",
    "RemediationAttempt",
    "RemediationCase",
    "RemediationCaseFinding",
    "RemediationEvent",
    "RemediationLlmCall",
    "RemediationPlan",
    "RemediationReassessment",
    "RemediationTriageDraft",
    "SoaControl",
    "SoaDecision",
    "User",
    "VERSION_ABANDONED_REASONS",
]
