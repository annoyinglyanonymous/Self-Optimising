import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID,JSONB
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.database import Base

class Lead(Base):
    __tablename__="leads"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    company: Mapped[str | None] = mapped_column(String(255))
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    persona: Mapped[str | None] = mapped_column(String(100), index=True)
    company_size: Mapped[str | None] = mapped_column(String(50))
    state: Mapped[str | None] = mapped_column(String(50))
    growth_stage: Mapped[str | None] = mapped_column(String(50))
    tech_stack: Mapped[dict | None] = mapped_column(JSONB)
    raw_enrichment: Mapped[dict | None] = mapped_column(JSONB)
    enrichment_status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    signals: Mapped[list["Signal"]] = relationship(back_populates="lead")
    touches: Mapped[list["Touch"]] = relationship(back_populates="lead")
    events: Mapped[list["Event"]] = relationship(back_populates="lead")
    outcomes: Mapped[list["Outcome"]] = relationship(back_populates="lead")

class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(String(100))
    extradata: Mapped[dict | None] = mapped_column(JSONB)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="signals")

class Touch(Base):
    __tablename__ = "touches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_id: Mapped[str | None] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(50), index=True)
    angle: Mapped[str] = mapped_column(String(100), index=True)
    template_family: Mapped[str | None] = mapped_column(String(100))
    content_version: Mapped[str | None] = mapped_column(String(50))
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(String)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Approval workflow:
    #   "approved"          — sent (or attempted) without human review (default; matches old behavior)
    #   "pending_approval"  — generated; awaiting human review (REQUIRE_APPROVAL=true)
    #   "rejected"          — human declined; will not send
    status: Mapped[str] = mapped_column(String(50), default="approved", nullable=False, index=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lead: Mapped["Lead"] = relationship(back_populates="touches")
    events: Mapped[list["Event"]] = relationship(back_populates="touch")
    
class Event(Base):
    __tablename__ = "events"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    touch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("touches.id", ondelete="SET NULL"), index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    channel: Mapped[str | None] = mapped_column(String(50))
    extradata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    lead: Mapped["Lead"] = relationship(back_populates="events")
    touch: Mapped["Touch"] = relationship(back_populates="events")
class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    touch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("touches.id", ondelete="SET NULL"))
    outcome_type: Mapped[str] = mapped_column(String(100), index=True)
    reward_score: Mapped[float | None] = mapped_column(Float)
    extradata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="outcomes")

class PolicyStat(Base):
    __tablename__ = "policy_stats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    segment_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    persona: Mapped[str | None] = mapped_column(String(100))
    channel: Mapped[str | None] = mapped_column(String(50))
    angle: Mapped[str | None] = mapped_column(String(100))
    trials: Mapped[int] = mapped_column(Integer, default=0)
    successes: Mapped[float] = mapped_column(Float, default=0.0)
    alpha: Mapped[float] = mapped_column(Float, default=1.0)
    beta_param: Mapped[float] = mapped_column(Float, default=1.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class RuleVersion(Base):
    __tablename__ = "rule_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    segment_key: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    old_rule: Mapped[dict | None] = mapped_column(JSONB)
    new_rule: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    trials_at_change: Mapped[int | None] = mapped_column(Integer)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    """Key/value store for app-level settings (active sender backend, sender
    credentials, etc.). Secret values are encrypted in `value`; non-secrets
    are stored plain. The whitelist of accepted keys lives in
    app/services/app_settings.py."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String, default="", nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AccountSuppression(Base):
    __tablename__ = "account_suppression"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(100))
    suppressed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))