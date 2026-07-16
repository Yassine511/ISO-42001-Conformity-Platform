"""Retention pruning of LLM request prompts (services/llm_retention.py).

SQLite runs with FKs off (see project memory), so call rows are seeded with
synthetic parent ids — the pruner touches only the call tables themselves.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ChatLlmCall, LlmCall, RemediationLlmCall
from app.services.llm_retention import is_pruned, prune_request_messages

PROMPT = [{"role": "user", "content": "texte de politique volumineux"}]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


def _seed_calls(db, started_at: datetime) -> tuple[str, str, str]:
    pipeline = LlmCall(
        assessment_attempt_id=str(uuid.uuid4()),
        call_number=1,
        provider="mistral",
        requested_model="m",
        status="SUCCESS",
        raw_response='{"ok": true}',
        request_messages=list(PROMPT),
        started_at=started_at,
    )
    chat = ChatLlmCall(
        chat_message_id=str(uuid.uuid4()),
        call_number=1,
        draft_attempt_number=1,
        provider="mistral",
        requested_model="m",
        status="SUCCESS",
        raw_response='{"ok": true}',
        request_messages=list(PROMPT),
        started_at=started_at,
    )
    remediation = RemediationLlmCall(
        remediation_attempt_id=str(uuid.uuid4()),
        call_number=1,
        provider="mistral",
        requested_model="m",
        status="SUCCESS",
        raw_response='{"ok": true}',
        request_messages=list(PROMPT),
        started_at=started_at,
    )
    db.add_all([pipeline, chat, remediation])
    db.commit()
    return pipeline.id, chat.id, remediation.id


def test_dry_run_reports_candidates_and_writes_nothing(db):
    old = datetime.now(timezone.utc) - timedelta(days=120)
    ids = _seed_calls(db, old)

    report = prune_request_messages(db, older_than_days=90, apply=False)

    assert report["apply"] is False
    for table in ("llm_calls", "chat_llm_calls", "remediation_llm_calls"):
        assert report["tables"][table] == {"candidates": 1, "pruned": 0}
    db.expire_all()
    for model, row_id in zip((LlmCall, ChatLlmCall, RemediationLlmCall), ids):
        assert db.get(model, row_id).request_messages == PROMPT


def test_apply_prunes_old_calls_only_and_keeps_raw_response(db):
    now = datetime.now(timezone.utc)
    old_ids = _seed_calls(db, now - timedelta(days=120))
    recent_ids = _seed_calls(db, now - timedelta(days=10))

    report = prune_request_messages(db, older_than_days=90, apply=True)

    for table in ("llm_calls", "chat_llm_calls", "remediation_llm_calls"):
        assert report["tables"][table] == {"candidates": 1, "pruned": 1}
    db.expire_all()
    for model, row_id in zip((LlmCall, ChatLlmCall, RemediationLlmCall), old_ids):
        row = db.get(model, row_id)
        assert is_pruned(row.request_messages)
        assert row.request_messages[0]["policy"] == "llm-request-retention-v1"
        # the model's OUTPUT (the trust-chain audit) is never touched
        assert row.raw_response == '{"ok": true}'
    for model, row_id in zip((LlmCall, ChatLlmCall, RemediationLlmCall), recent_ids):
        assert db.get(model, row_id).request_messages == PROMPT


def test_second_apply_is_idempotent(db):
    _seed_calls(db, datetime.now(timezone.utc) - timedelta(days=120))
    prune_request_messages(db, older_than_days=90, apply=True)
    report = prune_request_messages(db, older_than_days=90, apply=True)
    for table in ("llm_calls", "chat_llm_calls", "remediation_llm_calls"):
        assert report["tables"][table] == {"candidates": 0, "pruned": 0}


def test_rejects_zero_retention(db):
    with pytest.raises(ValueError):
        prune_request_messages(db, older_than_days=0, apply=True)
