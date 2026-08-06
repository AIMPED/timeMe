from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..calc import load_schedule, today_local
from ..config import get_settings
from ..db import get_db
from ..deps import current_admin
from ..models import NominalRate, User
from ..schemas import NominalUpdate, PasswordReset, UserCreate, UserOut, UserUpdate
from ..security import audit, hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _out(db: Session, user: User) -> UserOut:
    settings = get_settings()
    schedule = load_schedule(db, user.id, settings.default_nominal_minutes)
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        nominal_minutes=schedule.minutes_for(today_local(settings.tz)),
    )


def _get(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(
    admin: User = Depends(current_admin), db: Session = Depends(get_db)
) -> list[UserOut]:
    users = db.scalars(select(User).order_by(User.username)).all()
    return [_out(db, u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, admin: User = Depends(current_admin), db: Session = Depends(get_db)
) -> UserOut:
    if db.scalars(select(User).where(User.username == payload.username)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or payload.username,
        is_admin=payload.is_admin,
    )
    db.add(user)
    db.flush()
    # The opening rate is backdated so the user's very first days already have
    # a target, rather than falling back to the instance default.
    db.add(
        NominalRate(
            user_id=user.id,
            effective_from=today_local(get_settings().tz).replace(month=1, day=1),
            minutes=payload.nominal_minutes,
        )
    )
    audit(
        db,
        actor_user_id=admin.id,
        subject_user_id=user.id,
        entity="user",
        entity_id=user.id,
        action="create",
        after={"username": user.username, "is_admin": user.is_admin},
    )
    db.commit()
    return _out(db, user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    user = _get(db, user_id)
    before = {
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
    }

    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.is_active is not None:
        user.is_active = payload.is_active

    # Refuse to leave the instance with nobody who can administer it.
    db.flush()
    active_admins = db.scalars(
        select(User).where(User.is_admin.is_(True), User.is_active.is_(True))
    ).all()
    if not active_admins:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There must be at least one active admin")

    audit(
        db,
        actor_user_id=admin.id,
        subject_user_id=user.id,
        entity="user",
        entity_id=user.id,
        action="update",
        before=before,
        after={
            "display_name": user.display_name,
            "is_admin": user.is_admin,
            "is_active": user.is_active,
        },
    )
    db.commit()
    return _out(db, user)


@router.post("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def reset_password(
    user_id: int,
    payload: PasswordReset,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> None:
    user = _get(db, user_id)
    user.password_hash = hash_password(payload.new_password)
    audit(
        db,
        actor_user_id=admin.id,
        subject_user_id=user.id,
        entity="user",
        entity_id=user.id,
        action="password_reset",
    )
    db.commit()


@router.put("/users/{user_id}/nominal", response_model=UserOut)
def set_nominal(
    user_id: int,
    payload: NominalUpdate,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    user = _get(db, user_id)
    existing = db.scalars(
        select(NominalRate).where(
            NominalRate.user_id == user.id, NominalRate.effective_from == payload.effective_from
        )
    ).first()
    before = {"minutes": existing.minutes} if existing else None

    if existing:
        existing.minutes = payload.minutes
    else:
        db.add(
            NominalRate(
                user_id=user.id,
                effective_from=payload.effective_from,
                minutes=payload.minutes,
            )
        )

    audit(
        db,
        actor_user_id=admin.id,
        subject_user_id=user.id,
        entity="nominal_rate",
        entity_id=payload.effective_from.isoformat(),
        action="set",
        before=before,
        after={"minutes": payload.minutes},
    )
    db.commit()
    return _out(db, user)


@router.get("/users/{user_id}/nominal")
def list_nominal(
    user_id: int, admin: User = Depends(current_admin), db: Session = Depends(get_db)
) -> list[dict]:
    _get(db, user_id)
    rates = db.scalars(
        select(NominalRate)
        .where(NominalRate.user_id == user_id)
        .order_by(NominalRate.effective_from)
    ).all()
    return [{"effective_from": r.effective_from, "minutes": r.minutes} for r in rates]
