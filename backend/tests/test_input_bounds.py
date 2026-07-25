"""Guard test for audit pass 5 (F4): every client-supplied string that can be
PERSISTED carries a max_length.

Why a guard rather than per-endpoint 422 tests: the columns behind these
fields are unbounded PostgreSQL `Text`, and the remediation notes are also
copied verbatim into `remediation_events.payload` — an append-only table with
no pruning path. A bound that exists on five of six sibling fields is the
failure mode this catches, and it catches it for fields added later too.

The exemptions below are deliberate and each states why. Adding a new
unbounded string field to a request model fails this test.
"""

import inspect
import typing

import pytest
from annotated_types import MaxLen
from pydantic import BaseModel, StringConstraints
from pydantic.fields import FieldInfo

from app import schemas

# (model, field) pairs that intentionally carry no max_length.
EXEMPT: set[tuple[str, str]] = {
    # Password policy (min length, bcrypt's 72-byte cap) is enforced in
    # api/auth.py so the messages reach the UI in French — see the comment
    # above SignupIn. Neither value is ever stored as given: only a bcrypt
    # hash is persisted, and bcrypt reads at most 72 bytes.
    ("SignupIn", "password"),
    ("LoginIn", "password"),
    ("InvitationAcceptIn", "password"),
}

# Request models are the ones a client can POST/PUT a body into; *Out models
# are server-built and not an input surface.
INPUT_SUFFIXES = ("In", "Create", "Body", "Request", "Decision", "Approve", "Review", "Ask")


def _input_models() -> list[type[BaseModel]]:
    models = []
    for name, obj in vars(schemas).items():
        if (
            inspect.isclass(obj)
            and issubclass(obj, BaseModel)
            and obj is not BaseModel
            and name.endswith(INPUT_SUFFIXES)
        ):
            models.append(obj)
    return models


def _is_bound(marker) -> bool:
    """A single annotation marker that caps length. Three shapes occur here:
    `Field(max_length=…)` normalizes to MaxLen, `StringConstraints(…)` keeps
    its own max_length, and both can sit inside a FieldInfo."""
    if isinstance(marker, MaxLen):
        return True
    if isinstance(marker, StringConstraints):
        return marker.max_length is not None
    if isinstance(marker, FieldInfo):
        return any(_is_bound(m) for m in marker.metadata)
    return False


def _has_max_len(annotation, extra_metadata=()) -> bool:
    """True when a length bound is reachable, through Optional[...] /
    Annotated[...] / list[...] nesting as well as the field's own metadata."""
    if any(_is_bound(m) for m in extra_metadata):
        return True
    if any(_is_bound(m) for m in getattr(annotation, "__metadata__", ())):
        return True
    return any(_has_max_len(arg) for arg in typing.get_args(annotation))


def _is_str_field(annotation) -> bool:
    if annotation is str:
        return True
    args = typing.get_args(annotation)
    return bool(args) and any(_is_str_field(a) for a in args)


def test_input_models_were_discovered():
    """A rename that made the discovery pattern match nothing would turn every
    assertion below into a silent pass."""
    names = {m.__name__ for m in _input_models()}
    assert {"SignupIn", "SearchRequest", "ReviewDecision", "RemediationCloseBody"} <= names


@pytest.mark.parametrize("model", _input_models(), ids=lambda m: m.__name__)
def test_every_client_string_field_is_bounded(model):
    for field_name, field in model.model_fields.items():
        if (model.__name__, field_name) in EXEMPT:
            continue
        annotation = field.annotation
        if not _is_str_field(annotation):
            continue
        assert _has_max_len(annotation, field.metadata), (
            f"{model.__name__}.{field_name} is an unbounded client string: it can be "
            f"persisted to a Text column (and, for remediation notes, into the "
            f"append-only remediation_events payload). Add a max_length, or add it "
            f"to EXEMPT in this file with the reason."
        )


def test_id_lists_are_bounded():
    """List-of-id fields are bounded too: create_assessment validates every id
    against the 65-requirement KB, but it has to build the manifest checks over
    whatever list arrived first."""
    for model_name, field_name in (
        ("AssessmentCreate", "requirement_ids"),
        ("RemediationActionReview", "impacted_requirement_ids"),
        ("RemediationReassessmentCreate", "selected_action_ids"),
    ):
        model = getattr(schemas, model_name)
        field = model.model_fields[field_name]
        assert _has_max_len(field.annotation, field.metadata), (
            f"{model_name}.{field_name} is unbounded"
        )


def test_oversized_note_is_rejected():
    """Spot-check that the bound actually rejects, rather than only existing."""
    with pytest.raises(ValueError):
        schemas.RemediationCloseBody(close_note="x" * (schemas.NOTE_MAX + 1))
    with pytest.raises(ValueError):
        schemas.SearchRequest(query="x" * (schemas.SHORT_NOTE_MAX + 1))
    # and that a normal note still passes
    assert schemas.RemediationCloseBody(close_note="Écart traité.").close_note
