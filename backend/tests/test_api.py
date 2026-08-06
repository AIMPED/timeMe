from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.calc import today_local
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import AuditLog, NominalRate, Period, User
from app.security import hash_password

TZ = get_settings().tz


@pytest.fixture(scope="module")
def client():
    init_db()
    with SessionLocal() as db:
        for u in db.query(User).all():
            db.delete(u)
        db.commit()
        admin = User(
            username="admin",
            password_hash=hash_password("adminpass123"),
            display_name="Admin",
            is_admin=True,
        )
        db.add(admin)
        db.flush()
        db.add(
            NominalRate(user_id=admin.id, effective_from=date(2000, 1, 1), minutes=420)
        )
        db.commit()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass123"})
    assert r.status_code == 200, r.text
    return client


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_login_rejects_bad_password(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_endpoints_require_a_session(client):
    client.cookies.clear()
    assert client.get("/api/clock/status").status_code == 401
    assert client.get("/api/calendar?year=2026&month=8").status_code == 401


def test_login_and_me(admin_client):
    me = admin_client.get("/api/auth/me").json()
    assert me["username"] == "admin"
    assert me["is_admin"] is True
    assert me["nominal_minutes"] == 420


def test_clock_in_then_out(admin_client):
    status = admin_client.get("/api/clock/status").json()
    assert status["open_period"] is None

    r = admin_client.post("/api/clock/in")
    assert r.status_code == 200
    assert r.json()["open_period"] is not None

    # A second clock-in is refused rather than silently starting a new period.
    assert admin_client.post("/api/clock/in").status_code == 409

    r = admin_client.post("/api/clock/out")
    assert r.status_code == 200
    assert r.json()["open_period"] is None

    assert admin_client.post("/api/clock/out").status_code == 409


def test_manual_period_and_day_totals(admin_client):
    day = date(2026, 5, 12)  # a Tuesday
    r = admin_client.post(
        f"/api/days/{day}/periods",
        json={"start": f"{day}T09:00:00", "end": f"{day}T12:30:00", "note": "morning"},
    )
    assert r.status_code == 201, r.text
    r = admin_client.post(
        f"/api/days/{day}/periods",
        json={"start": f"{day}T13:15:00", "end": f"{day}T17:00:00"},
    )
    assert r.status_code == 201, r.text

    detail = admin_client.get(f"/api/days/{day}").json()
    assert detail["day"]["worked_minutes"] == 435
    assert detail["day"]["target_minutes"] == 420
    assert detail["day"]["deviation_minutes"] == 15
    assert len(detail["day"]["periods"]) == 2


def test_overlapping_period_is_refused(admin_client):
    day = date(2026, 5, 12)
    r = admin_client.post(
        f"/api/days/{day}/periods",
        json={"start": f"{day}T11:00:00", "end": f"{day}T14:00:00"},
    )
    assert r.status_code == 409
    assert "Overlaps" in r.json()["detail"]


def test_end_before_start_is_refused(admin_client):
    day = date(2026, 5, 13)
    r = admin_client.post(
        f"/api/days/{day}/periods",
        json={"start": f"{day}T17:00:00", "end": f"{day}T09:00:00"},
    )
    assert r.status_code == 400


def test_edit_and_delete_period(admin_client):
    day = date(2026, 5, 14)
    created = admin_client.post(
        f"/api/days/{day}/periods",
        json={"start": f"{day}T08:00:00", "end": f"{day}T10:00:00"},
    ).json()
    pid = created["day"]["periods"][0]["period_id"]

    r = admin_client.patch(f"/api/periods/{pid}", json={"end": f"{day}T11:00:00"})
    assert r.status_code == 200
    assert r.json()["day"]["worked_minutes"] == 180

    assert admin_client.delete(f"/api/periods/{pid}").status_code == 204
    assert admin_client.get(f"/api/days/{day}").json()["day"]["worked_minutes"] == 0


def test_day_marks_change_the_target(admin_client):
    day = date(2026, 5, 15)  # a Friday
    assert admin_client.get(f"/api/days/{day}").json()["day"]["target_minutes"] == 420

    r = admin_client.put(f"/api/days/{day}/mark", json={"day_type": "vacation", "note": "Leave"})
    assert r.status_code == 200
    assert r.json()["day"]["target_minutes"] == 0
    assert r.json()["day"]["effective_type"] == "vacation"

    r = admin_client.put(f"/api/days/{day}/mark", json={"day_type": "half_day"})
    assert r.json()["day"]["target_minutes"] == 210

    # Clearing the mark restores the weekday default.
    r = admin_client.put(f"/api/days/{day}/mark", json={"day_type": None})
    assert r.json()["day"]["target_minutes"] == 420


def test_saturday_can_be_marked_a_workday(admin_client):
    saturday = date(2026, 5, 16)
    assert admin_client.get(f"/api/days/{saturday}").json()["day"]["target_minutes"] == 0
    r = admin_client.put(f"/api/days/{saturday}/mark", json={"day_type": "workday"})
    assert r.json()["day"]["target_minutes"] == 420
    admin_client.put(f"/api/days/{saturday}/mark", json={"day_type": None})


def test_overnight_period_is_split_across_days(admin_client):
    r = admin_client.post(
        "/api/days/2026-05-20/periods",
        json={"start": "2026-05-20T22:00:00", "end": "2026-05-21T06:00:00"},
    )
    assert r.status_code == 201, r.text
    assert admin_client.get("/api/days/2026-05-20").json()["day"]["worked_minutes"] == 120
    assert admin_client.get("/api/days/2026-05-21").json()["day"]["worked_minutes"] == 360


def test_calendar_grid_and_totals(admin_client):
    cal = admin_client.get("/api/calendar?year=2026&month=5").json()
    assert cal["year"] == 2026 and cal["month"] == 5
    assert all(len(w["days"]) == 7 for w in cal["weeks"])
    # Every day of May appears exactly once and is flagged in_month.
    in_month = [d for w in cal["weeks"] for d in w["days"] if d["in_month"]]
    assert len(in_month) == 31
    assert {d["day"] for d in in_month} == {
        (date(2026, 5, 1) + timedelta(days=i)).isoformat() for i in range(31)
    }
    # May 2026 is fully in the past relative to the recorded data being tested.
    assert cal["month_totals"]["worked_minutes"] >= 435


def test_absences_are_counted_even_when_they_are_in_the_future(admin_client):
    future = today_local(TZ) + timedelta(days=20)
    admin_client.put(f"/api/days/{future}/mark", json={"day_type": "vacation"})
    cal = admin_client.get(f"/api/calendar?year={future.year}&month={future.month}").json()
    # Hours stop at today, so the future day is not in month_totals...
    assert cal["month_totals"]["vacation_days"] == 0
    # ...but booked leave still shows up in the absence counts.
    assert cal["month_absences"]["vacation_days"] == 1
    admin_client.put(f"/api/days/{future}/mark", json={"day_type": None})


def test_calendar_rejects_a_bad_month(admin_client):
    assert admin_client.get("/api/calendar?year=2026&month=13").status_code == 400


def test_dangling_period_flags_the_day_and_blocks_a_plain_clock_out(admin_client):
    # Plant an open period two days ago, as if the user forgot to clock out.
    with SessionLocal() as db:
        user = db.query(User).filter_by(username="admin").one()
        start_local = datetime.combine(
            today_local(TZ) - timedelta(days=2), datetime.min.time()
        ).replace(hour=9)
        from app.calc import to_utc_naive

        db.add(Period(user_id=user.id, start_at=to_utc_naive(start_local, TZ), source="clock"))
        db.commit()

    stale_day = (today_local(TZ) - timedelta(days=2)).isoformat()
    detail = admin_client.get(f"/api/days/{stale_day}").json()["day"]
    assert detail["incomplete"] is True
    assert detail["worked_minutes"] == 0  # nothing is invented

    status = admin_client.get("/api/clock/status").json()
    assert status["open_period"]["dangling"] is True

    r = admin_client.post("/api/clock/out")
    assert r.status_code == 409
    assert "never" in r.json()["detail"]

    r = admin_client.post("/api/clock/out?force=true")
    assert r.status_code == 200
    assert r.json()["open_period"] is None


def test_csv_exports(admin_client):
    r = admin_client.get("/api/export/month.csv?year=2026&month=5")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    assert "Deviation" in body and "TOTAL" in body
    assert "2026-05-12" in body

    r = admin_client.get("/api/export/month.csv?year=2026&month=5&detail=periods")
    assert r.status_code == 200
    assert "morning" in r.text


def test_admin_creates_a_user_who_is_isolated(admin_client):
    r = admin_client.post(
        "/api/admin/users",
        json={
            "username": "bob",
            "password": "bobpassword",
            "display_name": "Bob",
            "nominal_minutes": 300,
        },
    )
    assert r.status_code == 201, r.text
    bob_id = r.json()["id"]
    assert r.json()["nominal_minutes"] == 300

    assert admin_client.post(
        "/api/admin/users", json={"username": "bob", "password": "otherpassword"}
    ).status_code == 409

    admin_client.cookies.clear()
    assert (
        admin_client.post(
            "/api/auth/login", json={"username": "bob", "password": "bobpassword"}
        ).status_code
        == 200
    )
    # Bob sees his own empty day, not the admin's hours.
    assert admin_client.get("/api/days/2026-05-12").json()["day"]["worked_minutes"] == 0
    # And he cannot reach the admin API.
    assert admin_client.get("/api/admin/users").status_code == 403
    assert bob_id


def test_nominal_change_does_not_rewrite_the_past(admin_client):
    users = admin_client.get("/api/admin/users").json()
    bob = next(u for u in users if u["username"] == "bob")

    r = admin_client.put(
        f"/api/admin/users/{bob['id']}/nominal",
        json={"minutes": 480, "effective_from": "2026-06-01"},
    )
    assert r.status_code == 200

    rates = admin_client.get(f"/api/admin/users/{bob['id']}/nominal").json()
    assert {r_["effective_from"]: r_["minutes"] for r_ in rates}["2026-06-01"] == 480

    admin_client.cookies.clear()
    admin_client.post("/api/auth/login", json={"username": "bob", "password": "bobpassword"})
    # May keeps the old 5h target, June gets the new 8h one.
    assert admin_client.get("/api/days/2026-05-12").json()["day"]["target_minutes"] == 300
    assert admin_client.get("/api/days/2026-06-01").json()["day"]["target_minutes"] == 480


def test_cannot_disable_the_last_admin(admin_client):
    admin_client.cookies.clear()
    admin_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass123"})
    me = admin_client.get("/api/auth/me").json()
    r = admin_client.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})
    assert r.status_code == 400
    assert "admin" in r.json()["detail"]


def test_disabled_user_cannot_log_in(admin_client):
    users = admin_client.get("/api/admin/users").json()
    bob = next(u for u in users if u["username"] == "bob")
    assert admin_client.patch(f"/api/admin/users/{bob['id']}", json={"is_active": False}).status_code == 200

    admin_client.cookies.clear()
    r = admin_client.post("/api/auth/login", json={"username": "bob", "password": "bobpassword"})
    assert r.status_code == 401


def test_edits_are_audited(admin_client):
    with SessionLocal() as db:
        actions = {a.action for a in db.query(AuditLog).all()}
    assert {"create", "update", "delete", "set", "force_close"} <= actions
