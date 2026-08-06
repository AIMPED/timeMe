import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

_settings = get_settings()

_db_dir = os.path.dirname(_settings.db_path)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

engine = create_engine(
    f"sqlite:///{_settings.db_path}",
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    # WAL keeps reads from blocking the clock-in write, and lets the backup
    # script snapshot the file while the app is running.
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
