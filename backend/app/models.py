from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Naive UTC. Everything in the DB is stored in UTC without a tzinfo,
    because SQLite does not round-trip offsets. Convert at the edges only."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class Base(DeclarativeBase):
    pass


class DayType(str, enum.Enum):
    """An explicit mark on a calendar day. Absence of a mark means the default
    applies: Mon-Fri is a workday, Sat/Sun is off."""

    WORKDAY = "workday"
    HALF_DAY = "half_day"
    VACATION = "vacation"
    SICK = "sick"
    HOLIDAY = "holiday"
    OFF = "off"


#: Day types that carry no target hours.
ZERO_TARGET_TYPES = {DayType.VACATION, DayType.SICK, DayType.HOLIDAY, DayType.OFF}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(128), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    nominal_rates: Mapped[list[NominalRate]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by="NominalRate.effective_from"
    )


class NominalRate(Base):
    """Nominal working minutes per full workday, valid from `effective_from`
    onwards until superseded. Keeping history is what makes past days retain
    the target they were originally judged against."""

    __tablename__ = "nominal_rates"
    __table_args__ = (UniqueConstraint("user_id", "effective_from", name="uq_nominal_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="nominal_rates")


class Period(Base):
    """One clock-in/clock-out pair. `end_at is None` means still running, or —
    once the day is over — an incomplete period the user must fix by hand."""

    __tablename__ = "periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    # "clock" = created by the in/out buttons, "manual" = typed in the day editor.
    source: Mapped[str] = mapped_column(String(16), default="clock")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DayMark(Base):
    __tablename__ = "day_marks"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_daymark_user_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    day_type: Mapped[DayType] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    """Append-only record of every mutation that is not a plain clock press."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    subject_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(32))
    before: Mapped[str | None] = mapped_column(Text, nullable=True)
    after: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
