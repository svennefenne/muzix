import os
import subprocess
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import formats, render, settings
from ..db import get_db
from ..models import PlayEvent, Track, User
from ..security import cast_token, current_user, stream_user

router = APIRouter(prefix="/api", tags=["stream"])


def stream_file(path: str, fmt: str, codec: str, sample_rate: int, bit_depth: int,
                q: str = "original", t: float = 0.0):
    """Response for an audio file on disk (shared with audiobooks and podcasts)."""
    if not os.path.exists(path):
        raise HTTPException(404, "The file is gone; rescan the library")
    cast = q == "cast"   # for a Cast speaker: lossless FLAC whenever it can't take the file as it is
    max_rate = render.CAST_MAX_RATE if cast else int(settings.get("max_sample_rate"))
    if not render.needs_transcode(fmt, codec, sample_rate, q) and not t:
        return FileResponse(path, media_type=formats.browser_mime(fmt),
                            headers={"Cache-Control": "private, max-age=3600"})
    if cast:
        target, bit_depth = "flac", min(bit_depth or 16, 24)
    else:
        target = settings.get("transcode_format") if q in ("original", "lossless", "auto") else "opus"
    if q == "low":
        bitrate = 96
    else:
        bitrate = int(settings.get("opus_bitrate"))
    out_rate = max_rate if sample_rate and sample_rate > max_rate else 0
    cmd, mime = render.transcode_args(path, t, target, out_rate, bit_depth, bitrate)
    return _pipe(cmd, mime)


def _pipe(cmd, mime):
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise HTTPException(500, "ffmpeg is not installed")

    def body():
        try:
            while True:
                chunk = proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.kill()
            proc.wait()

    return StreamingResponse(body(), media_type=mime,
                             headers={"X-Muzix-Transcoded": "1", "Cache-Control": "no-store"})


def audio(path: str, fmt: str, codec: str, sample_rate: int, bit_depth: int, subsong: int, duration: float,
          extra: dict, q: str = "original", t: float = 0.0, prefetch: bool = False, learned=None):
    """Audio for a file, from the library or fetched from an online archive: the file itself,
    converted, or rendered when it's a chiptune. `learned(seconds)` hears a Furnace song's
    real length once it has been rendered."""
    fam = formats.family(fmt)
    if fam not in formats.RENDERED:
        if prefetch:
            return Response(status_code=204)
        return stream_file(path, fmt, codec, sample_rate, bit_depth, q, t)

    args = (path, fmt, subsong, duration, extra)
    if fam in render.PROGRESSIVE:
        out, done = render.start_progressive(*args)
        if prefetch:
            return Response(status_code=204)
        if done is not None and not t and q not in ("high", "low"):
            return StreamingResponse(render.follow(out, done), media_type="audio/flac",
                                     headers={"X-Muzix-Transcoded": "1", "Cache-Control": "no-store"})
        if done is not None:
            done.wait(120)
        if not os.path.exists(out):
            raise HTTPException(500, "Rendering failed")
        path = out
    else:
        if prefetch:
            threading.Thread(target=_render_quietly, args=args, daemon=True).start()
            return Response(status_code=204)
        try:
            path, seconds = render.render(*args)
        except render.RenderError as e:
            raise HTTPException(500, str(e))
        if fam == "furnace" and seconds and learned:
            learned(seconds)
    if q in ("high", "low") or t:
        cmd, mime = render.transcode_args(path, t, "opus" if q in ("high", "low") else "flac", 0, 16,
                                          96 if q == "low" else 160)
        return _pipe(cmd, mime)
    return FileResponse(path, media_type="audio/flac", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/stream/{track_id}")
def stream(track_id: int, q: str = "original", t: float = 0.0, prefetch: bool = False,
           db: Session = Depends(get_db), user: User = Depends(stream_user)):
    """Audio for a track. With t > 0 the response starts at that offset."""
    tr = db.get(Track, track_id)
    if tr is None:
        raise HTTPException(404, "No such track")

    def learned(seconds: float):
        if abs((tr.extra or {}).get("rendered", 0) - seconds) > 0.5:
            tr.extra = {**(tr.extra or {}), "rendered": seconds}   # the real length, for display
            db.commit()

    return audio(tr.path, tr.format, tr.codec, tr.sample_rate, tr.bit_depth, tr.subsong, tr.duration,
                 tr.extra, q, t, prefetch, learned)


def _render_quietly(*args):
    try:
        render.render(*args)
    except render.RenderError:
        pass


class Played(BaseModel):
    track_id: int


@router.get("/cast/token")
def cast_link(user: User = Depends(current_user)):
    """A signature for a Cast speaker's audio links (valid for a day)."""
    token, expires = cast_token(user)
    return {"token": token, "expires": expires}


@router.post("/plays")
def played(body: Played, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if db.get(Track, body.track_id) is None:
        raise HTTPException(404, "No such track")
    db.add(PlayEvent(user_id=user.id, track_id=body.track_id))
    db.commit()
    return {"ok": True}
