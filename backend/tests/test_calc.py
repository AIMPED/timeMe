from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.calc import (
    NominalSchedule,
    build_day_stats,
    split_period,
    summarise,
    target_minutes,
    to_utc_naive,
)
from app.models import DayMark, DayType, Period

TZ = ZoneInfo("Europe/Berlin")
NOMINAL = NominalSchedule([], 420)


def utc(local: str) -> datetime:
    return to_utc_naive(datetime.fromisoformat(local), TZ)


def mk_period(pid: int, start: str, end: str | None) -> Period:
    return Period(
        id=pid, user_id=1, start_at=utc(start), end_at=utc(end) if end else None,
        note="", source="clock",
    )


def test_split_within_one_day():
    assert split_period(utc("2026-08-06T09:00"), utc("2026-08-06T12:30"), TZ) == {
        date(2026, 8, 6): 210
    }


def test_split_across_midnight():
    chunks = split_period(utc("2026-08-06T22:00"), utc("2026-08-07T06:00"), TZ)
    assert chunks == {date(2026, 8, 6): 120, date(2026, 8, 7): 360}


def test_split_across_dst_spring_forward():
    # 2026-03-29 Europe/Berlin loses an hour at 02:00; 01:00 to 04:00 local is
    # two real hours, and both belong to the same calendar day.
    chunks = split_period(utc("2026-03-29T01:00"), utc("2026-03-29T04:00"), TZ)
    assert chunks == {date(2026, 3, 29): 120}


def test_target_defaults_by_weekday():
    assert target_minutes(date(2026, 8, 6), None, 420) == 420  # Thursday
    assert target_minutes(date(2026, 8, 8), None, 420) == 0  # Saturday


def test_marks_override_defaults():
    def mark(t):
        return DayMark(user_id=1, day=date(2026, 8, 6), day_type=t)

    assert target_minutes(date(2026, 8, 6), mark(DayType.VACATION), 420) == 0
    assert target_minutes(date(2026, 8, 6), mark(DayType.SICK), 420) == 0
    assert target_minutes(date(2026, 8, 6), mark(DayType.HOLIDAY), 420) == 0
    assert target_minutes(date(2026, 8, 6), mark(DayType.HALF_DAY), 420) == 210
    # A Saturday explicitly marked as a workday does carry a target.
    saturday = DayMark(user_id=1, day=date(2026, 8, 8), day_type=DayType.WORKDAY)
    assert target_minutes(date(2026, 8, 8), saturday, 420) == 420


def test_nominal_history_keeps_the_past_intact():
    from app.models import NominalRate

    schedule = NominalSchedule(
        [
            NominalRate(user_id=1, effective_from=date(2026, 1, 1), minutes=420),
            NominalRate(user_id=1, effective_from=date(2026, 7, 1), minutes=300),
        ],
        480,
    )
    assert schedule.minutes_for(date(2026, 6, 30)) == 420
    assert schedule.minutes_for(date(2026, 7, 1)) == 300
    assert schedule.minutes_for(date(2025, 5, 5)) == 420  # before any rate


def test_two_periods_sum_and_deviate():
    day = date(2026, 8, 6)
    periods = [
        mk_period(1, "2026-08-06T09:00", "2026-08-06T12:30"),
        mk_period(2, "2026-08-06T13:15", "2026-08-06T17:00"),
    ]
    stats = build_day_stats([day], periods, {}, NOMINAL, TZ, now=utc("2026-08-07T10:00"))
    assert stats[day].worked_minutes == 210 + 225
    assert stats[day].deviation_minutes == 435 - 420  # +15 minutes


def test_open_period_today_counts_live():
    day = date(2026, 8, 6)
    now = utc("2026-08-06T11:00")
    stats = build_day_stats(
        [day], [mk_period(1, "2026-08-06T09:00", None)], {}, NOMINAL, TZ, now=now
    )
    assert stats[day].worked_minutes == 120
    assert stats[day].running is True
    assert stats[day].incomplete is False


def test_dangling_period_contributes_nothing_and_flags_the_day():
    days = [date(2026, 8, 6), date(2026, 8, 7)]
    now = utc("2026-08-07T11:00")
    stats = build_day_stats(
        days, [mk_period(1, "2026-08-06T09:00", None)], {}, NOMINAL, TZ, now=now
    )
    assert stats[date(2026, 8, 6)].worked_minutes == 0
    assert stats[date(2026, 8, 6)].incomplete is True
    # It does not silently bleed into the following day either.
    assert stats[date(2026, 8, 7)].worked_minutes == 0
    assert stats[date(2026, 8, 7)].incomplete is False


def test_overnight_shift_splits_between_both_days():
    days = [date(2026, 8, 6), date(2026, 8, 7)]
    stats = build_day_stats(
        days,
        [mk_period(1, "2026-08-06T22:00", "2026-08-07T06:00")],
        {},
        NOMINAL,
        TZ,
        now=utc("2026-08-08T10:00"),
    )
    assert stats[date(2026, 8, 6)].worked_minutes == 120
    assert stats[date(2026, 8, 7)].worked_minutes == 360


def test_future_days_are_excluded_from_totals():
    days = [date(2026, 8, 6), date(2026, 8, 7)]
    stats = build_day_stats(days, [], {}, NOMINAL, TZ, now=utc("2026-08-06T12:00"))
    totals = summarise(list(stats.values()))
    assert totals.days_counted == 1
    assert totals.target_minutes == 420  # only the 6th is owed
    assert totals.deviation_minutes == -420


def test_summarise_counts_absences():
    days = [date(2026, 8, 6), date(2026, 8, 7)]
    marks = {
        date(2026, 8, 6): DayMark(user_id=1, day=date(2026, 8, 6), day_type=DayType.VACATION),
        date(2026, 8, 7): DayMark(user_id=1, day=date(2026, 8, 7), day_type=DayType.SICK),
    }
    stats = build_day_stats(days, [], marks, NOMINAL, TZ, now=utc("2026-08-10T10:00"))
    totals = summarise(list(stats.values()))
    assert totals.vacation_days == 1
    assert totals.sick_days == 1
    assert totals.target_minutes == 0
    assert totals.deviation_minutes == 0
