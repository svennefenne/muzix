"""Admin → Tags: the artists' genre tags removed, renamed and merged, put in categories, and edited
artist by artist; later lookups follow the rules, and each rule can be taken back."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from muzix import db, tagging
from muzix.api import library, tags
from muzix.models import Artist, TagCategory, TagRule
from muzix.security import admin_user


def client():
    app = FastAPI()
    app.include_router(tags.router)
    app.dependency_overrides[admin_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    return TestClient(app)


def shown(aid):
    with db.session() as s:
        a = s.get(Artist, aid)
        return [t for t, _ in a.tags], [t for t, _ in (a.other_tags or [])]


def row(c, name):
    return next((t for t in c.get("/api/admin/tags").json()["tags"] if t["name"] == name), None)


def looked_up(aid, given):
    """The weekly lookup came back with these (enrich.py)."""
    with db.session() as s:
        a = s.get(Artist, aid)
        a.source_tags = given
        tagging.apply(a, tagging.Rules(s))


def test_tags_removed_renamed_merged_and_taken_back():
    with db.session() as s:
        one = Artist(name="Tagged One", tags=[["zq metal", 100], ["zq-hip-hop", 80], ["zq hey joe", 10]])
        two = Artist(name="Tagged Two", tags=[["zq hip hop", 100], ["zq rnb", 50], ["zq metal", 40]])
        s.add_all([one, two])
        s.flush()
        a1, a2 = one.id, two.id
    c = client()
    assert row(c, "zq metal")["artists"] == 2 and row(c, "zq hey joe")["artists"] == 1

    # removed everywhere, and it stays so when the tags are looked up again
    c.post("/api/admin/tags/remove", json={"names": ["zq hey joe"]}).raise_for_status()
    assert shown(a1)[0] == ["zq metal", "zq-hip-hop"]
    assert row(c, "zq hey joe") is None
    assert {"name": "zq hey joe", "artists": 1} in c.get("/api/admin/tags").json()["removed"]
    looked_up(a1, [["zq metal", 100], ["zq hey joe", 90], ["zq-hip-hop", 80]])
    assert shown(a1)[0] == ["zq metal", "zq-hip-hop"]

    # two spellings merged into one: one row, both artists, and the old name noted
    c.post("/api/admin/tags/merge", json={"names": ["zq-hip-hop"], "into": "zq hip hop"}).raise_for_status()
    assert shown(a1)[0] == ["zq metal", "zq hip hop"]
    merged = row(c, "zq hip hop")
    assert merged["artists"] == 2 and merged["aliases"] == ["zq-hip-hop"] and row(c, "zq-hip-hop") is None
    # renamed, spelled as the admin spells it; then merged on into another, the first follows
    c.post("/api/admin/tags/merge", json={"names": ["zq rnb"], "into": "ZQ R&B"}).raise_for_status()
    assert shown(a2)[0] == ["zq hip hop", "ZQ R&B", "zq metal"]
    c.post("/api/admin/tags/merge", json={"names": ["zq hip hop"], "into": "zq rap"}).raise_for_status()
    assert shown(a1)[0] == ["zq metal", "zq rap"] and shown(a2)[0][0] == "zq rap"
    assert row(c, "zq rap")["aliases"] == ["zq hip hop", "zq-hip-hop"]

    # all taken back
    c.post("/api/admin/tags/unmerge", json={"names": ["zq hip hop", "zq-hip-hop"]}).raise_for_status()
    c.post("/api/admin/tags/restore", json={"names": ["zq hey joe"]}).raise_for_status()
    assert shown(a1)[0] == ["zq metal", "zq hey joe", "zq-hip-hop"]
    assert shown(a2)[0] == ["zq hip hop", "ZQ R&B", "zq metal"]
    c.post("/api/admin/tags/unmerge", json={"names": ["zq rnb"]}).raise_for_status()
    assert shown(a2)[0] == ["zq hip hop", "zq rnb", "zq metal"]
    with db.session() as s:
        assert not s.scalars(TagRule.__table__.select().where(TagRule.key.like("zq%"))).all()   # nothing left


def test_categories_shown_apart_or_not_at_all():
    with db.session() as s:
        s.execute(delete(TagCategory).where(TagCategory.name.like("Zq%")))
        a = Artist(name="Swedish Band", tags=[["zq doom", 100], ["zq swedish", 60], ["zq seen live", 20]])
        s.add(a)
        s.flush()
        aid = a.id
    c = client()
    country = c.post("/api/admin/tag-categories", json={"name": "Zq Country"}).json()
    junk = c.post("/api/admin/tag-categories", json={"name": "Zq Junk", "show": "hidden"}).json()
    assert c.post("/api/admin/tag-categories", json={"name": "zq country"}).status_code == 409
    c.post("/api/admin/tags/category", json={"names": ["zq swedish"], "category": country["id"]}).raise_for_status()
    c.post("/api/admin/tags/category", json={"names": ["zq seen live"], "category": junk["id"]}).raise_for_status()
    assert shown(aid) == (["zq doom"], ["zq swedish"])
    assert row(c, "zq seen live")["category"] == junk["id"]       # still listed, to be managed
    with db.session() as s:
        page = library.artist(aid, db=s, user=SimpleNamespace(id=0))
        assert page["tags"] == ["zq doom"] and page["tag_groups"] == [{"name": "Zq Country", "tags": ["zq swedish"]}]
        assert aid in s.scalars(library.tag_artists("Zq Swedish")).all()          # its page finds it

    # shown with the genres after all; then the category goes and its tags are genres again
    c.patch(f"/api/admin/tag-categories/{country['id']}", json={"show": "genre"}).raise_for_status()
    assert shown(aid) == (["zq doom", "zq swedish"], [])
    c.delete(f"/api/admin/tag-categories/{junk['id']}").raise_for_status()
    c.delete(f"/api/admin/tag-categories/{country['id']}").raise_for_status()
    assert shown(aid) == (["zq doom", "zq swedish", "zq seen live"], [])


def test_one_artists_tags_edited():
    with db.session() as s:
        a = Artist(name="Edited Artist", tags=[["zq trance", 100], ["zq goa", 70], ["zq psychedelic", 30]])
        s.add(a)
        s.flush()
        aid = a.id
    c = client()
    got = c.put(f"/api/admin/artists/{aid}/tags", json={"tags": ["zq trance", "zq psytrance", "zq psychedelic"]}).json()
    assert [(t["name"], t["added"]) for t in got["tags"]] == [("zq psytrance", True), ("zq trance", False), ("zq psychedelic", False)]
    assert got["taken_off"] == ["zq goa"]
    # the next lookup brings new tags, and the edits still hold
    looked_up(aid, [["zq trance", 100], ["zq goa", 90], ["zq full-on", 50]])
    assert shown(aid)[0] == ["zq psytrance", "zq trance", "zq full-on"]
    assert c.get("/api/admin/tags/artists", params={"name": "zq goa"}).json()["taken_off"] == [{"id": aid, "name": "Edited Artist"}]
    # given back from the tag's list of artists, and one more taken off there
    c.post(f"/api/admin/artists/{aid}/tags", json={"add": ["zq goa"], "remove": ["zq full-on"]}).raise_for_status()
    assert shown(aid)[0] == ["zq psytrance", "zq trance", "zq goa"]
    # a tag removed everywhere can't be added to one artist without saying so
    c.post("/api/admin/tags/remove", json={"names": ["zq blocked"]}).raise_for_status()
    got = c.post(f"/api/admin/artists/{aid}/tags", json={"add": ["zq blocked"]}).json()
    assert got["removed_everywhere"] == ["zq blocked"] and "zq blocked" not in shown(aid)[0]
    c.post("/api/admin/tags/restore", json={"names": ["zq blocked"]}).raise_for_status()
    assert "zq blocked" in shown(aid)[0]
