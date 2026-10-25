"""Accounts and cookie sessions."""

import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import env
from .db import get_db
from .models import AuthSession, User

COOKIE = "muzix_session"
SESSION_DAYS = 60
_hasher = PasswordHasher()


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def check_password(user: User, pw: str) -> bool:
    try:
        return _hasher.verify(user.password_hash, pw)
    except VerifyMismatchError:
        return False


def start_session(db: Session, user: User, request: Request, response: Response):
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token=token, user_id=user.id,
                       user_agent=(request.headers.get("user-agent") or "")[:255]))
    db.commit()
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=secure, path="/")


def end_session(db: Session, request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        row = db.get(AuthSession, token)
        if row:
            db.delete(row)
            db.commit()
    response.delete_cookie(COOKIE, path="/")


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    sess = db.get(AuthSession, token)
    if sess is None:
        return None
    nowt = datetime.now(timezone.utc)
    last = sess.last_seen if sess.last_seen.tzinfo else sess.last_seen.replace(tzinfo=timezone.utc)
    if nowt - last > timedelta(days=SESSION_DAYS):
        db.delete(sess)
        db.commit()
        return None
    if nowt - last > timedelta(minutes=10):
        sess.last_seen = nowt
        db.commit()
    return sess.user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "Not signed in")
    return user


# ---------------------------------------------------------------- cast links
# A Cast speaker fetches the audio itself and has no cookie, so its links carry a signature
# (?ct=user.expiry.mac) that only the audio streams accept.

CAST_HOURS = 24


def _cast_mac(uid: int, exp: int) -> str:
    mac = hmac.new(env.secret_key(), f"cast:{uid}:{exp}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:18]).decode()


def cast_token(user: User) -> tuple[str, int]:
    exp = int(time.time()) + CAST_HOURS * 3600
    return f"{user.id}.{exp}.{_cast_mac(user.id, exp)}", exp


def stream_user(request: Request, db: Session = Depends(get_db),
                user: User | None = Depends(optional_user)) -> User:
    """The signed-in user, or for an audio stream, the user a valid cast link was made for."""
    if user is not None:
        return user
    try:
        uid, exp, mac = request.query_params.get("ct", "").split(".")
        uid, exp = int(uid), int(exp)
    except ValueError:
        raise HTTPException(401, "Not signed in")
    if exp < time.time() or not hmac.compare_digest(mac, _cast_mac(uid, exp)):
        raise HTTPException(401, "This cast link has expired")
    owner = db.get(User, uid)
    if owner is None:
        raise HTTPException(401, "Not signed in")
    return owner


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admins only")
    return user


def has_users(db: Session) -> bool:
    return db.scalar(select(User.id).limit(1)) is not None
