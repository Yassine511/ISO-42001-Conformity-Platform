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
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuthSession, Invitation, Organization, OrganizationMember, User

# bcrypt hard limit: input beyond 72 bytes is ignored by the algorithm.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 10

INVITATION_TTL = timedelta(days=7)

# Fixed, valid bcrypt hash of an unguessable value, used ONLY to burn the same
# ~100 ms an authentic verification costs when the e-mail is unknown. Without
# it, "unknown address" answers measurably faster than "wrong password" and the
# 401 becomes an account-enumeration oracle. Literal, not computed at import:
# hashing at startup would cost the same time on every process boot for nothing.
_DUMMY_PASSWORD_HASH = "$2b$12$QoaDhUCv7rAUzixB4DZXuubBrampjTjtyWSgEQWOwlH/JU32tzJgi"


def waste_password_comparison() -> None:
    """Run one full bcrypt verification against the dummy hash. Called on the
    unknown-e-mail branch of login so both outcomes cost the same."""
    verify_password("", _DUMMY_PASSWORD_HASH)


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
    """sha256 of a token candidate, for ANY string a client can send.

    The value is attacker-controlled: it arrives in the `int102_session`
    cookie (Starlette decodes headers as latin-1) or in an invitation URL
    path (percent-decoded as UTF-8), so it can contain any character.
    `.encode("ascii")` raised UnicodeEncodeError on the first byte >= 0x7F,
    which was unhandled and turned every authenticated route — and both
    unauthenticated invitation routes — into a 500 for that caller.

    UTF-8 never raises, and every token we mint is `secrets.token_urlsafe`
    (ASCII only), for which UTF-8 and ASCII produce identical bytes: no
    stored hash changes. A non-ASCII candidate simply hashes to something no
    row holds and falls through the normal not-found path (401 / 404).
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    # SQLite loses tzinfo on DateTime(timezone=True); Postgres keeps it.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def create_session(db: Session, user: User) -> str:
    """Create a session row and return the RAW token (cookie value).

    Also drops this user's already-expired rows: they are dead weight (expiry
    is absolute, so an expired row can never authenticate again) and a token
    that is never presented again would otherwise be pruned by nothing. Bounded
    to one user, in the transaction the caller is already committing.
    """
    raw_token = secrets.token_urlsafe(32)
    db.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user.id, AuthSession.expires_at <= _now()
        )
    )
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=_now() + timedelta(hours=settings.session_ttl_hours),
        )
    )
    return raw_token


def resolve_session(db: Session, raw_token: str) -> User | None:
    """Raw cookie token -> User, or None if unknown/expired.

    Expired rows are deleted opportunistically here: sessions are only ever
    looked up by token hash, so a row nobody presents again is unreachable —
    this reclaims the ones that ARE presented (the common case: a browser
    holding a cookie past its absolute 7-day expiry) without a cron job.
    Deletion is best-effort; a failure must never break authentication.
    """
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == _hash_token(raw_token))
    )
    if session is None:
        return None
    if _as_utc(session.expires_at) <= _now():
        try:
            db.delete(session)
            db.commit()
        except Exception:
            db.rollback()
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


def organization_members(db: Session, organization_id: str) -> list[tuple[User, datetime]]:
    """(user, joined_at) for every member, oldest first."""
    return [
        (user, joined_at)
        for user, joined_at in db.execute(
            select(User, OrganizationMember.created_at)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == organization_id)
            .order_by(OrganizationMember.created_at)
        )
    ]


def member_count(db: Session, organization_id: str) -> int:
    return db.scalar(
        select(func.count())
        .select_from(OrganizationMember)
        .where(OrganizationMember.organization_id == organization_id)
    )


def get_membership(
    db: Session, user_id: str, organization_id: str
) -> OrganizationMember | None:
    return db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == organization_id,
        )
    )


def add_membership(db: Session, user_id: str, organization_id: str) -> OrganizationMember:
    membership = OrganizationMember(organization_id=organization_id, user_id=user_id)
    db.add(membership)
    return membership


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


def live_invitation(db: Session, organization_id: str, email: str) -> Invitation | None:
    """An outstanding invitation for this (org, email): unaccepted and not yet
    expired. Used to refuse a duplicate invite — two live tokens for one seat
    means revoking one leaves the other usable."""
    for invitation in db.scalars(
        select(Invitation).where(
            Invitation.organization_id == organization_id,
            Invitation.email == normalize_email(email),
            Invitation.accepted_at.is_(None),
        )
    ):
        if not invitation_expired(invitation):
            return invitation
    return None


def pending_invitations(db: Session, organization_id: str) -> list[Invitation]:
    """Unaccepted invitations, newest first. Raw tokens are NOT recoverable —
    only their hash was ever stored — so this lists metadata for revocation,
    never a re-displayable link."""
    return list(
        db.scalars(
            select(Invitation)
            .where(
                Invitation.organization_id == organization_id,
                Invitation.accepted_at.is_(None),
            )
            .order_by(Invitation.created_at.desc())
        )
    )
