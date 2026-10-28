"""Spotify's blue dots: new episodes until they're started, and a podcast's dot until its page is opened."""
from datetime import datetime, timedelta, timezone

from muzix import db
from muzix.api import me, podcasts as api
from muzix.models import Episode, EpisodeProgress, Feed, Subscription, User


def test_new_episodes_and_podcasts_get_a_blue_dot():
    t0 = datetime.now(timezone.utc) - timedelta(days=10)
    with db.session() as s:
        u, other = User(username="dot-fan", password_hash="x"), User(username="dot-stranger", password_hash="x")
        f = Feed(url="https://example.com/dots.xml", title="Dots")
        s.add_all([u, other, f])
        s.flush()
        s.add(Subscription(user_id=u.id, feed_id=f.id, created_at=t0))
        eps = {name: Episode(feed_id=f.id, guid=name, title=name, published=t0 + timedelta(days=days), added_at=t0 + timedelta(days=added))
               for name, days, added in [("before", -3, -3), ("after", 2, 2), ("started", 3, 3), ("late find", 4, 6)]}
        s.add_all(eps.values())
        s.flush()
        s.add(EpisodeProgress(user_id=u.id, episode_id=eps["started"].id, position=30))
        uid, oid, fid = u.id, other.id, f.id

    def page(user_id):
        with db.session() as s:
            return api.feed(fid, db=s, user=s.get(User, user_id))

    def dots(user_id):
        with db.session() as s:
            user = s.get(User, user_id)
            listed = {x["id"]: x["new"] for x in api.subscriptions(db=s, user=user)}
            side = {x["id"]: x["new"] for x in me.sidebar(db=s, user=user)["podcasts"]}
            return listed.get(fid), side.get(fid)

    # out since subscribing and not started; a stranger who doesn't subscribe sees none
    assert {e["title"]: e["new"] for e in page(uid)["episodes"]} == {"before": False, "after": True, "started": False, "late find": True}
    assert not any(e["new"] for e in page(oid)["episodes"])
    assert dots(uid) == (True, True)

    # opening the page takes the podcast's dot away, the episodes keep theirs
    with db.session() as s:
        api.seen(fid, db=s, user=s.get(User, uid))
    assert dots(uid) == (False, False)
    assert [e["title"] for e in page(uid)["episodes"] if e["new"]] == ["late find", "after"]

    # an episode found after the visit brings it back, even one that came out before (a slow feed)
    with db.session() as s:
        s.get(Subscription, (uid, fid)).seen_at = t0 + timedelta(days=5)
    assert dots(uid) == (True, True)

    # starting the new ones takes every dot away
    with db.session() as s:
        for name in ("after", "late find"):
            ep = s.query(Episode).filter_by(feed_id=fid, guid=name).one()
            s.add(EpisodeProgress(user_id=uid, episode_id=ep.id, position=5))
    assert dots(uid) == (False, False)
    assert not any(e["new"] for e in page(uid)["episodes"])
