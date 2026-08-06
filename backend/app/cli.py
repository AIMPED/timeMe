"""Admin CLI — the way the first account gets created.

    docker compose exec app python -m app.cli create-user alice --admin
    docker compose exec app python -m app.cli list-users
    docker compose exec app python -m app.cli reset-password alice
    docker compose exec app python -m app.cli set-nominal alice 7.5
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import date

from sqlalchemy import select

from .calc import load_schedule, today_local
from .config import get_settings
from .db import SessionLocal, init_db
from .models import NominalRate, User
from .security import hash_password


def _prompt_password(confirm: bool = True) -> str:
    while True:
        pw = getpass.getpass("Password: ")
        if len(pw) < 8:
            print("Password must be at least 8 characters.", file=sys.stderr)
            continue
        if confirm and pw != getpass.getpass("Repeat: "):
            print("Passwords did not match.", file=sys.stderr)
            continue
        return pw


def _find(db, username: str) -> User:
    user = db.scalars(select(User).where(User.username == username)).first()
    if user is None:
        sys.exit(f"No such user: {username}")
    return user


def cmd_create_user(args) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        if db.scalars(select(User).where(User.username == args.username)).first():
            sys.exit(f"User {args.username} already exists")
        password = args.password or _prompt_password()
        minutes = int(round(args.hours * 60)) if args.hours else settings.default_nominal_minutes
        user = User(
            username=args.username,
            password_hash=hash_password(password),
            display_name=args.name or args.username,
            is_admin=args.admin,
        )
        db.add(user)
        db.flush()
        db.add(
            NominalRate(
                user_id=user.id,
                effective_from=date(today_local(settings.tz).year, 1, 1),
                minutes=minutes,
            )
        )
        db.commit()
        role = "admin" if args.admin else "user"
        print(f"Created {role} {user.username} with {minutes / 60:g}h/day nominal.")


def cmd_list_users(_args) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.username)).all()
        if not users:
            print("No users yet. Create one with: python -m app.cli create-user <name> --admin")
            return
        print(f"{'USERNAME':<20} {'ADMIN':<6} {'ACTIVE':<7} {'NOMINAL':<8} NAME")
        for u in users:
            nominal = load_schedule(db, u.id, settings.default_nominal_minutes).minutes_for(
                today_local(settings.tz)
            )
            print(
                f"{u.username:<20} {'yes' if u.is_admin else '-':<6} "
                f"{'yes' if u.is_active else 'no':<7} {nominal / 60:<8.2f} {u.display_name}"
            )


def cmd_reset_password(args) -> None:
    with SessionLocal() as db:
        user = _find(db, args.username)
        user.password_hash = hash_password(args.password or _prompt_password())
        db.commit()
        print(f"Password updated for {user.username}.")


def cmd_set_nominal(args) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        user = _find(db, args.username)
        effective = (
            date.fromisoformat(args.effective_from)
            if args.effective_from
            else today_local(settings.tz)
        )
        minutes = int(round(args.hours * 60))
        existing = db.scalars(
            select(NominalRate).where(
                NominalRate.user_id == user.id, NominalRate.effective_from == effective
            )
        ).first()
        if existing:
            existing.minutes = minutes
        else:
            db.add(NominalRate(user_id=user.id, effective_from=effective, minutes=minutes))
        db.commit()
        print(f"{user.username}: {args.hours:g}h/day from {effective.isoformat()} onwards.")


def cmd_set_active(args) -> None:
    with SessionLocal() as db:
        user = _find(db, args.username)
        user.is_active = args.state == "enable"
        db.commit()
        print(f"{user.username} is now {'active' if user.is_active else 'disabled'}.")


def main(argv: list[str] | None = None) -> None:
    init_db()

    parser = argparse.ArgumentParser(prog="app.cli", description="timeMe administration")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="create an account")
    p.add_argument("username")
    p.add_argument("--password", help="read from a prompt if omitted")
    p.add_argument("--name", help="display name")
    p.add_argument("--admin", action="store_true")
    p.add_argument("--hours", type=float, help="nominal hours per workday")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("list-users")
    p.set_defaults(func=cmd_list_users)

    p = sub.add_parser("reset-password")
    p.add_argument("username")
    p.add_argument("--password", help="read from a prompt if omitted")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("set-nominal", help="change nominal hours from a date onwards")
    p.add_argument("username")
    p.add_argument("hours", type=float)
    p.add_argument("--effective-from", help="YYYY-MM-DD, defaults to today")
    p.set_defaults(func=cmd_set_nominal)

    p = sub.add_parser("set-active")
    p.add_argument("username")
    p.add_argument("state", choices=["enable", "disable"])
    p.set_defaults(func=cmd_set_active)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
