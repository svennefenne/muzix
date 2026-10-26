"""Online archives (HVSC, Modland, ASMA, the Joshw game rips, scene.org): browsing and playing."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import online
from ..models import User
from ..security import current_user, stream_user
from .stream import audio

router = APIRouter(prefix="/api/online", tags=["online"])


def _source(sid: str) -> online.Source:
    try:
        return online.source(sid)
    except online.OnlineError as e:
        raise HTTPException(404, str(e))


@router.get("/sources")
def sources(user: User = Depends(current_user)):
    return [{"id": s.id, "name": s.name, "label": s.label, "about": s.about, "system": s.system,
             "home": s.base, "starts": [{"name": n, "path": p} for n, p in s.starts]}
            for s in online.SOURCES]


@router.get("/list")
async def listing(source: str, path: str = "", page: int = 0, user: User = Depends(current_user)):
    src = _source(source)
    try:
        return await run_in_threadpool(online.listing, src, path, page)
    except online.OnlineError as e:
        raise HTTPException(502, str(e))


class OpenIn(BaseModel):
    source: str
    path: str


@router.post("/open")
async def open_file(body: OpenIn, user: User = Depends(current_user)):
    """The tunes in one file or archive (downloading it on the way)."""
    src = _source(body.source)
    try:
        opened = await run_in_threadpool(online.open_file, src, body.path)
    except online.OnlineError as e:
        raise HTTPException(502, str(e))
    return {"title": opened.title, "tracks": [online.serial(src, body.path, r) for r in opened.rows]}


@router.get("/stream")
def stream(source: str, path: str, member: str = "", sub: int = -1, q: str = "original", t: float = 0.0,
           prefetch: bool = False, user: User = Depends(stream_user)):
    src = _source(source)
    try:
        row = online.find(src, path, member, sub)
    except online.OnlineError as e:
        raise HTTPException(502, str(e))
    def learned(changes: dict):
        row["extra"] = {**(row.get("extra") or {}), **changes}    # kept while the file stays open

    return audio(row["local"], row["format"], row.get("codec") or "", row.get("sample_rate") or 0,
                 row.get("bit_depth") or 0, row["subsong"], row["duration"], row.get("extra"), q, t, prefetch,
                 learned)
