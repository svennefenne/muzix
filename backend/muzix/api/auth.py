import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__, env, jobs, settings
from ..db import get_db
from ..models import Root, User
from ..security import (check_password, end_session, has_users, hash_password, optional_user,
                        start_session)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def user_json(u: User | None):
    if u is None:
        return None
    return {"id": u.id, "username": u.username, "is_admin": u.is_admin, "prefs": u.prefs or {}}


@router.get("/state")
def state(db: Session = Depends(get_db), user: User | None = Depends(optional_user)):
    return {
        "needs_setup": not has_users(db),
        "user": user_json(user),
        "site_name": settings.get("site_name"),
        "allow_signup": settings.get("allow_signup"),
        "version": __version__,
        "defaults": {"scheme": settings.get("default_scheme"), "mode": settings.get("default_mode"),
                     "genre_skins": settings.get("genre_skins")},
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
    add_default_roots(db)
    start_session(db, user, request, response)
    jobs.submit("scan", "First library scan")
    return {"user": user_json(user)}


def add_default_roots(db: Session):
    """Register the folders the container mounts, if they exist and aren't known yet."""
    for item in env.DEFAULT_ROOTS.split(","):
        if ":" not in item:
            continue
        path, kind = item.rsplit(":", 1)
        path = path.rstrip("/") or "/"
        if not os.path.isdir(path) or db.scalar(select(Root.id).where(Root.path == path)):
            continue
        excludes = [d for d in ("Other formats", "Duplicates") if os.path.isdir(os.path.join(path, d))]
        db.add(Root(path=path, kind=kind, name=os.path.basename(path) or path,
                    excludes=excludes, upload_target=(kind == "music")))
    db.commit()


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.casefold(User.username) == body.username.strip().casefold()))
    if user is None or not check_password(user, body.password):
        raise HTTPException(401, "Wrong username or password")
    start_session(db, user, request, response)
    return {"user": user_json(user)}


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
    start_session(db, user, request, response)
    return {"user": user_json(user)}
