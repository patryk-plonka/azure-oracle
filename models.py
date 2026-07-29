from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    limitations: Mapped[list[Limitation]] = relationship(back_populates="source")


class Limitation(Base):
    __tablename__ = "limitations"
    __table_args__ = (
        CheckConstraint("btrim(quote) <> ''", name="ck_limitations_quote_not_blank"),
        CheckConstraint("btrim(confidence) <> ''", name="ck_limitations_confidence_not_blank"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    service: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    feature: Mapped[str | None] = mapped_column(Text)
    support_status: Mapped[str] = mapped_column(String(64), nullable=False)
    limitation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    condition: Mapped[str | None] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(String(255))
    region: Mapped[str | None] = mapped_column(String(255))
    sku_tier: Mapped[str | None] = mapped_column(String(255))
    auth_mode: Mapped[str | None] = mapped_column(String(255))
    network_mode: Mapped[str | None] = mapped_column(String(255))
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    workaround: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    first_seen: Mapped[date | None] = mapped_column(Date)
    last_seen: Mapped[date | None] = mapped_column(Date)
    verification_state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[Source] = relationship(back_populates="limitations")