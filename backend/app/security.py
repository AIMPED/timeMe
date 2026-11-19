from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuditLog

COOKIE_NAME = "timeme_session"
ALGORITHM = "HS256"


class LoginThrottle:
    """Counts failed logins per client and blocks once a client has too many.

    Kept in memory: the app runs as a single uvicorn process, and a restart
    forgetting the counts only gives a guesser a fresh window.
    """

    # Above this many tracked clients, expired entries are swept on each
    # failure so rotating addresses cannot grow the table without bound.
    _SWEEP_ABOVE = 10_000

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float] | None:
        stamps = self._failures.get(key)
        if stamps is None:
            return None
        while stamps and stamps[0] <= now - self.window:
            stamps.popleft()
        if not stamps:
            del self._failures[key]
            return None
        return stamps

    def retry_after(self, key: str) -> int:
        """Seconds until `key` may try again, or 0 if it is not blocked."""
        now = time.monotonic()
        with self._lock:
            stamps = self._recent(key, now)
            if stamps is None or len(stamps) < self.max_failures:
                return 0
            return max(1, math.ceil(stamps[0] + self.window - now))

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._failures) > self._SWEEP_ABOVE:
                for k in list(self._failures):
                    self._recent(k, now)
            self._failures.setdefault(key, deque()).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


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
