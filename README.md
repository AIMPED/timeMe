# timeMe

Working-time tracker. Clock in and out with two buttons, correct mistakes on a
day-editor page, and see worked hours per day, week and month against a nominal
target — with the deviation and a running balance.

- **Backend** — FastAPI + SQLAlchemy + SQLite
- **Frontend** — React + Vite + TypeScript, built into the same container
- **Deployment** — one Docker image behind Caddy, plus a backup sidecar

## How the numbers work

| Rule | Behaviour |
|---|---|
| A period | One clock-in / clock-out pair. Any number per day. |
| Midnight | A shift that crosses midnight is split between the two days. |
| Unclosed period | Never guessed at. It counts as **zero** and the day is flagged until you set the end time yourself. |
| Mon–Fri | Target = the user's nominal hours (7:00 by default). |
| Sat/Sun | Target 0, unless you mark the day a workday. |
| Vacation / sick / public holiday / off | Target 0. |
| Half day | Target = nominal ÷ 2. |
| Future days | Neither worked nor owed — excluded from every total. |
| Nominal changes | Recorded with an effective date, so past days keep the target they were judged against. |

Public holidays are marked by hand, per user — there is no holiday calendar to
get out of date.

Balance = the sum of every day's deviation from the user's first recorded day
through today.

## Deploy on the VPS

Deployment is automatic: merging to `main` runs the tests, builds and pushes the
images to GHCR, and restarts the app on the VPS. **[DEPLOYMENT.md](DEPLOYMENT.md)
is the one-time setup walkthrough** — DNS, the deploy user, registry access,
GitHub secrets and Caddy.

Caddy is expected to already run on the host. The app publishes only to
`127.0.0.1`, so Caddy is the sole route in. `docker-compose.yml` pulls prebuilt
images and deliberately has no `build:` stanza; the VPS never compiles what it
runs. To build locally, use `docker-compose.local.dev.yml`.

### Upgrading

Merge to `main`. To check what is live, or to roll back to an earlier commit:

```bash
cd /srv/timeme
grep TIMEME_TAG .env        # the commit SHA currently running
./deploy.sh <older-sha>     # roll back
```

The schema is created on start-up; the SQLite file lives in the `timeme-data`
volume and is untouched by a deploy. There is no migration framework — see the
schema-changes note in [DEPLOYMENT.md](DEPLOYMENT.md).

## Administration

Users are managed in the **Admin** page in the UI. The CLI covers the same
ground and is how you bootstrap the first account:

```bash
docker compose exec app python -m app.cli list-users
docker compose exec app python -m app.cli create-user bob --hours 5
docker compose exec app python -m app.cli reset-password bob
docker compose exec app python -m app.cli set-nominal bob 6 --effective-from 2026-09-01
docker compose exec app python -m app.cli set-active bob disable
```

Every manual edit — period added, changed or deleted, day type set, password
reset, nominal hours changed — is written to the `audit_log` table with the
actor, the timestamp and the before/after values.

## Backups

The `backup` service takes a `sqlite3 .backup` snapshot every night at
`BACKUP_AT`, verifies it with `PRAGMA integrity_check`, gzips it into
`./backups/`, and prunes anything older than `BACKUP_KEEP_DAYS`. It also runs
once at start-up so a fresh deployment is covered immediately.

```bash
docker compose logs -f backup          # watch it
ls -lh backups/                        # what is on disk
```

Restore:

```bash
docker compose stop app
gunzip -c backups/timeme-20260806-033000.sqlite.gz > /tmp/restore.db
docker compose run --rm -v /tmp:/restore --entrypoint sh app \
  -c 'cp /restore/restore.db /data/timeme.db && rm -f /data/timeme.db-wal /data/timeme.db-shm'
docker compose start app
```

Copy `./backups` off the machine periodically — a backup on the same disk only
protects you from mistakes, not from losing the disk.

## Export

The calendar page has **CSV: days** (one row per day with worked, target and
deviation, plus a total row) and **CSV: periods** (one row per clock-in/out
pair). Both are semicolon-separated with a BOM, so Excel opens them directly.

## Import

There is no import UI. To load history from before you started using timeMe —
say, hours you kept in a spreadsheet — use `backend/scripts/import_periods.py`.
It talks to the running API as you, so it obeys the same rules as the day
editor: times are local wall-clock, periods may not overlap, and worked/target/
deviation are never imported (they are always recomputed from the periods, the
day types and the nominal-hours history).

Feed it a **periods** CSV (one clock-in/out slice per row) and, optionally, a
**marks** CSV for absences. Both are semicolon-separated with a header row;
column names are case-insensitive, and a leading BOM (as written by the export)
is tolerated, so a file exported from timeMe re-imports as-is.

`periods` — columns `Date;Start;End;Note`:

```
Date;Start;End;Note
2026-01-06;08:30;12:00;
2026-01-06;12:45;17:15;afternoon
2026-01-07;22:00;02:30;night shift     # End <= Start rolls over to the next day
2026-01-08;09:00;;still-open slice      # blank End = an open period
```

`marks` — columns `Date;Type;Note`, where `Type` is one of `workday`,
`half_day`, `vacation`, `sick`, `holiday`, `off`:

```
Date;Type;Note
2026-01-12;vacation;
2026-01-13;sick;flu
```

Run it against a running backend. The password is read from `TIMEME_PASSWORD`,
or prompted for. `--dry-run` prints every request without sending anything —
always preview first.

```bash
cd backend
TIMEME_PASSWORD=... .venv/bin/python scripts/import_periods.py \
    --base-url http://localhost:8000 --username alice \
    --periods history_periods.csv --marks history_marks.csv --dry-run
```

Rows that can't be placed are reported and skipped, not fatal: a row missing
`Date`/`Start`, a period that overlaps an existing one (the API returns `409`),
or an unknown mark `Type`. There is no natural key, so **re-running an import
creates duplicates** — import into an empty range, or clear it first.

`--wipe-range START END` (inclusive `YYYY-MM-DD` dates) does that clearing: it
deletes every period whose own start falls in the range and clears any day marks
there, then the import can run cleanly. It runs before the import, or on its own
without `--periods`. A period that merely spills into the range from an earlier
day is left alone. This permanently deletes real data (each delete is written to
`audit_log`, but there is no undo), so dry-run it first:

```bash
# preview what would be removed — reads live data, changes nothing
.venv/bin/python scripts/import_periods.py --base-url http://localhost:8000 \
    --username alice --wipe-range 2026-01-01 2026-01-31 --dry-run

# clean re-import of a month
TIMEME_PASSWORD=... .venv/bin/python scripts/import_periods.py \
    --base-url http://localhost:8000 --username alice \
    --wipe-range 2026-01-01 2026-01-31 \
    --periods history_periods.csv --marks history_marks.csv
```

Both scripts need only `httpx`, which is already in `requirements-dev.txt`.

## Configuration

All settings are `TIMEME_`-prefixed environment variables; see `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `TIMEME_SECRET_KEY` | — | Signs session cookies. Required. |
| `TIMEME_TIMEZONE` | `Europe/Berlin` | Where day boundaries fall. |
| `TIMEME_DEFAULT_NOMINAL_MINUTES` | `420` | 7:00 per workday. |
| `TIMEME_SESSION_HOURS` | `336` | Session lifetime. |
| `TIMEME_COOKIE_SECURE` | `true` | Set false only for local HTTP. |
| `TIMEME_DB_PATH` | `/data/timeme.db` | SQLite file. |
| `TIMEME_BIND_PORT` | `8787` | Host port Caddy proxies to. |

## Try it locally

`docker-compose.local.dev.yml` is a standalone stack: no Caddy, plain HTTP on
`localhost:8000`, its own volume, and a throwaway secret. Use it on its own —
not combined with `docker-compose.yml`.

```bash
docker compose -f docker-compose.local.dev.yml up --build -d
docker compose -f docker-compose.local.dev.yml exec app \
    python -m app.cli create-user dev --admin --password devpassword
open http://localhost:8000
```

If port 8000 is taken, put `TIMEME_DEV_PORT=8001` in front of the commands (and
adjust the proxy target in `frontend/vite.config.ts` if you use the Vite server).

The backend reloads when you edit `backend/app`. The SPA is baked into the
image, so a frontend change needs `--build` — or run `cd frontend && npm run dev`
for a fast loop, since its dev server proxies `/api` to this container.

To exercise the backup sidecar too (writes into `./backups-dev/`):

```bash
mkdir -p backups-dev && sudo chown 10001:10001 backups-dev
docker compose -f docker-compose.local.dev.yml --profile backup up -d
docker compose -f docker-compose.local.dev.yml logs backup
```

Tear it down, data and all:

```bash
docker compose -f docker-compose.local.dev.yml --profile backup down -v
```

## Local development without Docker

Two terminals:

```bash
# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
TIMEME_DB_PATH=./dev.db TIMEME_COOKIE_SECURE=false TIMEME_STATIC_DIR= \
  .venv/bin/uvicorn app.main:app --reload
# in the same shell, once:
TIMEME_DB_PATH=./dev.db .venv/bin/python -m app.cli create-user dev --admin

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

Tests:

```bash
cd backend && .venv/bin/python -m pytest tests -q
cd frontend && npm run typecheck
```

Interactive API docs are at `/docs` while the backend is running.
