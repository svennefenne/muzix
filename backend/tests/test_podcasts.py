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


def test_a_podcast_page_sorts_hides_finished_and_counts():
    t0 = datetime.now(timezone.utc) - timedelta(days=100)
    with db.session() as s:
        u = User(username="serial-fan", password_hash="x")
        f = Feed(url="https://example.com/serial.xml", title="Serial")
        s.add_all([u, f])
        s.flush()
        eps = [Episode(feed_id=f.id, guid=f"s{n}", title=f"Part {n}", published=t0 + timedelta(days=n)) for n in range(1, 8)]
        eps.append(Episode(feed_id=f.id, guid="undated", title="Undated"))
        s.add_all(eps)
        s.flush()
        for n in (1, 2, 5):
            s.add(EpisodeProgress(user_id=u.id, episode_id=eps[n - 1].id, position=900, finished=True))
        s.add(EpisodeProgress(user_id=u.id, episode_id=eps[2].id, position=60))       # Part 3: started
        uid, fid = u.id, f.id

    def titles(**kw):
        with db.session() as s:
            page = api.feed(fid, db=s, user=s.get(User, uid), **kw)
            return [e["title"] for e in page["episodes"]], page["total"], page["finished"]

    assert titles() == (["Part 7", "Part 6", "Part 5", "Part 4", "Part 3", "Part 2", "Part 1", "Undated"], 8, 3)
    assert titles(order="oldest")[0] == ["Part 1", "Part 2", "Part 3", "Part 4", "Part 5", "Part 6", "Part 7", "Undated"]
    assert titles(order="oldest", hide_finished=True)[0] == ["Part 3", "Part 4", "Part 6", "Part 7", "Undated"]
    assert titles(order="oldest", hide_finished=True, limit=2) == (["Part 3", "Part 4"], 8, 3)


def test_show_notes_keep_paragraphs_links_and_timestamps_and_nothing_else():
    from muzix.podcasts import show_notes
    html = show_notes('<p>Hi <b>there <a href="https://x.org/?a=1&b=2">site</a></b> at 12:34.</p>'
                      '<script>alert(1)</script><ul><li><a href="javascript:alert(1)" onclick="x">bad</a>'
                      '<img src=x onerror=alert(1)> see https://ex.com/p).</li></ul><p>99:59:59 is too long</p>', 3600)
    assert html == ('<p>Hi <b>there <a href="https://x.org/?a=1&amp;b=2" target="_blank" rel="noopener noreferrer nofollow">site</a></b>'
                    ' at <button type="button" class="ts" data-t="754">12:34</button>.</p>'
                    '<p>• bad see <a href="https://ex.com/p" target="_blank" rel="noopener noreferrer nofollow">https://ex.com/p</a>).</p>'
                    '<p>99:59:59 is too long</p>')
    assert show_notes("One\ntwo\n\n2 < 3 & <tag>", 0) == "<p>One<br>two</p><p>2 &lt; 3 &amp; &lt;tag&gt;</p>"


def test_episodes_read_before_show_notes_were_kept_get_them_from_the_whole_feed():
    import httpx
    from muzix import podcasts
    rss = b"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
      <title>Notes</title>
      <item><guid>n1</guid><title>Old one</title><description>Short.</description>
        <content:encoded><![CDATA[<p>Long notes with <a href="https://ex.org">a link</a>.</p><p>At 1:30 the music.</p>]]></content:encoded>
        <enclosure url="https://ex.org/1.mp3" type="audio/mpeg" length="1"/></item>
      <item><guid>n2</guid><title>New one</title><description>Plain text notes.</description>
        <enclosure url="https://ex.org/2.mp3" type="audio/mpeg" length="1"/></item>
    </channel></rss>"""
    asked = []

    def answer(request):
        asked.append(request.headers.get("if-none-match"))
        return httpx.Response(200, content=rss, headers={"etag": '"v1"'})

    with db.session() as s:
        f = Feed(url="https://ex.org/notes.xml", etag='"v0"')
        s.add(f)
        s.flush()
        s.add(Episode(feed_id=f.id, guid="n1", title="Old one", description="Short."))     # notes None: from before
        s.add(Episode(feed_id=f.id, guid="gone", title="Gone from the feed"))
        fid = f.id
    with httpx.Client(transport=httpx.MockTransport(answer)) as client, db.session() as s:
        podcasts.fetch(s.get(Feed, fid), client)
    assert asked == [None]       # read whole, not "if changed", to fill them in
    with db.session() as s:
        notes = {e.guid: e.notes for e in s.query(Episode).filter_by(feed_id=fid)}
    assert notes == {"n1": '<p>Long notes with <a href="https://ex.org" target="_blank" rel="noopener noreferrer nofollow">a link</a>.</p>'
                           '<p>At <button type="button" class="ts" data-t="90">1:30</button> the music.</p>',
                     "n2": "<p>Plain text notes.</p>", "gone": ""}
    with httpx.Client(transport=httpx.MockTransport(answer)) as client, db.session() as s:
        podcasts.fetch(s.get(Feed, fid), client)
    assert asked == [None, '"v1"']     # all filled in: back to asking only for changes
