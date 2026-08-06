"""Query-side services shared by the routers."""

from __future__ import annotations

import calendar as calmod
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .calc import (
    DayStats,
    balance_through,
    build_day_stats,
    day_bounds_utc,
    load_marks,
    load_periods_overlapping,
    load_schedule,
    summarise,
    target_minutes,
    today_local,
)
from .config import get_settings
from .models import User
from .schemas import CalendarOut, DayOut, TotalsOut, WeekOut
from .views import day_out, totals_out


def stats_for_range(db: Session, user: User, first: date, last: date) -> dict[date, DayStats]:
    settings = get_settings()
    tz = settings.tz
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    start_utc, _ = day_bounds_utc(first, tz)
    _, end_utc = day_bounds_utc(last, tz)
    periods = load_periods_overlapping(db, user.id, start_utc, end_utc)
    marks = load_marks(db, user.id, first, last)
    schedule = load_schedule(db, user.id, settings.default_nominal_minutes)
    return build_day_stats(days, periods, marks, schedule, tz, with_slices=True)


def day_view(db: Session, user: User, day: date) -> DayOut:
    return day_out(stats_for_range(db, user, day, day)[day])


def all_time_balance(db: Session, user: User) -> int:
    settings = get_settings()
    return balance_through(
        db,
        user.id,
        settings.tz,
        settings.default_nominal_minutes,
        user.created_at.date(),
        today_local(settings.tz),
    )


def calendar_view(db: Session, user: User, year: int, month: int) -> CalendarOut:
    """A Mon-Sun grid covering the month, with whole-ISO-week totals. Days from
    the neighbouring months are included so week totals are honest."""
    settings = get_settings()
    tz = settings.tz

    first_of_month = date(year, month, 1)
    last_of_month = date(year, month, calmod.monthrange(year, month)[1])
    grid_first = first_of_month - timedelta(days=first_of_month.weekday())
    grid_last = last_of_month + timedelta(days=6 - last_of_month.weekday())

    stats = stats_for_range(db, user, grid_first, grid_last)
    schedule = load_schedule(db, user.id, settings.default_nominal_minutes)

    weeks: list[WeekOut] = []
    cursor = grid_first
    while cursor <= grid_last:
        week_days = [cursor + timedelta(days=i) for i in range(7)]
        week_stats = [stats[d] for d in week_days]
        iso_year, iso_week, _ = cursor.isocalendar()
        weeks.append(
            WeekOut(
                iso_year=iso_year,
                iso_week=iso_week,
                start=week_days[0],
                end=week_days[-1],
                days=[
                    day_out(st, in_month=st.day.month == month and st.day.year == year)
                    for st in week_stats
                ],
                totals=totals_out(summarise(week_stats)),
            )
        )
        cursor += timedelta(days=7)

    month_stats = [stats[d] for d in stats if first_of_month <= d <= last_of_month]
    month_stats.sort(key=lambda s: s.day)
    month_totals: TotalsOut = totals_out(summarise(month_stats))

    # What the whole month asks for, future days included — useful mid-month.
    marks = load_marks(db, user.id, first_of_month, last_of_month)
    target_full = sum(
        target_minutes(st.day, marks.get(st.day), schedule.minutes_for(st.day))
        for st in month_stats
    )

    return CalendarOut(
        year=year,
        month=month,
        weeks=weeks,
        month_totals=month_totals,
        # Vacation booked for next week is still vacation, so absence counts
        # look at the whole month even though hours stop at today.
        month_absences=totals_out(summarise(month_stats, include_future=True)),
        month_target_full_minutes=target_full,
        balance_through_month_end_minutes=balance_through(
            db,
            user.id,
            tz,
            settings.default_nominal_minutes,
            user.created_at.date(),
            last_of_month,
        ),
        balance_all_time_minutes=all_time_balance(db, user),
        nominal_minutes=schedule.minutes_for(today_local(tz)),
    )
