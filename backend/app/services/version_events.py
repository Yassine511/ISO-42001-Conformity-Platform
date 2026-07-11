"""Append-only document-version event stream (M7b).

Generic version lifecycle (upload, indexing, activation, recovery) — separate
from case-scoped remediation_events, which cannot host caseless superseding
uploads. LOCKING RULE: sequence is assigned under the DOCUMENT row lock, and
rows are appended only from transactions already holding that lock in the
declared order (org [-> case] -> document -> versions). `version_indexed` is
recorded in the locked activation/recovery transaction AFTER Qdrant success
was observed, never from the lock-free indexing step itself.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DOCUMENT_VERSION_EVENT_TYPES, DocumentVersionEvent


def append_version_event(
    db: Session,
    document_id: str,
    event_type: str,
    payload: dict,
    actor_label: str | None = None,
) -> DocumentVersionEvent:
    """Caller MUST hold the document row lock (upload creation is exempt: a
    brand-new document row is invisible to concurrent writers). Flushes; the
    caller commits."""
    if event_type not in DOCUMENT_VERSION_EVENT_TYPES:
        raise ValueError(f"unknown document version event type: {event_type}")
    last = db.scalar(
        select(DocumentVersionEvent.sequence)
        .where(DocumentVersionEvent.document_id == document_id)
        .order_by(DocumentVersionEvent.sequence.desc())
        .limit(1)
    )
    event = DocumentVersionEvent(
        document_id=document_id,
        sequence=(last or 0) + 1,
        event_type=event_type,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )
    event.actor_label = actor_label
    db.add(event)
    db.flush()
    return event
