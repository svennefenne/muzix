"""Accounts and their logins: a browser's cookie, or an app's token (`Authorization: Bearer`)."""

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

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


def new_login(db: Session, user: User, request: Request, name: str = "") -> str:
    """A login for one device: the token it signs in with from now on (one of the account's devices)."""
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token=token, user_id=user.id, name=name[:120],
                       user_agent=(request.headers.get("user-agent") or "")[:255]))
    db.commit()
    return token


def start_session(db: Session, user: User, request: Request, response: Response, name: str = "") -> str:
    token = new_login(db, user, request, name)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=secure, path="/")
    return token


def end_session(db: Session, request: Request, response: Response):
    token = login_token(request)
    if token:
        row = db.get(AuthSession, token)
        if row:
            db.delete(row)
            db.commit()
    response.delete_cookie(COOKIE, path="/")


def login_token(conn: HTTPConnection) -> str | None:
    """The login a request (or WebSocket) comes with: an app's bearer token, or the browser's cookie."""
    auth = conn.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip() or None
    return conn.cookies.get(COOKIE)


def login_id(token: str) -> str:
    """A login as the account's list of devices names it: not the token itself, which signs in."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def device_name(agent: str) -> str:
    """A browser's login as people know it, from its user agent: "Firefox on Linux", "Muzix for Android 0.8.2"."""
    if m := re.search(r"MuzixApp/(\S+)", agent):
        return f"Muzix for Android {m.group(1)}"
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Vivaldi/", "Vivaldi"), ("Firefox/", "Firefox"),
                                           ("Chrome/", "Chrome"), ("Safari/", "Safari")) if key in agent), None)
    if browser is None:         # a program of its own: its name ("curl/8.0": curl)
        return agent.split("/")[0].strip()[:40] or "Unknown device"
    system = next((name for key, name in (("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iPadOS"), ("Windows", "Windows"),
                                          ("Mac OS X", "macOS"), ("CrOS", "ChromeOS"), ("Linux", "Linux")) if key in agent), "")
    return f"{browser} on {system}" if system else browser


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user = session_user(db, login_token(request))
    if user is not None:
        viewing(request, user)
    return user


def viewing(request: Request, user: User):
    """Whose request it is, for what the pages show them (db.py): with their "network" preference
    off, only this server's own library."""
    request.state.network = (user.prefs or {}).get("network", True) is not False


def session_user(db: Session, token: str | None) -> User | None:
    """Whose session `token` is, while it lasts (a WebSocket has no Request to depend on)."""
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
    viewing(request, owner)
    return owner


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admins only")
    return user


def has_users(db: Session) -> bool:
    return db.scalar(select(User.id).limit(1)) is not None
