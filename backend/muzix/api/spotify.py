"""Spotify: sign-in (Authorization Code + PKCE), token refresh, unlinking.

The browser then talks to the Spotify Web API and Web Playback SDK directly
with the access token from /api/spotify/token.
"""

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import settings
from ..db import get_db
from ..models import SpotifyLink, User
from ..security import current_user

router = APIRouter(prefix="/api/spotify", tags=["spotify"])
SCOPES = ("streaming user-read-email user-read-private user-read-playback-state user-modify-playback-state "
          "user-read-currently-playing user-library-read user-library-modify playlist-read-private "
          "playlist-read-collaborative user-read-recently-played user-top-read user-follow-read")
_pending: dict[str, tuple[int, str, float]] = {}   # state -> (user id, verifier, created)


def redirect_uri(request: Request) -> str:
    base = (settings.get("public_url") or "").rstrip("/")
    if not base:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        base = f"{proto}://{host}"
    return f"{base}/api/spotify/callback"


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    link = db.get(SpotifyLink, user.id)
    return {"configured": bool(settings.get("spotify_client_id")), "linked": bool(link and link.refresh_token),
            "display_name": link.display_name if link else "", "product": link.product if link else "",
            "redirect_uri": redirect_uri(request)}


@router.get("/login")
def login(request: Request, user: User = Depends(current_user)):
    client_id = settings.get("spotify_client_id")
    if not client_id:
        raise HTTPException(400, "Add your Spotify client ID on the admin page first")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    now = time.time()
    for k in [k for k, v in _pending.items() if now - v[2] > 600]:
        _pending.pop(k, None)
    _pending[state] = (user.id, verifier, now)
    q = urlencode({"client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri(request),
                   "code_challenge_method": "S256", "code_challenge": challenge, "state": state, "scope": SCOPES})
    return RedirectResponse(f"https://accounts.spotify.com/authorize?{q}")


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    pending = _pending.pop(state, None)
    if error or pending is None:
        return RedirectResponse(f"/spotify?error={error or 'expired'}")
    user_id, verifier, _ = pending
    r = httpx.post("https://accounts.spotify.com/api/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(request),
        "client_id": settings.get("spotify_client_id"), "code_verifier": verifier}, timeout=20)
    if r.status_code != 200:
        return RedirectResponse(f"/spotify?error={r.json().get('error', 'token')}")
    tok = r.json()
    me = httpx.get("https://api.spotify.com/v1/me", headers={"Authorization": f"Bearer {tok['access_token']}"},
                   timeout=20).json()
    link = db.get(SpotifyLink, user_id) or SpotifyLink(user_id=user_id)
    link.access_token, link.refresh_token = tok["access_token"], tok.get("refresh_token", "")
    link.expires_at, link.scope = time.time() + tok.get("expires_in", 3600) - 60, tok.get("scope", "")
    link.display_name, link.product = me.get("display_name") or me.get("id", ""), me.get("product", "")
    db.merge(link)
    db.commit()
    return RedirectResponse("/spotify")


@router.get("/token")
def token(db: Session = Depends(get_db), user: User = Depends(current_user)):
    link = db.get(SpotifyLink, user.id)
    if link is None or not link.refresh_token:
        raise HTTPException(401, "Spotify isn't linked")
    if time.time() >= link.expires_at:
        r = httpx.post("https://accounts.spotify.com/api/token", data={
            "grant_type": "refresh_token", "refresh_token": link.refresh_token,
            "client_id": settings.get("spotify_client_id")}, timeout=20)
        if r.status_code != 200:
            raise HTTPException(401, "Spotify sign-in expired; link it again")
        tok = r.json()
        link.access_token = tok["access_token"]
        link.refresh_token = tok.get("refresh_token") or link.refresh_token
        link.expires_at = time.time() + tok.get("expires_in", 3600) - 60
        db.commit()
    return {"access_token": link.access_token, "expires_at": link.expires_at, "product": link.product}


@router.delete("/link")
def unlink(db: Session = Depends(get_db), user: User = Depends(current_user)):
    link = db.get(SpotifyLink, user.id)
    if link is not None:
        db.delete(link)
        db.commit()
    return {"ok": True}
