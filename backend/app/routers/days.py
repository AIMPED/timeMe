from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..calc import load_schedule, to_local, to_utc_naive
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import DayMark, Period, User
from ..schemas import DayDetailOut, MarkUpdate, PeriodCreate, PeriodUpdate
from ..security import audit
from ..service import day_view

router = APIRouter(prefix="/api", tags=["days"])

MAX_PERIOD_HOURS = 24


def _snapshot(p: Period) -> dict:
    return {"start_at": p.start_at, "end_at": p.end_at, "note": p.note}


def _assert_no_overlap(
    db: Session, user_id: int, start_utc: datetime, end_utc: datetime | None, exclude_id: int | None
) -> None:
    """Two work periods cannot run at the same time. An open period is treated
    as occupying everything from its start onwards."""
    horizon = end_utc or datetime.max
    stmt = select(Period).where(Period.user_id == user_id, Period.start_at < horizon)
    if exclude_id is not None:
        stmt = stmt.where(Period.id != exclude_id)
    for other in db.scalars(stmt):
        other_end = other.end_at or datetime.max
        if other_end > start_utc:
            local = to_local(other.start_at, get_settings().tz)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Overlaps an existing period starting {local:%d %b %H:%M}",
            )


def _validate_bounds(start_utc: datetime, end_utc: datetime | None) -> None:
    if end_utc is None:
        return
    if end_utc <= start_utc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "End time must be after the start time")
    if end_utc - start_utc > timedelta(hours=MAX_PERIOD_HOURS):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A single period cannot be longer than {MAX_PERIOD_HOURS} hours",
        )


@router.get("/days/{day}", response_model=DayDetailOut)
def get_day(
    day: date, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> DayDetailOut:
    settings = get_settings()
    schedule = load_schedule(db, user.id, settings.default_nominal_minutes)
    return DayDetailOut(day=day_view(db, user, day), nominal_minutes=schedule.minutes_for(day))


@router.post("/days/{day}/periods", response_model=DayDetailOut, status_code=status.HTTP_201_CREATED)
def create_period(
    day: date,
    payload: PeriodCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DayDetailOut:
    tz = get_settings().tz
    start_utc = to_utc_naive(payload.start, tz)
    end_utc = to_utc_naive(payload.end, tz) if payload.end else None
    _validate_bounds(start_utc, end_utc)
    _assert_no_overlap(db, user.id, start_utc, end_utc, exclude_id=None)

    period = Period(
        user_id=user.id,
        start_at=start_utc,
        end_at=end_utc,
        note=payload.note,
        source="manual",
    )
    db.add(period)
    db.flush()
    audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        entity="period",
        entity_id=period.id,
        action="create",
        after=_snapshot(period),
    )
    db.commit()
    return get_day(day, user, db)


@router.patch("/periods/{period_id}", response_model=DayDetailOut)
def update_period(
    period_id: int,
    payload: PeriodUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DayDetailOut:
    tz = get_settings().tz
    period = db.get(Period, period_id)
    if period is None or period.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Period not found")

    before = _snapshot(period)
    start_utc = to_utc_naive(payload.start, tz) if payload.start else period.start_at
    if payload.clear_end:
        end_utc = None
    elif payload.end is not None:
        end_utc = to_utc_naive(payload.end, tz)
    else:
        end_utc = period.end_at

    _validate_bounds(start_utc, end_utc)
    _assert_no_overlap(db, user.id, start_utc, end_utc, exclude_id=period.id)

    period.start_at = start_utc
    period.end_at = end_utc
    if payload.note is not None:
        period.note = payload.note

    audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        entity="period",
        entity_id=period.id,
        action="update",
        before=before,
        after=_snapshot(period),
    )
    db.commit()
    return get_day(to_local(period.start_at, tz).date(), user, db)


@router.delete("/periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_period(
    period_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    period = db.get(Period, period_id)
    if period is None or period.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Period not found")
    audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        entity="period",
        entity_id=period.id,
        action="delete",
        before=_snapshot(period),
    )
    db.delete(period)
    db.commit()


@router.put("/days/{day}/mark", response_model=DayDetailOut)
def set_mark(
    day: date,
    payload: MarkUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DayDetailOut:
    mark = db.scalars(
        select(DayMark).where(DayMark.user_id == user.id, DayMark.day == day)
    ).first()
    before = {"day_type": mark.day_type, "note": mark.note} if mark else None

    if payload.day_type is None:
        if mark is not None:
            db.delete(mark)
        after = None
    else:
        if mark is None:
            mark = DayMark(user_id=user.id, day=day)
            db.add(mark)
        mark.day_type = payload.day_type
        mark.note = payload.note
        after = {"day_type": payload.day_type.value, "note": payload.note}

    audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        entity="day_mark",
        entity_id=day.isoformat(),
        action="set" if payload.day_type else "clear",
        before=before,
        after=after,
    )
    db.commit()
    return get_day(day, user, db)
