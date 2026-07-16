"""M10 backfill: create a user account and attach it to an existing organization.

Pre-M10 organizations ("Lumen AI", "Lumen AI (eval M6)") have no members, so
nobody can reach them through the authenticated UI. This CLI creates (or
reuses) an account and grants it membership — the operator-side counterpart
of the public signup flow, which always creates a NEW organization.

    python scripts/create_user.py --email you@x.fr --name "Vous" --org "Lumen AI"

The password is prompted (never a CLI argument — it would land in the shell
history). Idempotent: an existing user is reused, an existing membership is
reported, nothing is duplicated.
"""

import argparse
import getpass
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="display name")
    parser.add_argument("--org", required=True, help='organization name, e.g. "Lumen AI"')
    args = parser.parse_args()

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Organization, OrganizationMember, User
    from app.services import auth as auth_service

    email = auth_service.normalize_email(args.email)

    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.name == args.org))
        if org is None:
            print(f"Organization not found: {args.org!r}", file=sys.stderr)
            return 1

        user = auth_service.get_user_by_email(db, email)
        if user is None:
            password = getpass.getpass("Password (min 10 chars): ")
            if len(password) < auth_service.MIN_PASSWORD_LENGTH:
                print("Password too short.", file=sys.stderr)
                return 1
            if len(password.encode("utf-8")) > auth_service.MAX_PASSWORD_BYTES:
                print("Password too long (72 bytes max).", file=sys.stderr)
                return 1
            user = User(
                email=email,
                password_hash=auth_service.hash_password(password),
                display_name=args.name,
            )
            db.add(user)
            db.flush()
            print(f"Created user {email}")
        else:
            print(f"User {email} already exists — reusing.")

        membership = db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org.id,
                OrganizationMember.user_id == user.id,
            )
        )
        if membership is None:
            db.add(OrganizationMember(organization_id=org.id, user_id=user.id))
            print(f"Granted membership of {org.name!r}.")
        else:
            print(f"Already a member of {org.name!r} — nothing to do.")
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
