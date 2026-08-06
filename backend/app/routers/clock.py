from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..calc import now_utc_naive, open_period, to_local, today_local
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import Period, User
from ..schemas import ClockStatusOut, OpenPeriodOut
from ..security import audit
from ..service import all_time_balance, day_view

router = APIRouter(prefix="/api/clock", tags=["clock"])


def _status(db: Session, user: User) -> ClockStatusOut:
    tz = get_settings().tz
    now = now_utc_naive()
    today = today_local(tz)
    running = open_period(db, user.id)

    open_out = None
    if running is not None:
        start_local = to_local(running.start_at, tz)
        open_out = OpenPeriodOut(
            period_id=running.id,
            start=start_local.replace(tzinfo=None),
            elapsed_minutes=int((now - running.start_at).total_seconds() // 60),
            dangling=start_local.date() < today,
        )

    return ClockStatusOut(
        now=to_local(now, tz).replace(tzinfo=None),
        open_period=open_out,
        today=day_view(db, user, today),
        balance_all_time_minutes=all_time_balance(db, user),
    )


@router.get("/status", response_model=ClockStatusOut)
def status_(user: User = Depends(current_user), db: Session = Depends(get_db)) -> ClockStatusOut:
    return _status(db, user)


@router.post("/in", response_model=ClockStatusOut)
def clock_in(user: User = Depends(current_user), db: Session = Depends(get_db)) -> ClockStatusOut:
    if open_period(db, user.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You are already clocked in")
    db.add(Period(user_id=user.id, start_at=now_utc_naive(), source="clock"))
    db.commit()
    return _status(db, user)


@router.post("/out", response_model=ClockStatusOut)
def clock_out(
    force: bool = Query(
        False,
        description="Close a period that began on an earlier day. Without this "
        "the request is refused so the user can correct the times instead.",
    ),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ClockStatusOut:
    running = open_period(db, user.id)
    if running is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You are not clocked in")

    tz = get_settings().tz
    start_local = to_local(running.start_at, tz)
    if start_local.date() < today_local(tz) and not force:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This period started on {start_local:%d %b %Y at %H:%M} and was never "
            "closed. Edit that day to set the right end time, or close it now anyway.",
        )

    now = now_utc_naive()
    if now < running.start_at:
        # Only possible if the clock moved backwards under us.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "End time must be after the start time")

    running.end_at = now
    if force:
        audit(
            db,
            actor_user_id=user.id,
            subject_user_id=user.id,
            entity="period",
            entity_id=running.id,
            action="force_close",
            after={"start_at": running.start_at, "end_at": now},
        )
    db.commit()
    return _status(db, user)
