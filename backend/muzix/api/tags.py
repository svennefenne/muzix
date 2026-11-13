"""Admin → Tags: the artists' genre tags (tagging.py), each one removed, renamed or merged into
another, put in a category, and one artist's tags edited."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import db, serial, settings, tagging
from ..models import Artist, TagCategory
from ..security import admin_user

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_user)])

Name = Field(min_length=1, max_length=128)


class Names(BaseModel):
    names: list[str] = Field(min_length=1, max_length=5000)


class Merge(Names):
    into: str = Name


class Categorize(Names):
    category: int | None = None


class Category(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    show: Literal["genre", "apart", "hidden"] = "apart"


class CategoryChange(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    show: Literal["genre", "apart", "hidden"] | None = None


class ArtistTags(BaseModel):
    tags: list[str] = Field(max_length=100)


class ArtistEdit(BaseModel):
    add: list[str] = Field([], max_length=100)
    remove: list[str] = Field([], max_length=100)


def _changed(n: int) -> dict:
    return {"artists": n}


@router.get("/tags")
def tags():
    with db.session() as s:
        return tagging.overview(s)


class Places(BaseModel):
    on: bool


@router.post("/tags/places")
def places(body: Places):
    """The general rule: place names taken off every artist's tags, or (off) back."""
    settings.set_many({"tags_drop_places": body.on})
    with db.session() as s:
        return _changed(tagging.apply_all(s))


@router.get("/tags/artists")
def tag_artists(name: str):
    with db.session() as s:
        got = tagging.carriers(s, name)
    for a in got["artists"]:
        a["art"] = serial.art_url("artist", a["id"])
    return got


@router.post("/tags/remove")
def remove(body: Names):
    with db.session() as s:
        return _changed(tagging.change(s, remove=body.names))


@router.post("/tags/restore")
def restore(body: Names):
    with db.session() as s:
        return _changed(tagging.change(s, restore=body.names))


@router.post("/tags/merge")
def merge(body: Merge):
    """Renames tags into one: an existing tag merges them, a new name renames them."""
    if not body.into.strip():
        raise HTTPException(400, "A name is needed")
    with db.session() as s:
        return _changed(tagging.change(s, merge=body.names, into=body.into))


@router.post("/tags/unmerge")
def unmerge(body: Names):
    with db.session() as s:
        return _changed(tagging.change(s, unmerge=body.names))


@router.post("/tags/category")
def categorize(body: Categorize):
    with db.session() as s:
        try:
            return _changed(tagging.change(s, categorize=body.names, category=body.category))
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/tag-categories")
def add_category(body: Category):
    name = body.name.strip()
    with db.session() as s:
        if not name or s.scalar(select(TagCategory).where(func.casefold(TagCategory.name) == name.casefold())):
            raise HTTPException(409, f"There's a category called {name} already")
        c = TagCategory(name=name, show=body.show)
        s.add(c)
        s.flush()
        return {"id": c.id, "name": c.name, "show": c.show}


@router.patch("/tag-categories/{cid}")
def change_category(cid: int, body: CategoryChange):
    with db.session() as s:
        c = s.get(TagCategory, cid)
        if c is None:
            raise HTTPException(404, "No such category")
        if body.name is not None and body.name.strip():
            name = body.name.strip()
            if s.scalar(select(TagCategory).where(func.casefold(TagCategory.name) == name.casefold(), TagCategory.id != cid)):
                raise HTTPException(409, f"There's a category called {name} already")
            c.name = name
        if body.show is not None:
            c.show = body.show
        s.flush()
        return _changed(tagging.apply_all(s))


@router.delete("/tag-categories/{cid}")
def delete_category(cid: int):
    """Its tags go back among the genres."""
    with db.session() as s:
        if s.get(TagCategory, cid) is None:
            raise HTTPException(404, "No such category")
        return _changed(tagging.delete_category(s, cid))


def _artist(s, artist_id: int) -> Artist:
    a = s.get(Artist, artist_id)
    if a is None:
        raise HTTPException(404, "No such artist")
    return a


@router.get("/artists/{artist_id}/tags")
def artist_tags(artist_id: int):
    with db.session() as s:
        a = _artist(s, artist_id)
        return {"id": a.id, "name": a.name, **tagging.artist_tags(s, a)}


@router.put("/artists/{artist_id}/tags")
def set_artist_tags(artist_id: int, body: ArtistTags):
    """The artist's tags as its editor shows them; returns them as they are now, and those that
    won't show (removed everywhere)."""
    with db.session() as s:
        a = _artist(s, artist_id)
        hidden = tagging.set_artist_tags(s, a, body.tags)
        return {"id": a.id, "name": a.name, **tagging.artist_tags(s, a), "removed_everywhere": hidden}


@router.post("/artists/{artist_id}/tags")
def edit_artist_tags(artist_id: int, body: ArtistEdit):
    """Adds tags to one artist or takes them off it, its others as they are."""
    with db.session() as s:
        a = _artist(s, artist_id)
        hidden = tagging.edit_artist_tags(s, a, body.add, body.remove)
        return {"id": a.id, "name": a.name, **tagging.artist_tags(s, a), "removed_everywhere": hidden}
