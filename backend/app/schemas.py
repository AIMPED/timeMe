from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from .models import DayType


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    is_admin: bool
    is_active: bool
    nominal_minutes: int


# --------------------------------------------------------------------------
# days
# --------------------------------------------------------------------------


class PeriodOut(BaseModel):
    period_id: int
    start: datetime | None  # local; None when the period began on an earlier day
    end: datetime | None  # local; None when open or running past midnight
    minutes: int
    open: bool
    note: str
    source: str
    continues_from_previous_day: bool
    continues_to_next_day: bool
    full_start: datetime  # the period's own start, local
    full_end: datetime | None  # its own end, local; null while open


class DayOut(BaseModel):
    day: date
    in_month: bool = True
    worked_minutes: int
    target_minutes: int
    deviation_minutes: int
    day_type: str | None
    effective_type: str
    note: str
    incomplete: bool
    running: bool
    is_future: bool
    periods: list[PeriodOut] = []


class TotalsOut(BaseModel):
    worked_minutes: int
    target_minutes: int
    deviation_minutes: int
    days_counted: int
    vacation_days: float
    sick_days: float
    holiday_days: float
    incomplete_days: int


class WeekOut(BaseModel):
    iso_year: int
    iso_week: int
    start: date
    end: date
    days: list[DayOut]
    totals: TotalsOut


class CalendarOut(BaseModel):
    year: int
    month: int
    weeks: list[WeekOut]
    month_totals: TotalsOut  # hours only count days that have already happened
    month_absences: TotalsOut  # absence day counts over the whole month, future included
    month_target_full_minutes: int
    balance_through_month_end_minutes: int
    balance_all_time_minutes: int
    nominal_minutes: int


class DayDetailOut(BaseModel):
    day: DayOut
    nominal_minutes: int


class OpenPeriodOut(BaseModel):
    period_id: int
    start: datetime
    elapsed_minutes: int
    dangling: bool


class ClockStatusOut(BaseModel):
    now: datetime
    open_period: OpenPeriodOut | None
    today: DayOut
    balance_all_time_minutes: int


# --------------------------------------------------------------------------
# mutations
# --------------------------------------------------------------------------


class PeriodCreate(BaseModel):
    start: datetime  # local wall-clock, naive
    end: datetime | None = None
    note: str = ""

    @field_validator("start", "end")
    @classmethod
    def strip_tzinfo(cls, v: datetime | None) -> datetime | None:
        # Times are always instance-local; an offset from the client would only
        # be a lie waiting to happen.
        return v.replace(tzinfo=None, second=0, microsecond=0) if v else v


class PeriodUpdate(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    clear_end: bool = False
    note: str | None = None

    @field_validator("start", "end")
    @classmethod
    def strip_tzinfo(cls, v: datetime | None) -> datetime | None:
        return v.replace(tzinfo=None, second=0, microsecond=0) if v else v


class MarkUpdate(BaseModel):
    day_type: DayType | None = None  # null clears the mark
    note: str = ""


# --------------------------------------------------------------------------
# admin
# --------------------------------------------------------------------------


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = ""
    is_admin: bool = False
    nominal_minutes: int = Field(default=420, ge=0, le=24 * 60)


class UserUpdate(BaseModel):
    display_name: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class NominalUpdate(BaseModel):
    minutes: int = Field(ge=0, le=24 * 60)
    effective_from: date
