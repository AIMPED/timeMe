#!/usr/bin/env python3
"""Import historical time data into timeMe via the public API.

Reads a "periods"-style CSV (one clock-in/out slice per row) and creates the
matching period rows through POST /api/days/{day}/periods. Optionally reads a
second CSV of day marks (vacation / sick / half-day / holiday / off).

The server stores times as UTC but the API speaks *local wall-clock* time, so
we send exactly the times as they appear in your table — no tz math here.

Usage:
    python import_periods.py \
        --base-url http://localhost:8000 \
        --username alice \
        --periods history_periods.csv \
        [--marks history_marks.csv] \
        [--wipe-range 2026-01-01 2026-01-31] \
        [--delimiter ';'] [--dry-run]

--wipe-range deletes every period that starts in the given inclusive date range
and clears any day marks there, so an import can be re-run cleanly. It runs
before the import, and can also be used on its own (without --periods).

Password is read from the TIMEME_PASSWORD env var, or prompted for.

periods CSV columns (header row required, case-insensitive):
    Date;Start;End;Note
    2026-01-06;08:30;12:00;
    2026-01-06;12:45;17:15;afternoon
    2026-01-07;22:00;02:30;night shift        # end < start => spills to next day
    2026-01-08;09:00;;still-open slice         # blank End => open period

marks CSV columns (optional):
    Date;Type;Note
    2026-01-09;vacation;
    2026-01-10;sick;flu
    Type is one of: workday, half_day, vacation, sick, holiday, off
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta

import httpx

VALID_TYPES = {"workday", "half_day", "vacation", "sick", "holiday", "off"}


def _dt(day: str, hhmm: str) -> str:
    """Combine 'YYYY-MM-DD' + 'HH:MM' into a naive ISO datetime string."""
    return datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M").isoformat()


def login(session: httpx.Client, base_url: str, username: str, password: str) -> None:
    r = session.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
    )
    if r.status_code != 200:
        sys.exit(f"Login failed ({r.status_code}): {r.text}")
    # The session cookie is now stored on `session` and sent automatically.


def wipe_range(
    session: httpx.Client, base_url: str, start: str, end: str, dry_run: bool
) -> None:
    """Delete every period that *starts* within [start, end] and clear any day
    marks in the range, so an import can be re-run cleanly.

    A period is deleted only when its own start falls in the range (via
    `full_start`), so a slice that merely spills into the range from an earlier
    day is left alone.
    """
    start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    if end_d < start_d:
        sys.exit(f"--wipe-range end {end} is before start {start}")

    seen: set[int] = set()
    deleted = marks_cleared = failed = 0
    day = start_d
    while day <= end_d:
        iso = day.isoformat()
        r = session.get(f"{base_url}/api/days/{iso}")
        if r.status_code != 200:
            print(f"  {iso}: GET failed ({r.status_code}) {r.text}")
            failed += 1
            day += timedelta(days=1)
            continue
        detail = r.json()["day"]

        for p in detail["periods"]:
            pid = p["period_id"]
            if pid in seen:
                continue
            if not (start_d <= datetime.fromisoformat(p["full_start"]).date() <= end_d):
                continue  # started before the range — don't touch it
            seen.add(pid)
            if dry_run:
                print(f"  {iso}: DELETE /api/periods/{pid}")
                deleted += 1
                continue
            d = session.delete(f"{base_url}/api/periods/{pid}")
            if d.status_code == 204:
                deleted += 1
            else:
                print(f"  {iso}: DELETE period {pid} failed ({d.status_code}) {d.text}")
                failed += 1

        if detail["day_type"] is not None:  # an explicit mark exists — clear it
            if dry_run:
                print(f"  {iso}: PUT /api/days/{iso}/mark (clear)")
                marks_cleared += 1
            else:
                m = session.put(f"{base_url}/api/days/{iso}/mark", json={"day_type": None})
                if m.status_code == 200:
                    marks_cleared += 1
                else:
                    print(f"  {iso}: clear mark failed ({m.status_code}) {m.text}")
                    failed += 1

        day += timedelta(days=1)
    print(f"wipe: {deleted} periods deleted, {marks_cleared} marks cleared, {failed} failed")


def import_periods(
    session: httpx.Client, base_url: str, path: str, delimiter: str, dry_run: bool
) -> None:
    with open(path, newline="", encoding="utf-8-sig") as f:  # utf-8-sig drops the export BOM
        reader = csv.DictReader(f, delimiter=delimiter)
        # normalise headers to lowercase so 'Date'/'date' both work
        reader.fieldnames = [h.strip().lower() for h in (reader.fieldnames or [])]
        ok = skipped = failed = 0
        for i, row in enumerate(reader, start=2):  # row 1 is the header
            day = (row.get("date") or "").strip()
            start = (row.get("start") or "").strip()
            end = (row.get("end") or "").strip()
            note = (row.get("note") or "").strip()
            if not day or not start:
                print(f"  line {i}: missing Date/Start — skipped")
                skipped += 1
                continue

            start_iso = _dt(day, start)
            end_iso = None
            if end:
                start_dt = datetime.fromisoformat(start_iso)
                end_dt = datetime.strptime(f"{day} {end}", "%Y-%m-%d %H:%M")
                if end_dt <= start_dt:  # crossed midnight — roll to the next day
                    end_dt += timedelta(days=1)
                end_iso = end_dt.isoformat()

            payload = {"start": start_iso, "end": end_iso, "note": note}
            if dry_run:
                print(f"  line {i}: POST /api/days/{day}/periods {payload}")
                ok += 1
                continue

            r = session.post(f"{base_url}/api/days/{day}/periods", json=payload)
            if r.status_code == 201:
                ok += 1
            elif r.status_code == 409:  # _assert_no_overlap rejected it
                print(f"  line {i}: overlap, skipped — {r.json().get('detail')}")
                skipped += 1
            else:
                print(f"  line {i}: FAILED ({r.status_code}) {r.text}")
                failed += 1
        print(f"periods: {ok} created, {skipped} skipped, {failed} failed")


def import_marks(
    session: httpx.Client, base_url: str, path: str, delimiter: str, dry_run: bool
) -> None:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        reader.fieldnames = [h.strip().lower() for h in (reader.fieldnames or [])]
        ok = failed = 0
        for i, row in enumerate(reader, start=2):
            day = (row.get("date") or "").strip()
            day_type = (row.get("type") or "").strip()
            note = (row.get("note") or "").strip()
            if day_type not in VALID_TYPES:
                print(f"  line {i}: invalid Type {day_type!r} — skipped")
                failed += 1
                continue
            payload = {"day_type": day_type, "note": note}
            if dry_run:
                print(f"  line {i}: PUT /api/days/{day}/mark {payload}")
                ok += 1
                continue
            r = session.put(f"{base_url}/api/days/{day}/mark", json=payload)
            if r.status_code == 200:
                ok += 1
            else:
                print(f"  line {i}: FAILED ({r.status_code}) {r.text}")
                failed += 1
        print(f"marks: {ok} set, {failed} failed")


def main() -> None:
    ap = argparse.ArgumentParser(description="Import historical time data into timeMe.")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--username", required=True)
    ap.add_argument("--periods", help="periods CSV path")
    ap.add_argument("--marks", help="optional day-marks CSV path")
    ap.add_argument(
        "--wipe-range",
        nargs=2,
        metavar=("START", "END"),
        help="delete periods/marks in this inclusive YYYY-MM-DD range first",
    )
    ap.add_argument("--delimiter", default=";", help="CSV delimiter (default ';')")
    ap.add_argument("--dry-run", action="store_true", help="print requests, send nothing")
    args = ap.parse_args()

    if not (args.periods or args.wipe_range):
        ap.error("nothing to do — give --periods and/or --wipe-range")

    # A dry-run of --wipe-range still needs to read the days it would clear, so
    # we log in whenever wiping, dry-run or not.
    need_login = (not args.dry_run) or bool(args.wipe_range)
    password = os.environ.get("TIMEME_PASSWORD")
    if not password and need_login:
        import getpass

        password = getpass.getpass(f"Password for {args.username}: ")

    session = httpx.Client()
    if need_login:
        login(session, args.base_url, args.username, password)

    if args.wipe_range:
        wipe_range(session, args.base_url, *args.wipe_range, dry_run=args.dry_run)
    if args.periods:
        import_periods(session, args.base_url, args.periods, args.delimiter, args.dry_run)
    if args.marks:
        import_marks(session, args.base_url, args.marks, args.delimiter, args.dry_run)


if __name__ == "__main__":
    main()
