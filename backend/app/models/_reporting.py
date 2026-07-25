from app.models._shared import *  # noqa: F401,F403
from app.models._shared import _now, _uuid  # noqa: F401

class SoaDecision(Base):
    """One human applicability decision on one Annex A control — immutable,
    append-only (finding_reviews pattern): rows are never updated or deleted;
    a change appends the next sequence under the ORGANIZATION row lock (the
    only cross-row invariant SQLite tests cannot enforce — validated on the
    dev Postgres concurrency test). soa_controls carries the projection."""

    __tablename__ = "soa_decisions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "control_id", "sequence", name="uq_soa_decisions_sequence"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # a REAL Annex A requirement id (A.2.2 … A.10.4) — SoA is per control,
    # not per domain; validated against the KB by the service
    control_id: Mapped[str] = mapped_column(String(20))
    sequence: Mapped[int] = mapped_column(Integer)  # 1-based per (org, control)
    applicable: Mapped[bool] = mapped_column(Boolean)
    justification_fr: Mapped[str] = mapped_column(Text)
    editor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SoaControl(Base):
    """CURRENT applicability projection of one Annex A control (latest
    decision). Absence of a row = the default: applicable, no justification
    recorded. Applicability ANNOTATES the SoA — it never retroactively
    filters conformity or risk outputs (those stay faithful to the recorded
    findings; non-applicable controls are flagged, not removed)."""

    __tablename__ = "soa_controls"
    __table_args__ = (
        UniqueConstraint("organization_id", "control_id", name="uq_soa_controls_pair"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    control_id: Mapped[str] = mapped_column(String(20))
    applicable: Mapped[bool] = mapped_column(Boolean)
    justification_fr: Mapped[str] = mapped_column(Text)
    editor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decision_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
