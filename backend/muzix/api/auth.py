from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__, modules, settings
from ..db import get_db
from ..models import User
from ..security import (check_password, end_session, has_users, hash_password, login_token, new_login,
                        optional_user, start_session)
from . import setup as first_setup
from .me import device_prefs

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    device: str = Field("", max_length=120)     # an app's name for its device, as the account's list of devices shows it


def user_json(db: Session, u: User | None, token: str | None):
    """The account as the UI knows it, with the settings of the device signed in with `token`."""
    if u is None:
        return None
    return {"id": u.id, "username": u.username, "is_admin": u.is_admin, "prefs": device_prefs(db, u, token)}


@router.get("/state")
def state(request: Request, db: Session = Depends(get_db), user: User | None = Depends(optional_user)):
    return {
        "needs_setup": not has_users(db),
        # the admin account is there; the rest of the setup isn't done (api/setup.py)
        "setup": bool(user and user.is_admin and first_setup.pending()),
        "modules": modules.states(),
        "user": user_json(db, user, login_token(request)),
        "site_name": settings.get("site_name"),
        "allow_signup": settings.get("allow_signup"),
        "version": __version__,
    }


@router.post("/setup")
def setup(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    if has_users(db):
        raise HTTPException(409, "Muzix is already set up")
    if len(body.password) < 6:
        raise HTTPException(400, "Use at least 6 characters for the password")
    user = User(username=body.username.strip(), password_hash=hash_password(body.password), is_admin=True)
    db.add(user)
    db.commit()
    first_setup.begin()          # the library's folders and the modules come next
    token = start_session(db, user, request, response, body.device.strip())
    return {"user": user_json(db, user, token)}


def _signing_in(db: Session, body: Credentials) -> User:
    user = db.scalar(select(User).where(func.casefold(User.username) == body.username.strip().casefold()))
    if user is None or not check_password(user, body.password):
        raise HTTPException(401, "Wrong username or password")
    return user


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _signing_in(db, body)
    token = start_session(db, user, request, response, body.device.strip())
    return {"user": user_json(db, user, token)}


@router.post("/token")
def app_login(body: Credentials, request: Request, db: Session = Depends(get_db)):
    """An app signs in: a token of the device's own, sent as `Authorization: Bearer <token>` from then on
    (the API, streams, Connect). Signed out from the account's list of devices, or by /logout with it."""
    user = _signing_in(db, body)
    token = new_login(db, user, request, body.device.strip())
    return {"token": token, "user": user_json(db, user, token)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(db, request, response)
    return {"ok": True}


@router.post("/signup")
def signup(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    if not settings.get("allow_signup"):
        raise HTTPException(403, "Sign-up is turned off")
    if db.scalar(select(User.id).where(func.casefold(User.username) == body.username.strip().casefold())):
        raise HTTPException(409, "That username is taken")
    if len(body.password) < 6:
        raise HTTPException(400, "Use at least 6 characters for the password")
    user = User(username=body.username.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    token = start_session(db, user, request, response, body.device.strip())
    return {"user": user_json(db, user, token)}
