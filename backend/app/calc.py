"""Time arithmetic: turning raw clock presses into worked minutes, targets and
deviations.

Two rules drive everything here:

1. All day boundaries are drawn in the instance timezone, so a period that runs
   past midnight is split between the two calendar days it touches.
2. An unfinished period is never guessed at. It contributes zero minutes to a
   past day and marks that day *incomplete* until the user fixes it by hand.
   The only exception is the live "running" total on the current day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ZERO_TARGET_TYPES, DayMark, DayType, NominalRate, Period


# --------------------------------------------------------------------------
# timezone helpers
# --------------------------------------------------------------------------


def to_local(dt_utc: datetime, tz: ZoneInfo) -> datetime:
    """Naive-UTC (as stored) -> aware local."""
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(tz)


def to_utc_naive(dt_local: datetime, tz: ZoneInfo) -> datetime:
    """Local (naive or aware) -> naive UTC, ready to store."""
    if dt_local.tzinfo is None:
        dt_local = dt_local.replace(tzinfo=tz)
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Half-open [start, end) of a local calendar day, in naive UTC."""
    start = local_midnight(day, tz).astimezone(timezone.utc).replace(tzinfo=None)
    end = local_midnight(day + timedelta(days=1), tz).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def today_local(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


def now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


# --------------------------------------------------------------------------
# splitting periods across local days
# --------------------------------------------------------------------------


def split_period(start_utc: datetime, end_utc: datetime, tz: ZoneInfo) -> dict[date, int]:
    """Minutes contributed to each local calendar day the period touches.

    The walk is done in UTC on purpose: subtracting two aware datetimes that
    share a ZoneInfo gives the wall-clock difference, which would count a
    DST-shortened day as an hour longer than it really was.
    """
    if end_utc <= start_utc:
        return {}

    out: dict[date, int] = {}
    cursor = start_utc
    while cursor < end_utc:
        day = to_local(cursor, tz).date()
        _, day_end_utc = day_bounds_utc(day, tz)
        chunk_end = min(end_utc, day_end_utc)
        if chunk_end <= cursor:  # defensive: never spin on a zero-length step
            break
        minutes = int((chunk_end - cursor).total_seconds() // 60)
        if minutes:
            out[day] = out.get(day, 0) + minutes
        cursor = chunk_end
    return out


# --------------------------------------------------------------------------
# targets
# --------------------------------------------------------------------------


class NominalSchedule:
    """Resolves a user's nominal minutes for any given day from their rate
    history, so that changing the rate today does not rewrite the past."""

    def __init__(self, rates: list[NominalRate], fallback_minutes: int):
        self._rates = sorted(rates, key=lambda r: r.effective_from)
        self._fallback = fallback_minutes

    def minutes_for(self, day: date) -> int:
        if not self._rates:
            return self._fallback
        current = self._rates[0].minutes  # days before the first rate use the first rate
        for rate in self._rates:
            if rate.effective_from <= day:
                current = rate.minutes
            else:
                break
        return current


def resolve_day_type(day: date, mark: DayMark | None) -> str:
    """The day's effective classification, mark or default."""
    if mark is not None:
        return mark.day_type.value if isinstance(mark.day_type, DayType) else str(mark.day_type)
    return "workday" if day.weekday() < 5 else "weekend"


def target_minutes(day: date, mark: DayMark | None, nominal: int) -> int:
    effective = resolve_day_type(day, mark)
    if effective == "half_day":
        return nominal // 2
    if effective in {t.value for t in ZERO_TARGET_TYPES} or effective == "weekend":
        return 0
    return nominal  # "workday", whether by default or by explicit mark


# --------------------------------------------------------------------------
# per-day aggregation
# --------------------------------------------------------------------------


@dataclass
class PeriodSlice:
    """A period as it appears on one particular day."""

    period_id: int
    start_local: datetime | None  # None when the period began on an earlier day
    end_local: datetime | None  # None when it runs past midnight or is still open
    minutes: int
    open: bool
    note: str
    source: str
    # The whole period, regardless of which day this slice belongs to. The day
    # editor needs these to let the user change a shift that crosses midnight.
    full_start_local: datetime = datetime.min
    full_end_local: datetime | None = None


@dataclass
class DayStats:
    day: date
    worked_minutes: int = 0
    target_minutes: int = 0
    day_type: str | None = None  # the explicit mark, if any
    effective_type: str = "workday"
    note: str = ""
    incomplete: bool = False  # an unfinished period from the past touches this day
    running: bool = False  # a period is open right now and counted live
    is_future: bool = False
    slices: list[PeriodSlice] = field(default_factory=list)

    @property
    def deviation_minutes(self) -> int:
        return self.worked_minutes - self.target_minutes


def build_day_stats(
    days: list[date],
    periods: list[Period],
    marks: dict[date, DayMark],
    schedule: NominalSchedule,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
    with_slices: bool = False,
) -> dict[date, DayStats]:
    """Aggregate `periods` onto `days`. Periods may extend outside the range;
    only the portions landing on a requested day are counted."""
    now = now or now_utc_naive()
    today = to_local(now, tz).date()
    wanted = set(days)
    stats = {d: DayStats(day=d) for d in days}

    for day, st in stats.items():
        mark = marks.get(day)
        st.day_type = resolve_day_type(day, mark) if mark else None
        st.effective_type = resolve_day_type(day, mark)
        st.note = mark.note if mark else ""
        st.is_future = day > today
        st.target_minutes = target_minutes(day, mark, schedule.minutes_for(day))

    for period in periods:
        start_local = to_local(period.start_at, tz)
        is_open = period.end_at is None

        # An open period counts live only while it is still the day it began on.
        # Once that day is over it is dangling: zero minutes, day flagged.
        dangling = is_open and start_local.date() < today
        effective_end = now if is_open else period.end_at

        if dangling:
            # Attribute nothing, but flag every elapsed day it hangs over.
            for day in wanted:
                if start_local.date() <= day < today:
                    stats[day].incomplete = True
            chunks: dict[date, int] = {start_local.date(): 0}
        else:
            chunks = split_period(period.start_at, effective_end, tz)
            for day, minutes in chunks.items():
                if day not in wanted:
                    continue
                stats[day].worked_minutes += minutes
                if is_open:
                    stats[day].running = True

        if with_slices:
            end_local = to_local(effective_end, tz)
            for day, minutes in chunks.items():
                if day not in wanted:
                    continue
                stats[day].slices.append(
                    PeriodSlice(
                        period_id=period.id,
                        start_local=start_local if start_local.date() == day else None,
                        end_local=None if is_open or end_local.date() != day else end_local,
                        minutes=minutes,
                        open=is_open,
                        note=period.note,
                        source=period.source,
                        full_start_local=start_local,
                        full_end_local=None if is_open else end_local,
                    )
                )

    for st in stats.values():
        st.slices.sort(key=lambda s: (s.start_local is not None, s.start_local or datetime.min))

    return stats


# --------------------------------------------------------------------------
# loading helpers
# --------------------------------------------------------------------------


def load_schedule(db: Session, user_id: int, fallback_minutes: int) -> NominalSchedule:
    rates = list(db.scalars(select(NominalRate).where(NominalRate.user_id == user_id)))
    return NominalSchedule(rates, fallback_minutes)


def load_periods_overlapping(
    db: Session, user_id: int, start_utc: datetime, end_utc: datetime
) -> list[Period]:
    """Every period intersecting [start_utc, end_utc), including open ones that
    began before the window."""
    stmt = (
        select(Period)
        .where(Period.user_id == user_id)
        .where(Period.start_at < end_utc)
        .where((Period.end_at.is_(None)) | (Period.end_at > start_utc))
        .order_by(Period.start_at)
    )
    return list(db.scalars(stmt))


def load_marks(db: Session, user_id: int, first: date, last: date) -> dict[date, DayMark]:
    stmt = (
        select(DayMark)
        .where(DayMark.user_id == user_id)
        .where(DayMark.day >= first)
        .where(DayMark.day <= last)
    )
    return {m.day: m for m in db.scalars(stmt)}


def open_period(db: Session, user_id: int) -> Period | None:
    stmt = (
        select(Period)
        .where(Period.user_id == user_id, Period.end_at.is_(None))
        .order_by(Period.start_at.desc())
    )
    return db.scalars(stmt).first()


def first_activity_day(db: Session, user_id: int, tz: ZoneInfo, floor: date) -> date:
    earliest_period = db.scalars(
        select(Period.start_at).where(Period.user_id == user_id).order_by(Period.start_at).limit(1)
    ).first()
    earliest_mark = db.scalars(
        select(DayMark.day).where(DayMark.user_id == user_id).order_by(DayMark.day).limit(1)
    ).first()

    candidates = [floor]
    if earliest_period is not None:
        candidates.append(to_local(earliest_period, tz).date())
    if earliest_mark is not None:
        candidates.append(earliest_mark)
    return min(candidates)


# --------------------------------------------------------------------------
# balances
# --------------------------------------------------------------------------


@dataclass
class Totals:
    worked_minutes: int = 0
    target_minutes: int = 0
    days_counted: int = 0
    vacation_days: float = 0.0
    sick_days: float = 0.0
    holiday_days: float = 0.0
    incomplete_days: int = 0

    @property
    def deviation_minutes(self) -> int:
        return self.worked_minutes - self.target_minutes


def summarise(stats: list[DayStats], *, include_future: bool = False) -> Totals:
    totals = Totals()
    for st in stats:
        if st.is_future and not include_future:
            # A day that has not happened yet is neither worked nor owed.
            continue
        totals.worked_minutes += st.worked_minutes
        totals.target_minutes += st.target_minutes
        totals.days_counted += 1
        if st.effective_type == "vacation":
            totals.vacation_days += 1
        elif st.effective_type == "sick":
            totals.sick_days += 1
        elif st.effective_type == "holiday":
            totals.holiday_days += 1
        if st.incomplete:
            totals.incomplete_days += 1
    return totals


def balance_through(
    db: Session,
    user_id: int,
    tz: ZoneInfo,
    fallback_minutes: int,
    created_on: date,
    through: date,
) -> int:
    """Cumulative deviation in minutes from the user's first activity up to and
    including `through` (never counting days in the future)."""
    today = today_local(tz)
    last = min(through, today)
    first = first_activity_day(db, user_id, tz, created_on)
    if last < first:
        return 0

    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    start_utc, _ = day_bounds_utc(first, tz)
    _, end_utc = day_bounds_utc(last, tz)
    periods = load_periods_overlapping(db, user_id, start_utc, end_utc)
    marks = load_marks(db, user_id, first, last)
    schedule = load_schedule(db, user_id, fallback_minutes)
    stats = build_day_stats(days, periods, marks, schedule, tz)
    return summarise(list(stats.values())).deviation_minutes
