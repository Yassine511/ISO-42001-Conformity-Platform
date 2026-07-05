"""Backfill chat_messages.claims: rename per-claim key `verified` -> `citations_verified`.

Commit ad46dbe renamed the claim flag (honest citation-location semantics) but
left previously persisted claims untouched: ChatClaimOut then rejects legacy
rows on replay (5 missing-field validation errors reproduced live). This data
migration makes persisted rows uniform; api/chat.message_to_out additionally
normalizes at serialization time as a belt for non-migrated stores (sqlite
dev/test databases are created fresh by create_all and never carry legacy rows).

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-05
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _rename_key(claims: list, old: str, new: str) -> tuple[list, bool]:
    changed = False
    out = []
    for claim in claims:
        if isinstance(claim, dict) and old in claim and new not in claim:
            claim = {**{k: v for k, v in claim.items() if k != old}, new: claim[old]}
            changed = True
        out.append(claim)
    return out, changed


def _migrate(old: str, new: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, claims FROM chat_messages")).fetchall()
    for row_id, claims in rows:
        if isinstance(claims, str):  # driver without native JSON decoding
            claims = json.loads(claims)
        if not claims:
            continue
        migrated, changed = _rename_key(claims, old, new)
        if changed:
            bind.execute(
                sa.text("UPDATE chat_messages SET claims = :claims WHERE id = :id"),
                {"claims": json.dumps(migrated, ensure_ascii=False), "id": row_id},
            )


def upgrade() -> None:
    _migrate("verified", "citations_verified")


def downgrade() -> None:
    _migrate("citations_verified", "verified")
