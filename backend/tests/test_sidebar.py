"""The library panel (/api/me/sidebar, layout/Sidebar.tsx): its Artists are the ones you follow, then the ones
you've listened to lately; its Latest, what came into the library last and your podcasts' new episodes."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from muzix import db
from muzix.api import me as api
from muzix.models import Album, Artist, Book, Episode, Feed, Like, PlayEvent, Root, Subscription, Track, User

NOW = datetime.now(timezone.utc)


def _library():
    with db.session() as s:
        u = User(username="panel-user", password_hash="x")
        root = Root(path="/panel", kind="music")
        s.add_all([u, root])
        s.flush()
        followed, heard, other = Artist(name="Panel Followed"), Artist(name="Panel Heard"), Artist(name="Panel Unheard")
        s.add_all([followed, heard, other])
        s.flush()
        # the library's newest: an album a day old, a game two days old, a book three days old
        new_album = Album(title="Panel New Album", artist_name=heard.name, artist_id=heard.id, folder="/panel/a", key="panel-a",
                          added_at=NOW - timedelta(days=1))
        new_game = Album(title="Panel New Game", kind="vgm", artist_name="", folder="/panel/g", key="panel-g",
                         added_at=NOW - timedelta(days=2))
        s.add_all([new_album, new_game, Book(root_id=root.id, title="Panel New Book", author="Writer", path="/panel/book",
                                             added_at=NOW - timedelta(days=3))])
        s.flush()
        song = Track(root_id=root.id, path="/panel/a/1.mp3", title="Panel Song", artist=heard.name, album_id=new_album.id,
                     artist_id=heard.id)
        s.add(song)
        s.flush()
        s.add_all([Like(user_id=u.id, item_type="artist", item_id=followed.id),
                   PlayEvent(user_id=u.id, track_id=song.id, played_at=NOW - timedelta(hours=1))])
        # a podcast subscribed to a week ago: an episode out since (new), and one from before it
        feed = Feed(url="https://panel.test/feed", title="Panel Cast")
        s.add(feed)
        s.flush()
        s.add_all([Subscription(user_id=u.id, feed_id=feed.id, created_at=NOW - timedelta(days=7)),
                   Episode(feed_id=feed.id, guid="new", title="Panel New Episode", published=NOW - timedelta(hours=12)),
                   Episode(feed_id=feed.id, guid="old", title="Panel Old Episode", published=NOW - timedelta(days=30))])
        return u.id


def _clean_up():
    """The test database is shared: what's made here would turn up in other tests' lists."""
    with db.session() as s:
        s.execute(delete(Feed).where(Feed.url == "https://panel.test/feed"))
        s.execute(delete(Album).where(Album.key.in_(["panel-a", "panel-g"])))
        s.execute(delete(Artist).where(Artist.name.like("Panel %")))
        s.execute(delete(Root).where(Root.path == "/panel"))
        s.execute(delete(User).where(User.username == "panel-user"))


def test_artists_you_follow_then_those_you_listened_to_and_the_latest():
    uid = _library()
    try:
        with db.session() as s:
            d = api.sidebar(db=s, user=s.get(User, uid))
        assert [a["name"] for a in d["artists"]] == ["Panel Followed", "Panel Heard"]
        # newest first: the episode (12 h), the album (1 day), the game, the book; not the episode from before
        latest = [(x["type"], x["item"]["title"]) for x in d["latest"] if x["item"]["title"].startswith("Panel")]
        assert latest == [("episode", "Panel New Episode"), ("album", "Panel New Album"), ("album", "Panel New Game"),
                          ("book", "Panel New Book")]
        episode = next(x["item"] for x in d["latest"] if x["type"] == "episode")
        assert episode["stream"] and episode["feed_title"] == "Panel Cast"     # ready to play
    finally:
        _clean_up()
