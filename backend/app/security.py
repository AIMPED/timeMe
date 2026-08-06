from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuditLog

COOKIE_NAME = "timeme_session"
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash in the DB — treat as a failed login, never as a pass.
        return False


def create_token(user_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.session_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def audit(
    db: Session,
    *,
    actor_user_id: int | None,
    subject_user_id: int | None,
    entity: str,
    entity_id: str | int = "",
    action: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            subject_user_id=subject_user_id,
            entity=entity,
            entity_id=str(entity_id),
            action=action,
            before=json.dumps(before, default=str) if before is not None else None,
            after=json.dumps(after, default=str) if after is not None else None,
        )
    )
