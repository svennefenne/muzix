"""Admin mode: hiding, deleting and editing library items, and looking them up elsewhere."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import manage, providers
from ..db import get_db
from ..models import User
from ..security import admin_user

router = APIRouter(prefix="/api/manage", tags=["manage"], dependencies=[Depends(admin_user)])


def _kind(kind: str) -> str:
    if kind not in manage.MODELS:
        raise HTTPException(404, f"Unknown kind of item: {kind}")
    return kind


def _do(fn, *args):
    try:
        return fn(*args)
    except manage.ManageError as e:
        raise HTTPException(409, str(e))


# ---------------------------------------------------------------- hidden things and the trash

@router.get("/hidden")
def hidden():
    return manage.hidden_items()


@router.get("/trash")
def trash():
    return manage.trash_items()


@router.post("/trash/{trash_id}/restore")
def restore(trash_id: int):
    return _do(manage.restore, trash_id)


@router.delete("/trash/{trash_id}")
def empty_one(trash_id: int):
    return {"emptied": manage.empty_trash(trash_id)}


@router.delete("/trash")
def empty_all():
    return {"emptied": manage.empty_trash()}


# ---------------------------------------------------------------- other sources

@router.get("/lookup")
def lookup(kind: str, artist: str = "", title: str = "", album: str = "",
           db: Session = Depends(get_db), user: User = Depends(admin_user)):
    if kind not in ("album", "track", "artist"):
        raise HTTPException(400, "Lookups are for albums, songs and artists")
    return providers.search(kind, artist.strip(), title.strip(), album.strip(), user=user, db=db)


@router.get("/lookup/{source}/{kind}/{id_}")
def lookup_details(source: str, kind: str, id_: str, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    try:
        return providers.details(source, kind, id_, user=user, db=db)
    except providers.SourceError as e:
        raise HTTPException(502, f"{source} {e}")
    except Exception as e:      # the source's answer wasn't what was expected
        raise HTTPException(502, f"{source} isn't answering right now ({type(e).__name__})")


@router.get("/covers")
def covers(kind: str, artist: str = "", title: str = "", web: str = "",
           db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return providers.covers(kind, artist.strip(), title.strip(), web.strip(), user=user, db=db)


# ---------------------------------------------------------------- one item

class Edit(BaseModel):
    fields: dict = {}
    tracks: list[dict] = []      # an album's songs: {id, title, artist, track_no, disc_no}


class CoverUrl(BaseModel):
    url: str


@router.get("/{kind}/{id_}")
def details(kind: str, id_: int):
    return _do(manage.details, _kind(kind), id_)


@router.put("/{kind}/{id_}")
def edit(kind: str, id_: int, body: Edit):
    kind = _kind(kind)
    if kind == "album":
        return _do(manage.edit_album, id_, body.fields, body.tracks)
    if kind == "track":
        return _do(manage.edit_track, id_, body.fields)
    return _do(manage.edit_simple, kind, id_, body.fields)


@router.post("/{kind}/{id_}/hide")
def hide(kind: str, id_: int):
    _do(manage.set_hidden, _kind(kind), id_, True)
    return {"ok": True}


@router.post("/{kind}/{id_}/unhide")
def unhide(kind: str, id_: int):
    _do(manage.set_hidden, _kind(kind), id_, False)
    return {"ok": True}


@router.delete("/{kind}/{id_}")
def delete(kind: str, id_: int):
    return _do(manage.delete_item, _kind(kind), id_)


@router.post("/{kind}/{id_}/cover")
def cover_from_url(kind: str, id_: int, body: CoverUrl):
    kind = _kind(kind)
    if kind in ("podcast", "station"):
        field = "image" if kind == "podcast" else "favicon"
        return _do(manage.edit_simple, kind, id_, {field: body.url})
    return _do(lambda: manage.set_cover(kind, id_, manage.fetch_image(body.url)))


@router.post("/{kind}/{id_}/cover/upload")
async def cover_upload(kind: str, id_: int, file: UploadFile = File(...)):
    data = await file.read(manage.MAX_IMAGE + 1)
    if len(data) > manage.MAX_IMAGE:
        raise HTTPException(413, "That picture is too big")
    return _do(manage.set_cover, _kind(kind), id_, data)
