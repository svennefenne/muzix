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


def test_bandcamps_tags_are_an_artists_when_musicbrainz_has_none(monkeypatch):
    """The Operator Sound INC.: MusicBrainz has no tags for them, Bandcamp's albums do: those (the most albums'
    first, then in Bandcamp's own order, not where it's from) are their genre tags, after the admin's rules; an
    artist Bandcamp tags psytrance has "psytrance" first; one MusicBrainz has tags for keeps MusicBrainz's."""
    from muzix import enrich, settings
    from muzix.models import Album, BandcampTags

    with db.session() as s:
        s.execute(delete(BandcampTags))
        op = Artist(name="ZQ Operator Sound", tags=[])
        known = Artist(name="ZQ Known Band", tags=[])
        psy = Artist(name="ZQ Migdalor", tags=[])
        s.add_all([op, known, psy])
        s.flush()
        ids = op.id, known.id, psy.id
        s.add_all([Album(title="Esoteric", artist_id=op.id, artist_name=op.name, key="zq-esoteric", kind="music", folder="/zq/e"),
                   Album(title="Known", artist_id=known.id, artist_name=known.name, key="zq-known", kind="music", folder="/zq/k"),
                   Album(title="Planeta", artist_id=psy.id, artist_name=psy.name, key="zq-planeta", kind="music", folder="/zq/p")])
    enrich.keep_bandcamp_tags([
        {"artist": "ZQ Operator Sound", "album": "Esoteric", "tags": ["Electronic", "dungeon synth", "zq hey joe"]},
        {"artist": "zq operator sound", "album": "Second", "tags": ["Electronic", "modular synth"]},
        {"artist": "ZQ Known Band", "album": "Known", "tags": ["Rock"]},
        {"artist": "ZQ Migdalor", "album": "Planeta", "tags": ["Electronic", "Progressive Trance", "Psychedelic Trance", "downtempo"]},
        {"artist": "ZQ Untagged", "album": "Nothing", "tags": []}])
    enrich.keep_bandcamp_tags([{"artist": "ZQ Operator Sound", "album": "Esoteric",       # again: once, as now
                                "tags": ["Electronic", "dungeon synth", "zq hey joe"]}])
    with db.session() as s:
        s.add(TagRule(key="zq hey joe", removed=True))
    monkeypatch.setattr(enrich, "mb_tags", lambda c, l, name, mbid: ([["zq post-rock", 5]], "mb") if "Known" in name else ([], ""))
    monkeypatch.setattr(enrich.RateLimited, "wait", lambda self: None)
    was = settings.get("artist_tags")
    settings.set_many({"artist_tags": "musicbrainz"})
    try:
        enrich.artist_tags(SimpleNamespace(log=lambda *a: None, update=lambda *a: None, check=lambda: None))
    finally:
        settings.set_many({"artist_tags": was})
        with db.session() as s:
            s.execute(delete(BandcampTags))
            s.execute(delete(TagRule).where(TagRule.key == "zq hey joe"))
    assert shown(ids[0])[0] == ["electronic", "dungeon synth", "modular synth"]
    assert shown(ids[1])[0] == ["zq post-rock"]
    assert shown(ids[2])[0] == ["psytrance", "electronic", "progressive trance", "psychedelic trance", "downtempo"]
    with db.session() as s:
        assert dict(s.get(Artist, ids[0]).tags)["electronic"] == 2       # on both their albums


def test_place_names_are_taken_off_everyone_unless_the_admin_put_one_there():
    """The general rule: "finland", "DE", "U.S.A", "british"... off every artist's tags (whole tags only: "finnish
    metal" stays), but one the admin added to an artist; turned off, they're back. Admin → Tags lists them."""
    from muzix import settings
    with db.session() as s:
        a = Artist(name="ZQ Place Band", source_tags=[["british", 100], ["progressive rock", 80], ["UK", 60], ["U.S.A", 50],
                                                       ["finnish metal", 40], ["Estados Unidos", 30]],
                   tag_edits={"add": ["london"]})
        s.add(a)
        s.flush()
        aid = a.id
        tagging.apply(a, tagging.Rules(s))
    assert settings.get("tags_drop_places") is True                     # on from the start
    assert shown(aid)[0] == ["london", "progressive rock", "finnish metal"]
    c = client()
    places = {t["name"]: t["artists"] for t in c.get("/api/admin/tags").json()["places"]["tags"]}
    assert places["british"] >= 1 and "london" not in places and "progressive rock" not in places
    assert c.post("/api/admin/tags/places", json={"on": False}).json()["artists"] >= 1
    try:
        assert shown(aid)[0] == ["london", "british", "progressive rock", "UK", "U.S.A", "finnish metal", "Estados Unidos"]
        assert c.get("/api/admin/tags").json()["places"]["on"] is False
    finally:
        c.post("/api/admin/tags/places", json={"on": True}).raise_for_status()
    assert shown(aid)[0] == ["london", "progressive rock", "finnish metal"]


def test_the_rules_are_applied_once_to_everyone_when_muzix_starts_after_they_change():
    from muzix import settings
    with db.session() as s:
        a = Artist(name="ZQ Old Tags", source_tags=[["swedish", 100], ["death metal", 90]], tags=[["swedish", 100], ["death metal", 90]])
        s.add(a)
        s.flush()
        aid = a.id
    settings.set_many({"tag_rules_applied": ""})
    tagging.catch_up()
    assert shown(aid)[0] == ["death metal"] and settings.get("tag_rules_applied") == tagging.RULES_VERSION
    with db.session() as s:
        s.get(Artist, aid).tags = [["swedish", 100], ["death metal", 90]]
    tagging.catch_up()                                                     # once: not again
    assert shown(aid)[0] == ["swedish", "death metal"]
