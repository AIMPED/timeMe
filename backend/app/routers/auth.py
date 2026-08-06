from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..calc import load_schedule, today_local
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import LoginRequest, PasswordChange, UserOut
from ..security import COOKIE_NAME, audit, create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(db: Session, user: User) -> UserOut:
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


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> UserOut:
    user = db.scalars(select(User).where(User.username == payload.username)).first()
    # Always run a hash comparison so a missing username and a wrong password
    # take the same amount of time.
    reference = user.password_hash if user else "$2b$12$" + "." * 53
    ok = verify_password(payload.password, reference)
    if not user or not ok or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        create_token(user.id),
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return _user_out(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> UserOut:
    return _user_out(db, user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def change_password(
    payload: PasswordChange,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        entity="user",
        entity_id=user.id,
        action="password_change",
    )
    db.commit()
