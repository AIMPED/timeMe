"""Mapping the calc dataclasses onto the wire format."""

from __future__ import annotations

from .calc import DayStats, Totals
from .schemas import DayOut, PeriodOut, TotalsOut


def period_out(slice_) -> PeriodOut:
    return PeriodOut(
        period_id=slice_.period_id,
        start=slice_.start_local.replace(tzinfo=None) if slice_.start_local else None,
        end=slice_.end_local.replace(tzinfo=None) if slice_.end_local else None,
        minutes=slice_.minutes,
        open=slice_.open,
        note=slice_.note,
        source=slice_.source,
        continues_from_previous_day=slice_.start_local is None,
        continues_to_next_day=not slice_.open and slice_.end_local is None,
        full_start=slice_.full_start_local.replace(tzinfo=None),
        full_end=slice_.full_end_local.replace(tzinfo=None) if slice_.full_end_local else None,
    )


def day_out(st: DayStats, *, in_month: bool = True, with_periods: bool = True) -> DayOut:
    return DayOut(
        day=st.day,
        in_month=in_month,
        worked_minutes=st.worked_minutes,
        target_minutes=st.target_minutes,
        deviation_minutes=st.deviation_minutes,
        day_type=st.day_type,
        effective_type=st.effective_type,
        note=st.note,
        incomplete=st.incomplete,
        running=st.running,
        is_future=st.is_future,
        periods=[period_out(s) for s in st.slices] if with_periods else [],
    )


def totals_out(t: Totals) -> TotalsOut:
    return TotalsOut(
        worked_minutes=t.worked_minutes,
        target_minutes=t.target_minutes,
        deviation_minutes=t.deviation_minutes,
        days_counted=t.days_counted,
        vacation_days=t.vacation_days,
        sick_days=t.sick_days,
        holiday_days=t.holiday_days,
        incomplete_days=t.incomplete_days,
    )
