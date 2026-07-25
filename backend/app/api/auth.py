"""M10 auth endpoints — signup (creates the organization), login, logout,
me, and the invite-by-link flow.

Cookie contract: `int102_session`, httpOnly, SameSite=Lax (a cross-site POST
never carries it — the CSRF mitigation for this same-origin deployment),
Secure per settings. The value is the raw opaque token; the DB knows only
its sha256 (services/auth.py).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, get_current_user, require_org_member
from app.config import settings
from app.db import get_db
from app.models import Invitation, Organization, OrganizationMember, User
from app.schemas import (
    InvitationAcceptIn,
    InvitationCreatedOut,
    InvitationCreateIn,
    InvitationOut,
    InvitationPublicOut,
    LoginIn,
    OrganizationMemberOut,
    SessionOut,
    SignupIn,
)
from app.services import auth as auth_service
from app.services import run_guard
from app.services.rate_limit import client_ip, login_limiter, signup_limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Org-scoped invite creation lives with the other /api/organizations/{org_id}
# routes so the membership guard applies the same way.
org_router = APIRouter(
    prefix="/api/organizations/{org_id}",
    tags=["auth"],
    dependencies=[Depends(require_org_member)],
)


def _validate_password(password: str) -> None:
    if len(password) < auth_service.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            422,
            f"Le mot de passe doit contenir au moins {auth_service.MIN_PASSWORD_LENGTH} caractères.",
        )
    if len(password.encode("utf-8")) > auth_service.MAX_PASSWORD_BYTES:
        raise HTTPException(422, "Le mot de passe est trop long (72 octets maximum).")


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def _session_body(db: Session, user: User) -> SessionOut:
    return SessionOut.model_validate(
        {
            "user": user,
            "organizations": auth_service.user_organizations(db, user.id),
        },
        from_attributes=True,
    )


@router.post("/signup", response_model=SessionOut, status_code=201)
def signup(
    payload: SignupIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    # The 409 below necessarily discloses that an address is taken (with no
    # e-mail server, signup either creates the account or refuses). Throttling
    # bounds how often that question can be asked; it does not remove the
    # disclosure — see services/rate_limit and the README.
    _throttle(signup_limiter, request, payload.email)
    _validate_password(payload.password)
    email = auth_service.normalize_email(payload.email)
    if "@" not in email:
        raise HTTPException(422, "Adresse e-mail invalide.")
    if auth_service.get_user_by_email(db, email):
        raise HTTPException(409, "Un compte existe déjà avec cette adresse e-mail.")
    existing_org = db.query(Organization).filter_by(name=payload.organization_name).first()
    if existing_org:
        raise HTTPException(409, "Une organisation portant ce nom existe déjà.")

    user = User(
        email=email,
        password_hash=auth_service.hash_password(payload.password),
        display_name=payload.display_name,
    )
    org = Organization(name=payload.organization_name)
    db.add_all([user, org])
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id))
    raw_token = auth_service.create_session(db, user)
    try:
        db.commit()
    except IntegrityError:
        # concurrent duplicate slipped past the pre-checks; the UNIQUE
        # constraints (users.email, organizations.name) are the atomic gate
        db.rollback()
        raise HTTPException(409, "Adresse e-mail ou nom d'organisation déjà utilisés.")
    _set_session_cookie(response, raw_token)
    return _session_body(db, user)


def _throttle(limiter, request: Request, identifier: str) -> None:
    """Refuse the call with 429 when the (identifier, IP) window is exhausted.
    Keyed on both halves — see services/rate_limit.client_ip for why the IP
    alone is not trustworthy and the identifier alone is not fair."""
    retry_after = limiter.hit(auth_service.normalize_email(identifier), client_ip(request))
    if retry_after > 0:
        raise HTTPException(
            429,
            "Trop de tentatives. Réessayez dans "
            f"{int(retry_after // 60) + 1} minute(s).",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


@router.post("/login", response_model=SessionOut)
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _throttle(login_limiter, request, payload.email)
    user = auth_service.get_user_by_email(db, payload.email)
    # Generic message for unknown email AND wrong password — and the same COST:
    # skipping bcrypt on the unknown-address branch would answer ~100× faster
    # and turn the identical 401 into a timing enumeration oracle.
    if user is None:
        auth_service.waste_password_comparison()
        raise HTTPException(401, "Identifiants invalides.")
    if not auth_service.verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Identifiants invalides.")
    # authenticated: forget the window so a person who eventually remembers
    # their password is not still throttled by their own failed attempts
    login_limiter.reset(auth_service.normalize_email(payload.email), client_ip(request))
    raw_token = auth_service.create_session(db, user)
    db.commit()
    _set_session_cookie(response, raw_token)
    return _session_body(db, user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        auth_service.revoke_session(db, raw_token)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=SessionOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _session_body(db, user)


@router.get("/invitations/{token}", response_model=InvitationPublicOut)
def invitation_info(token: str, db: Session = Depends(get_db)):
    """Public metadata for the accept page. Looked up by hash; an unknown or
    already-accepted token is a plain 404."""
    invitation = auth_service.get_invitation_by_token(db, token)
    if invitation is None or invitation.accepted_at is not None:
        raise HTTPException(404, "Invitation introuvable ou déjà utilisée.")
    org = db.get(Organization, invitation.organization_id)
    return InvitationPublicOut(
        organization_name=org.name if org else "",
        email=invitation.email,
        expired=auth_service.invitation_expired(invitation),
        account_exists=auth_service.get_user_by_email(db, invitation.email) is not None,
    )


@router.post("/invitations/{token}/accept", response_model=SessionOut, status_code=201)
def accept_invitation(
    token: str,
    payload: InvitationAcceptIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Join the inviting organization.

    Two paths, chosen by whether the invited address already has an account:
    - NEW account: `password` becomes the account's password, `display_name`
      is required, user + membership are created.
    - EXISTING account: `password` AUTHENTICATES that account (it is a login,
      never a password change) and only the membership is added — this is what
      lets an existing user join a second organization.

    Authentication happens BEFORE any write: a wrong password must never
    consume the single-use invitation.
    """
    invitation = auth_service.get_invitation_by_token(db, token)
    if invitation is None or invitation.accepted_at is not None:
        raise HTTPException(404, "Invitation introuvable ou déjà utilisée.")
    if auth_service.invitation_expired(invitation):
        raise HTTPException(410, "Cette invitation a expiré.")

    existing = auth_service.get_user_by_email(db, invitation.email)
    if existing is not None:
        # ---- existing account: authenticate FIRST, write nothing on failure
        # This branch checks a password, so it is throttled exactly like login:
        # the invitation is single-use but survives a wrong password, which
        # would otherwise make it an unlimited guessing surface for the one
        # address it names.
        _throttle(login_limiter, request, invitation.email)
        if not auth_service.verify_password(payload.password, existing.password_hash):
            raise HTTPException(
                401,
                "Mot de passe invalide pour ce compte. L'invitation reste "
                "valide : réessayez.",
            )
        login_limiter.reset(invitation.email, client_ip(request))
        user = existing
        if not auth_service.is_member(db, user.id, invitation.organization_id):
            auth_service.add_membership(db, user.id, invitation.organization_id)
    else:
        # ---- new account
        _validate_password(payload.password)
        if not (payload.display_name or "").strip():
            raise HTTPException(422, "Votre nom est obligatoire.")
        user = User(
            email=invitation.email,
            password_hash=auth_service.hash_password(payload.password),
            display_name=payload.display_name.strip(),
        )
        db.add(user)
        db.flush()
        auth_service.add_membership(db, user.id, invitation.organization_id)

    invitation.accepted_at = auth_service._now()
    invitation.accepted_by_user_id = user.id
    raw_token = auth_service.create_session(db, user)
    try:
        db.commit()
    except IntegrityError:
        # Concurrency backstop — no row lock is taken on the invitation because
        # the UNIQUE constraints already decide every race:
        #  - two accepts creating the account: UNIQUE(users.email) fails one;
        #  - two accepts joining an existing account: uq_org_members_pair fails
        #    one (both stamped accepted_at, but the loser's whole tx rolls back);
        #  - accepting when already a member: no membership INSERT at all, both
        #    just consume the token — idempotent, nothing to protect.
        db.rollback()
        raise HTTPException(409, "Cette invitation vient d'être utilisée.")
    _set_session_cookie(response, raw_token)
    return _session_body(db, user)


# ------------------------------------------------------- members & invitations
# Every member is equal by design (organization_members has no role column), so
# any member may invite and remove any other — including themselves. The one
# hard rule is the last-member guard in remove_member.


@org_router.post("/invitations", response_model=InvitationCreatedOut, status_code=201)
def create_invitation(
    org_id: str,
    payload: InvitationCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a single-use invite link. An address that already has an
    account is invited normally — it joins by authenticating at accept time."""
    email = auth_service.normalize_email(payload.email)
    if "@" not in email:
        raise HTTPException(422, "Adresse e-mail invalide.")
    # Serialize concurrent creates on the org row (SQLite no-op, real on PG —
    # run_guard pattern): the duplicate-live-invitation check below has no
    # UNIQUE backstop, so without the lock two simultaneous requests could both
    # pass it and mint two live tokens for one seat.
    run_guard.lock_organization(db, org_id)
    invitee = auth_service.get_user_by_email(db, email)
    if invitee is not None and auth_service.is_member(db, invitee.id, org_id):
        raise HTTPException(409, "Cette personne est déjà membre de l'organisation.")
    if auth_service.live_invitation(db, org_id, email) is not None:
        raise HTTPException(
            409,
            "Une invitation est déjà en cours pour cette adresse. Révoquez-la "
            "avant d'en générer une nouvelle.",
        )
    invitation, raw_token = auth_service.create_invitation(db, org_id, email, user)
    db.commit()
    return InvitationCreatedOut(
        invite_token=raw_token, email=invitation.email, expires_at=invitation.expires_at
    )


@org_router.get("/invitations", response_model=list[InvitationOut])
def list_invitations(org_id: str, db: Session = Depends(get_db)):
    return [
        InvitationOut(
            id=inv.id,
            email=inv.email,
            created_at=inv.created_at,
            expires_at=inv.expires_at,
            expired=auth_service.invitation_expired(inv),
        )
        for inv in auth_service.pending_invitations(db, org_id)
    ]


@org_router.delete("/invitations/{invitation_id}", status_code=204)
def revoke_invitation(org_id: str, invitation_id: str, db: Session = Depends(get_db)):
    """Revoke a PENDING invitation — the link stops working immediately. An
    ACCEPTED invitation is the record of how a member got their access and is
    never deleted (404, indistinguishable from an unknown id)."""
    invitation = db.get(Invitation, invitation_id)
    if (
        invitation is None
        or invitation.organization_id != org_id
        or invitation.accepted_at is not None
    ):
        raise HTTPException(404, "Invitation introuvable.")
    db.delete(invitation)
    db.commit()


@org_router.get("/members", response_model=list[OrganizationMemberOut])
def list_members(
    org_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [
        OrganizationMemberOut(
            user_id=member.id,
            email=member.email,
            display_name=member.display_name,
            joined_at=joined_at,
            is_self=member.id == user.id,
        )
        for member, joined_at in auth_service.organization_members(db, org_id)
    ]


@org_router.delete("/members/{user_id}", status_code=204)
def remove_member(org_id: str, user_id: str, db: Session = Depends(get_db)):
    """Remove a member — or leave, by passing your own id.

    The LAST member can never be removed: there is no org-delete endpoint and
    no way to add a member to an organization nobody belongs to, so an org at
    zero members would be permanently unreachable data.

    Sessions are global rather than org-scoped, so nothing is revoked here: the
    removed user simply fails `require_org_member` on their next request to
    this organization.
    """
    # Serialize concurrent removals on the org row (SQLite no-op, real on PG —
    # run_guard pattern): without it, two requests removing the two remaining
    # members could each count 2 and both delete, stranding the org at zero.
    run_guard.lock_organization(db, org_id)
    membership = auth_service.get_membership(db, user_id, org_id)
    if membership is None:
        raise HTTPException(404, "Membre introuvable dans cette organisation.")
    if auth_service.member_count(db, org_id) <= 1:
        raise HTTPException(
            409,
            "Impossible de retirer le dernier membre : l'organisation et ses "
            "données deviendraient inaccessibles. Invitez d'abord quelqu'un d'autre.",
        )
    db.delete(membership)
    db.commit()
