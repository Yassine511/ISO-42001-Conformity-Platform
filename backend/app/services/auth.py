"""M10 identity layer — passwords, sessions, invitations.

Design contract (see api/auth.py for the HTTP surface):
- Passwords: bcrypt, used directly (passlib is unmaintained). bcrypt only
  reads the first 72 bytes of input; we reject longer passwords upfront
  rather than silently truncating.
- Sessions: opaque `secrets.token_urlsafe(32)` tokens. The DB stores only
  sha256(token) — a leaked dump cannot be replayed; logout deletes the row;
  expiry is absolute (no sliding refresh).
- Invitations: same hash-only storage; the raw token is returned exactly
  once at creation and lives in the copied URL. Single-use (accepted_at).
- Email normalization (strip + lowercase) happens HERE and only here — the
  UNIQUE(users.email) constraint assumes one canonical form.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuthSession, Invitation, Organization, OrganizationMember, User

# bcrypt hard limit: input beyond 72 bytes is ignored by the algorithm.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 10

INVITATION_TTL = timedelta(days=7)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        # malformed stored hash — treat as authentication failure, not a 500
        return False


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("ascii")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    # SQLite loses tzinfo on DateTime(timezone=True); Postgres keeps it.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def create_session(db: Session, user: User) -> str:
    """Create a session row and return the RAW token (cookie value)."""
    raw_token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=_now() + timedelta(hours=settings.session_ttl_hours),
        )
    )
    return raw_token


def resolve_session(db: Session, raw_token: str) -> User | None:
    """Raw cookie token -> User, or None if unknown/expired."""
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == _hash_token(raw_token))
    )
    if session is None or _as_utc(session.expires_at) <= _now():
        return None
    return db.get(User, session.user_id)


def revoke_session(db: Session, raw_token: str) -> None:
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == _hash_token(raw_token))
    )
    if session is not None:
        db.delete(session)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def is_member(db: Session, user_id: str, organization_id: str) -> bool:
    return (
        db.scalar(
            select(OrganizationMember.id).where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == organization_id,
            )
        )
        is not None
    )


def user_organizations(db: Session, user_id: str) -> list[Organization]:
    return list(
        db.scalars(
            select(Organization)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.created_at)
        )
    )


def create_invitation(
    db: Session, organization_id: str, email: str, created_by: User
) -> tuple[Invitation, str]:
    """Create an invitation and return (row, RAW token) — the raw token is
    shown exactly once; only its hash is stored."""
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(
        organization_id=organization_id,
        email=normalize_email(email),
        token_hash=_hash_token(raw_token),
        created_by_user_id=created_by.id,
        expires_at=_now() + INVITATION_TTL,
    )
    db.add(invitation)
    return invitation, raw_token


def get_invitation_by_token(db: Session, raw_token: str) -> Invitation | None:
    return db.scalar(
        select(Invitation).where(Invitation.token_hash == _hash_token(raw_token))
    )


def invitation_expired(invitation: Invitation) -> bool:
    return _as_utc(invitation.expires_at) <= _now()
