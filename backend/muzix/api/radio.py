"""Internet radio: radio-browser.info directory, saved stations, and a stream relay
that strips ICY metadata out of the audio and remembers the current song title."""

import random
import re
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__, settings
from ..db import get_db
from ..models import Station, User
from ..security import current_user, stream_user
from .proxy import check_url

router = APIRouter(prefix="/api/radio", tags=["radio"])
UA = f"Muzix/{__version__}"
_servers: list[str] = []
_servers_at = 0.0
now_playing: dict[str, tuple[str, float]] = {}   # stream url -> (title, when)


def rb_servers() -> list[str]:
    global _servers, _servers_at
    if _servers and time.time() - _servers_at < 3600:
        return _servers
    try:
        r = httpx.get("https://all.api.radio-browser.info/json/servers", timeout=10, headers={"User-Agent": UA})
        names = sorted({s["name"] for s in r.json()})
        if names:
            _servers, _servers_at = [f"https://{n}" for n in names], time.time()
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return _servers or ["https://de1.api.radio-browser.info", "https://fi1.api.radio-browser.info"]


def rb(path: str, params: dict | None = None):
    servers = rb_servers()[:]
    random.shuffle(servers)
    last = None
    for base in servers[:3]:
        try:
            r = httpx.get(base + path, params=params, timeout=12, headers={"User-Agent": UA})
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            last = e
    raise HTTPException(502, f"The radio directory isn't answering ({last})")


def station_json(s: dict) -> dict:
    return {"uuid": s.get("stationuuid"), "name": (s.get("name") or "").strip(),
            "url": s.get("url_resolved") or s.get("url"), "homepage": s.get("homepage"),
            "favicon": s.get("favicon"), "tags": s.get("tags", ""), "country": s.get("country", ""),
            "countrycode": s.get("countrycode", ""), "codec": s.get("codec", ""),
            "bitrate": s.get("bitrate", 0), "votes": s.get("votes", 0), "hls": bool(s.get("hls"))}


@router.get("/search")
def search(q: str = "", tag: str = "", country: str = "", limit: int = 60, user: User = Depends(current_user)):
    params = {"limit": min(limit, 200), "hidebroken": "true", "order": "clickcount", "reverse": "true"}
    if q:
        params["name"] = q
    if tag:
        params["tag"] = tag
    if country:
        params["countrycode"] = country
    return [station_json(s) for s in rb("/json/stations/search", params)]


@router.get("/top")
def top(user: User = Depends(current_user)):
    country = settings.get("radio_country")
    out = {"top": [station_json(s) for s in rb("/json/stations/topclick/40", {"hidebroken": "true"})]}
    if country:
        out["local"] = [station_json(s) for s in rb("/json/stations/search", {
            "countrycode": country, "order": "clickcount", "reverse": "true", "limit": 40, "hidebroken": "true"})]
    return out


@router.get("/tags")
def tags(user: User = Depends(current_user)):
    return [{"name": t["name"], "stations": t["stationcount"]}
            for t in rb("/json/tags", {"order": "stationcount", "reverse": "true", "limit": 80, "hidebroken": "true"})]


# ---------------------------------------------------------------- saved stations

class StationBody(BaseModel):
    name: str
    url: str
    uuid: str = ""
    homepage: str = ""
    favicon: str = ""
    tags: str = ""
    country: str = ""
    codec: str = ""
    bitrate: int = 0


def saved_json(s: Station):
    return {"id": s.id, "uuid": s.uuid, "name": s.name, "url": s.url, "homepage": s.homepage,
            "favicon": s.favicon, "tags": s.tags, "country": s.country, "codec": s.codec, "bitrate": s.bitrate}


@router.get("/stations")
def saved(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [saved_json(s) for s in db.scalars(select(Station).where(Station.user_id == user.id).order_by(Station.name))]


@router.post("/stations")
def save(body: StationBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_url(body.url)
    s = Station(user_id=user.id, **body.model_dump())
    db.add(s)
    db.commit()
    if body.uuid:
        try:   # tell radio-browser someone liked it, as their API asks
            rb(f"/json/vote/{body.uuid}")
        except HTTPException:
            pass
    return saved_json(s)


@router.delete("/stations/{station_id}")
def remove(station_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = db.get(Station, station_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such station")
    db.delete(s)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- playing

def resolve_playlist(url: str, client: httpx.Client) -> str:
    """.pls / .m3u station links point at the real stream."""
    low = url.lower().split("?")[0]
    if not low.endswith((".pls", ".m3u")):
        return url
    r = client.get(url, follow_redirects=True)
    for line in r.text.splitlines():
        line = line.strip()
        m = re.match(r"^File\d+=(.+)$", line, re.I)
        if m:
            return m.group(1).strip()
        if line.startswith("http"):
            return line
    return url


@router.get("/play")
def play(url: str, uuid: str = "", user: User = Depends(stream_user)):
    check_url(url)
    if uuid:
        try:
            rb(f"/json/url/{uuid}")   # click counter, as radio-browser asks of clients
        except HTTPException:
            pass
    key = url   # now-playing titles are kept under the address the client asked for
    client = httpx.Client(timeout=httpx.Timeout(15, read=60), follow_redirects=True, headers={"User-Agent": UA})
    try:
        url = resolve_playlist(url, client)
        req = client.build_request("GET", url, headers={"Icy-MetaData": "1"})
        upstream = client.send(req, stream=True)
    except httpx.HTTPError as e:
        client.close()
        raise HTTPException(502, f"The station isn't answering: {e}")
    if upstream.status_code >= 400:
        upstream.close()
        client.close()
        raise HTTPException(502, f"The station answered {upstream.status_code}")
    metaint = int(upstream.headers.get("icy-metaint") or 0)
    ctype = upstream.headers.get("content-type", "audio/mpeg").split(";")[0]
    if ctype in ("application/octet-stream", "text/plain", ""):
        ctype = "audio/mpeg"

    def body():
        try:
            if not metaint:
                for chunk in upstream.iter_raw(32 * 1024):
                    yield chunk
                return
            buf = b""
            left = metaint
            for chunk in upstream.iter_raw(32 * 1024):
                buf += chunk
                out = b""
                while buf:
                    if left > 0:
                        take = buf[:left]
                        out += take
                        buf = buf[len(take):]
                        left -= len(take)
                    else:
                        size = buf[0] * 16
                        if len(buf) < 1 + size:
                            break
                        meta = buf[1:1 + size].rstrip(b"\0").decode("utf-8", "replace")
                        m = re.search(r"StreamTitle='(.*?)';", meta)
                        if m and m.group(1).strip():
                            now_playing[key] = (m.group(1).strip(), time.time())
                        buf = buf[1 + size:]
                        left = metaint
                if out:
                    yield out
        finally:
            upstream.close()
            client.close()

    name = upstream.headers.get("icy-name", "")
    return StreamingResponse(body(), media_type=ctype, headers={
        "Cache-Control": "no-store", "X-Station-Name": name.encode("latin-1", "replace").decode("latin-1")})


@router.get("/nowplaying")
def nowplaying(url: str, user: User = Depends(current_user)):
    title, when = now_playing.get(url, ("", 0))
    return {"title": title, "since": when}
