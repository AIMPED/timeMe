from __future__ import annotations

import calendar as calmod
import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import CalendarOut
from ..service import calendar_view, stats_for_range

router = APIRouter(prefix="/api", tags=["reports"])

DAY_TYPE_LABELS = {
    "workday": "Workday",
    "weekend": "Weekend",
    "half_day": "Half day",
    "vacation": "Vacation",
    "sick": "Sick",
    "holiday": "Public holiday",
    "off": "Off",
}


def hm(minutes: int) -> str:
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return f"{sign}{minutes // 60}:{minutes % 60:02d}"


def _check_month(year: int, month: int) -> None:
    if not 1 <= month <= 12 or not 1970 <= year <= 2200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid year or month")


@router.get("/calendar", response_model=CalendarOut)
def calendar_month(
    year: int = Query(...),
    month: int = Query(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CalendarOut:
    _check_month(year, month)
    return calendar_view(db, user, year, month)


@router.get("/export/month.csv")
def export_month(
    year: int = Query(...),
    month: int = Query(...),
    detail: str = Query("days", pattern="^(days|periods)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    _check_month(year, month)
    first = date(year, month, 1)
    last = date(year, month, calmod.monthrange(year, month)[1])
    stats = stats_for_range(db, user, first, last)
    ordered = [stats[d] for d in sorted(stats)]

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")

    if detail == "periods":
        writer.writerow(["Date", "Weekday", "Start", "End", "Duration", "Minutes", "Note", "Source"])
        for st in ordered:
            for sl in st.slices:
                writer.writerow(
                    [
                        st.day.isoformat(),
                        st.day.strftime("%a"),
                        sl.start_local.strftime("%H:%M") if sl.start_local else "(prev. day)",
                        sl.end_local.strftime("%H:%M")
                        if sl.end_local
                        else ("(open)" if sl.open else "(next day)"),
                        hm(sl.minutes),
                        sl.minutes,
                        sl.note,
                        sl.source,
                    ]
                )
    else:
        writer.writerow(
            [
                "Date",
                "Weekday",
                "Type",
                "Worked",
                "Target",
                "Deviation",
                "Worked minutes",
                "Target minutes",
                "Deviation minutes",
                "Incomplete",
                "Note",
            ]
        )
        for st in ordered:
            counted = not st.is_future
            writer.writerow(
                [
                    st.day.isoformat(),
                    st.day.strftime("%a"),
                    DAY_TYPE_LABELS.get(st.effective_type, st.effective_type),
                    hm(st.worked_minutes),
                    hm(st.target_minutes),
                    hm(st.deviation_minutes) if counted else "",
                    st.worked_minutes,
                    st.target_minutes,
                    st.deviation_minutes if counted else "",
                    "yes" if st.incomplete else "",
                    st.note,
                ]
            )
        past = [s for s in ordered if not s.is_future]
        writer.writerow([])
        writer.writerow(
            [
                "TOTAL",
                "",
                f"{len(past)} days",
                hm(sum(s.worked_minutes for s in past)),
                hm(sum(s.target_minutes for s in past)),
                hm(sum(s.deviation_minutes for s in past)),
                sum(s.worked_minutes for s in past),
                sum(s.target_minutes for s in past),
                sum(s.deviation_minutes for s in past),
                "",
                "",
            ]
        )

    buf.seek(0)
    filename = f"timeme-{user.username}-{year}-{month:02d}-{detail}.csv"
    return StreamingResponse(
        # Excel needs the BOM to read the separator hint and UTF-8 correctly.
        iter(["﻿" + buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
