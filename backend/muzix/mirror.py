"""The libraries of the Library Network (network.py links the servers): what this server shares
with the ones it's linked with, and their catalogs mirrored here.

A linked server's artists, albums, songs, chiptunes, audiobooks and playlist files are kept in
the same tables as this server's own, so search, artist pages, likes, playlists and radio take
them as they come. Its rows hang off a root of kind "peer" (path peer:<its id>), which takes them
along when it goes, and carry its peer_id; their paths (peer:<its id>/tracks/<its track id>) say
where on it they are. Artists are shared: a name both libraries have is one artist here.

Only a server's own library is shared on, never what it mirrors from others, and nothing its
admin hid. A sync fetches the whole catalog (a page at a time) and changes here what changed
there, so what's liked or in a playlist keeps its place.

The audio, pictures and lyrics stay on the server they're on; this one fetches them when they're
asked for (pictures once, kept like our own), so the app, Cast speakers and the quality settings
work with them as with ours. A computer (the desktop client) is asked the same through the
connection it keeps open (tunnel.py), and its songs are played from here. A picture's reference carries its version there
(peer:<its id>/albums/<its album id>/<version>): a new cover there is a new address here.
"""

import hashlib
import logging
import threading
import time
import unicodedata
from datetime import datetime, timezone

import httpx
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import delete, insert, or_, select, union, update
from sqlalchemy.exc import IntegrityError

from . import art, db, enrich, jobs, modules, network, scanner, tunnel
from .models import Album, Artist, Book, BookPart, FilePlaylist, FilePlaylistItem, Peer, Root, Track

log = logging.getLogger(__name__)

PAGE = 2000
PARTS = ("artists", "albums", "tracks", "books", "playlists")
ROOT = "peer:"      # + server id: the root a server's catalog hangs off

# what each part is made of, in the order of its rows
FIELDS = {
    "artists": ("id", "name", "sort_name", "mbid", "tags", "image"),
    "albums": ("id", "kind", "title", "artist", "artist_name", "year", "genre", "art", "mbid", "added_at"),
    "tracks": ("id", "album_id", "artist_ref", "kind", "subsong", "format", "codec", "title", "artist",
               "albumartist", "album", "track_no", "disc_no", "year", "genre", "duration", "bitrate",
               "sample_rate", "bit_depth", "channels", "size", "embedded_art", "mbid", "extra", "added_at"),
    "books": ("id", "title", "author", "narrator", "series", "year", "description", "art", "duration",
              "chapters", "added_at", "parts"),
    "playlists": ("id", "name", "entries", "tracks"),
}
# copied as they are into the mirrored rows
TRACK_COPY = ("kind", "subsong", "format", "codec", "title", "artist", "albumartist", "album", "track_no", "disc_no",
              "year", "genre", "duration", "bitrate", "sample_rate", "bit_depth", "channels", "size", "embedded_art",
              "mbid", "extra")
BOOK_COPY = ("title", "author", "narrator", "series", "year", "description", "duration", "chapters")


# ------------------------------------------------------------ what this server shares

def _ours(model):
    return [model.peer_id.is_(None), model.hidden.is_(False)]


def export(part: str, after: int = 0, limit: int = PAGE) -> dict:
    """A page of this server's own library: {fields, rows, next}, rows by id from `after` on."""
    limit = max(1, min(limit, 5000))
    with db.session() as s:
        if part == "artists":
            # the ones with songs or albums of our own (not those only another server brought)
            own = or_(Artist.id.in_(select(Track.artist_id).where(*_ours(Track))),
                      Artist.id.in_(select(Album.artist_id).where(*_ours(Album))))
            q = (select(Artist.id, Artist.name, Artist.sort_name, Artist.mbid, Artist.tags, Artist.image != "")
                 .where(Artist.hidden.is_(False), own, Artist.id > after).order_by(Artist.id).limit(limit))
        elif part == "albums":
            q = (select(Album.id, Album.kind, Album.title, Artist.name, Album.artist_name, Album.year, Album.genre,
                        Album.art != "", Album.mbid, Album.added_at)
                 .outerjoin(Artist, Artist.id == Album.artist_id)
                 .where(*_ours(Album), Album.id > after).order_by(Album.id).limit(limit))
        elif part == "tracks":
            q = (select(Track.id, Track.album_id, Artist.name, *(getattr(Track, f) for f in TRACK_COPY), Track.added_at)
                 .outerjoin(Artist, Artist.id == Track.artist_id)
                 .where(*_ours(Track), Track.id > after).order_by(Track.id).limit(limit))
        elif part == "books":
            q = (select(Book.id, *(getattr(Book, f) for f in BOOK_COPY[:-2]), Book.art != "", Book.duration,
                        Book.chapters, Book.added_at)
                 .where(*_ours(Book), Book.id > after).order_by(Book.id).limit(limit))
        elif part == "playlists":
            q = (select(FilePlaylist.id, FilePlaylist.name, FilePlaylist.entries)
                 .where(*_ours(FilePlaylist), FilePlaylist.id > after).order_by(FilePlaylist.id).limit(limit))
        else:
            raise KeyError(part)
        rows = [list(r) for r in s.execute(q)]
        picture = {"artists": ("artist", 5), "albums": ("album", 7), "books": ("book", 7)}.get(part)
        for r in rows:
            if isinstance(r[-1], datetime):
                r[-1] = r[-1].replace(tzinfo=None).isoformat()      # added_at, UTC
            if picture:     # whether it has one, as the version of its address (0: none)
                kind, i = picture
                r[i] = art.version(kind, r[0]) if r[i] else 0
        if part == "books":
            parts = {}
            for bid, pos, title, dur, off, fmt in s.execute(
                    select(BookPart.book_id, BookPart.position, BookPart.title, BookPart.duration, BookPart.offset,
                           BookPart.format)
                    .where(BookPart.book_id.in_([r[0] for r in rows])).order_by(BookPart.position)):
                parts.setdefault(bid, []).append([pos, title, dur, off, fmt])
            for r in rows:
                r.append(parts.get(r[0], []))
        elif part == "playlists":
            items = {}
            for pid, tid in s.execute(
                    select(FilePlaylistItem.playlist_id, FilePlaylistItem.track_id)
                    .join(Track, Track.id == FilePlaylistItem.track_id)
                    .where(FilePlaylistItem.playlist_id.in_([r[0] for r in rows]), *_ours(Track))
                    .order_by(FilePlaylistItem.playlist_id, FilePlaylistItem.position)):
                items.setdefault(pid, []).append(tid)
            for r in rows:
                r.append(items.get(r[0], []))
    return {"fields": FIELDS[part], "rows": rows, "next": rows[-1][0] if len(rows) == limit else None}


# ------------------------------------------------------------ another server's, here

class Unreachable(Exception):
    pass


def _fetch(c: httpx.Client, base: str, part: str, ctx) -> list[dict]:
    out, after = [], 0
    while True:
        ctx.check()
        for attempt in range(4):
            r = c.get(f"{base}/api/network/catalog/{part}", params={"after": after, "limit": PAGE})
            # right after linking, the other side may not have written down the link yet
            if r.status_code != 401 or attempt == 3:
                break
            time.sleep(3)
        if r.status_code == 401:
            raise Unreachable("it doesn't take this server's key: the link may have ended there")
        if r.status_code != 200:
            raise Unreachable(f"HTTP {r.status_code} for its {part}")
        page = r.json()
        fields = page["fields"]
        out += [dict(zip(fields, row)) for row in page["rows"]]
        if page["next"] is None:
            return out
        after = page["next"]


def _when(text: str | None) -> datetime:
    try:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc) if text else datetime.now(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _root(s, sid: str, name: str) -> int:
    root = s.scalar(select(Root).where(Root.path == ROOT + sid))
    if root is None:
        root = Root(path=ROOT + sid, kind="peer", name=name, enabled=True)
        s.add(root)
        s.flush()
    root.name = name
    return root.id


def _apply(s, model, key: str, fields, peer_id: int, want: dict) -> tuple[dict, dict]:
    """Make a server's rows of `model` here what `want` ({key: row}) says: new ones added, the
    `fields` of the others changed where they differ (an admin's hiding here stays), the rest
    removed. Returns {key: id} and what the rows were before ({key: {field: value}})."""
    col = getattr(model, key)
    rows = s.execute(select(model.id, col, *(getattr(model, f) for f in fields)).where(model.peer_id == peer_id))
    have = {r[1]: (r[0], dict(zip(fields, r[2:]))) for r in rows}
    changed = [{"id": have[k][0], **{f: want[k][f] for f in fields}} for k in want
               if k in have and any(have[k][1][f] != want[k][f] for f in fields)]
    new = [want[k] for k in want if k not in have]
    gone = [have[k][0] for k in have if k not in want]
    for i in range(0, len(changed), 500):
        s.execute(update(model), changed[i:i + 500])
    for i in range(0, len(new), 500):
        s.execute(insert(model), new[i:i + 500])
    for i in range(0, len(gone), 500):
        s.execute(delete(model).where(model.id.in_(gone[i:i + 500])))
    ids = dict(s.execute(select(col, model.id).where(model.peer_id == peer_id)).all())
    return ids, {k: v[1] for k, v in have.items()}


def store(peer_id: int, sid: str, name: str, cat: dict) -> dict:
    """A server's catalog, as fetched, made what's mirrored of it here."""
    resolver = scanner.Resolver()
    prefix = f"{ROOT}{sid}"
    new_pictures: dict[str, list[int]] = {"album": [], "book": [], "artist": []}
    with db.session() as s:
        root_id = _root(s, sid, name)

        # artists: theirs join ours by name; one only they have takes their genres along
        info = {a["name"].casefold(): a for a in cat["artists"] if a.get("name")}
        artist_ids: dict[str, int | None] = {}

        def artist(n: str | None) -> int | None:
            if not n:
                return None
            if n not in artist_ids:
                artist_ids[n] = resolver.artist(s, n)
            return artist_ids[n]

        for a in cat["albums"]:
            artist(a["artist"])
        for t in cat["tracks"]:
            artist(t["artist_ref"])
        known = [i for i in artist_ids.values() if i]
        bare = {i for i, tags in s.execute(select(Artist.id, Artist.tags).where(Artist.id.in_(known))) if not tags}
        for n, aid in artist_ids.items():
            a = info.get(n.casefold())
            if aid in bare and a and a.get("tags"):
                s.execute(update(Artist).where(Artist.id == aid).values(
                    tags=a["tags"], mbid=a.get("mbid") or "", sort_name=a.get("sort_name") or "",
                    tags_checked=datetime.now(timezone.utc)))
        # its picture of an artist, for one without a picture here (or with its older one)
        images = dict(s.execute(select(Artist.id, Artist.image).where(Artist.id.in_(known))).all())
        for n, aid in artist_ids.items():
            a = info.get(n.casefold())
            if aid not in images or (images[aid] and not images[aid].startswith(prefix + "/")):
                continue
            image = f"{prefix}/artists/{a['id']}/{a['image']}" if a and a.get("image") else ""
            if image != images[aid]:
                s.execute(update(Artist).where(Artist.id == aid).values(image=image))
                new_pictures["artist"].append(aid)

        # albums
        want = {}
        for a in cat["albums"]:
            aid = artist(a["artist"])
            want[f"{prefix}:{a['id']}"] = {
                "key": f"{prefix}:{a['id']}", "kind": a["kind"], "title": a["title"], "artist_id": aid,
                "artist_name": a["artist_name"], "year": a["year"], "genre": a["genre"],
                "folder": f"{prefix}/albums/{a['id']}",
                "art": f"{prefix}/albums/{a['id']}/{a['art']}" if a["art"] else "", "mbid": a["mbid"],
                "peer_id": peer_id}
        for k, a in zip(want, cat["albums"]):
            want[k]["added_at"] = _when(a["added_at"])
            want[k]["hidden"] = resolver.hidden(s, want[k]["artist_id"], None)
        album_ids, before = _apply(s, Album, "key", ("kind", "title", "artist_id", "artist_name", "year", "genre",
                                                     "folder", "art", "mbid"), peer_id, want)
        new_pictures["album"] = [album_ids[k] for k in want if k in before and before[k]["art"] != want[k]["art"]]
        by_album = {a["id"]: album_ids.get(f"{prefix}:{a['id']}") for a in cat["albums"]}

        # songs and chiptunes
        want = {}
        for t in cat["tracks"]:
            path = f"{prefix}/tracks/{t['id']}"
            row = {f: t[f] for f in TRACK_COPY}
            row.update(path=path, root_id=root_id, peer_id=peer_id, album_id=by_album.get(t["album_id"]),
                       artist_id=artist(t["artist_ref"]))
            want[path] = row
        for k, t in zip(want, cat["tracks"]):
            want[k]["added_at"] = _when(t["added_at"])
            want[k]["hidden"] = resolver.hidden(s, want[k]["artist_id"], want[k]["album_id"])
        track_ids, _ = _apply(s, Track, "path", TRACK_COPY + ("album_id", "artist_id"), peer_id, want)
        by_track = {t["id"]: track_ids.get(f"{prefix}/tracks/{t['id']}") for t in cat["tracks"]}

        # audiobooks: a book whose parts changed gets them anew
        want, parts = {}, {}
        for b in cat["books"]:
            path = f"{prefix}/books/{b['id']}"
            want[path] = {**{f: b[f] for f in BOOK_COPY}, "path": path, "root_id": root_id, "peer_id": peer_id,
                          "art": f"{prefix}/books/{b['id']}/{b['art']}" if b["art"] else "",
                          "signature": hashlib.sha1(repr(b["parts"]).encode()).hexdigest(),
                          "added_at": _when(b["added_at"])}
            parts[path] = b["parts"]
        book_ids, before = _apply(s, Book, "path", BOOK_COPY + ("art", "signature"), peer_id, want)
        new_pictures["book"] = [book_ids[k] for k in want if k in before and before[k]["art"] != want[k]["art"]]
        for path, bid in book_ids.items():
            if before.get(path, {}).get("signature") == want[path]["signature"]:
                continue
            s.execute(delete(BookPart).where(BookPart.book_id == bid))
            if parts[path]:
                s.execute(insert(BookPart), [
                    {"book_id": bid, "position": pos, "path": f"{path}/{pos}", "title": title, "duration": dur,
                     "offset": off, "format": fmt} for pos, title, dur, off, fmt in parts[path]])

        # playlist files: their songs as mirrored here
        want = {f"{prefix}/playlists/{p['id']}": {
            "path": f"{prefix}/playlists/{p['id']}", "name": p["name"], "entries": p["entries"],
            "root_id": root_id, "peer_id": peer_id} for p in cat["playlists"]}
        list_ids, _ = _apply(s, FilePlaylist, "path", ("name", "entries"), peer_id, want)
        s.execute(delete(FilePlaylistItem).where(FilePlaylistItem.playlist_id.in_(list(list_ids.values()))))
        rows = []
        for p in cat["playlists"]:
            lid = list_ids.get(f"{prefix}/playlists/{p['id']}")
            tracks = [by_track[t] for t in p["tracks"] if by_track.get(t)]
            rows += [{"playlist_id": lid, "position": i, "track_id": t} for i, t in enumerate(tracks)]
        for i in range(0, len(rows), 1000):
            s.execute(insert(FilePlaylistItem), rows[i:i + 1000])

    for kind, ids in new_pictures.items():       # new addresses for the pictures that changed there
        art.changed(kind, *ids)
    return {"artists": len(artist_ids), "albums": len(cat["albums"]), "tracks": len(cat["tracks"]),
            "books": len(cat["books"]), "playlists": len(cat["playlists"])}


def sync_peer(ctx: jobs.JobContext, peer_id: int, share: float = 1.0, base_progress: float = 0.0) -> bool:
    with db.session() as s:
        p = s.get(Peer, peer_id)
        if p is None or network.state(p) != "linked":
            return False
        address, key, sid, name, computer = p.address, p.key, p.server_id, p.name, p.kind == "computer"
    if computer and not tunnel.connected(peer_id):
        ctx.log(f"{name} isn't on: its catalog comes when it connects")
        return False
    ctx.log(f"{name}: fetching its catalog")
    headers = {"User-Agent": enrich.UA, "Authorization": f"Bearer {key}"}
    try:
        with httpx.Client(headers=headers, timeout=120) as c:
            cat = {}
            for i, part in enumerate(PARTS):
                ctx.update(base_progress + share * 0.8 * i / len(PARTS), f"{name}: {part}")
                cat[part] = tunnel.catalog(peer_id, part, ctx) if computer else _fetch(c, address, part, ctx)
    except (httpx.HTTPError, Unreachable, tunnel.Gone, ValueError, KeyError, TypeError) as e:
        why = str(e) or e.__class__.__name__
        ctx.log(f"{name}: couldn't fetch its catalog ({why})")
        with db.session() as s:
            if (p := s.get(Peer, peer_id)) is not None:
                p.error = f"Couldn't fetch its library: {why}"
        return False
    ctx.update(base_progress + share * 0.8, f"{name}: storing")
    try:
        counts = store(peer_id, sid, name, cat)
    except IntegrityError:
        with db.session() as s:
            if s.get(Peer, peer_id) is not None:
                raise
        ctx.log(f"{name} left the network meanwhile")     # network_drop takes what's here
        return False
    ctx.log(f"{name}: {counts['albums']} albums, {counts['tracks']} songs, {counts['books']} audiobooks, "
            f"{counts['playlists']} playlist files")
    with db.session() as s:
        if (p := s.get(Peer, peer_id)) is not None:
            p.counts, p.error = counts, ""
            p.synced_at = p.last_seen = datetime.now(timezone.utc)
    return True


@jobs.job("network_sync")
def sync_job(ctx: jobs.JobContext, peer_id: int | None = None):
    """The linked servers' catalogs (or one's), mirrored here."""
    if not modules.on("network"):
        ctx.log("The Library Network is turned off (Admin → Modules), nothing synced")
        return {"synced": 0, "servers": 0}
    with db.session() as s:
        ids = [p.id for p in s.scalars(select(Peer).where(Peer.sent.is_(True), Peer.received.is_(True)))
               if peer_id in (None, p.id)]
    done = sum(sync_peer(ctx, pid, 1 / max(1, len(ids)), i / max(1, len(ids))) for i, pid in enumerate(ids))
    if done:
        scanner.finish_scan(ctx)
    return {"synced": done, "servers": len(ids)}


@jobs.job("network_drop")
def drop_job(ctx: jobs.JobContext, server_id: str):
    """A server left the network: what was mirrored of it goes (its songs out of playlists too)."""
    with db.session() as s:
        root = s.scalar(select(Root).where(Root.path == ROOT + server_id))
        if root is not None:
            s.delete(root)      # its tracks, books and playlist files with it
        s.execute(delete(Album).where(Album.key.startswith(f"{ROOT}{server_id}:")))
        pictured = s.scalars(select(Artist.id).where(Artist.image.startswith(f"{ROOT}{server_id}/"))).all()
        s.execute(update(Artist).where(Artist.id.in_(pictured)).values(image=""))
    art.changed("artist", *pictured)
    tunnel.forget_files(server_id)
    scanner.finish_scan(ctx)


# ------------------------------------------------------------ the same album in more than one library

VARIOUS = {"various artists", "various", "va"}


def _name(text: str) -> str:
    """A name as compared across libraries: case, accents, punctuation and a leading "the" aside."""
    t = unicodedata.normalize("NFKD", (text or "").casefold())
    t = "".join(ch if ch.isalnum() else " " for ch in t if not unicodedata.combining(ch))
    words = t.split()
    return " ".join(words[1:] if words[:1] == ["the"] and len(words) > 1 else words)


def order() -> dict[int | None, int]:
    """Each library's place in line (this server's is None): the main library first, then this
    server, then the others in the order they were linked."""
    main = network.main()
    with db.session() as s:
        peers = s.execute(select(Peer.id, Peer.server_id).order_by(Peer.id)).all()
    line = [None] + [pid for pid, _ in peers]
    first = next((pid for pid, sid in peers if sid == main), None)
    if first is not None:
        line.remove(first)
        line.insert(0, first)
    return {lib: i for i, lib in enumerate(line)}


def _shadows(rows, keys, rank) -> set[int]:
    """Of rows (id, library, ...) that `keys(row)` says are one work, the ones in a library later
    in line than another that has it (any of its keys shared makes it the same)."""
    parent: dict = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for r in rows:
        for k in keys(r):
            parent[find(("row", r[0]))] = find(k)
    groups: dict = {}
    for r in rows:
        groups.setdefault(find(("row", r[0])), []).append(r)
    out = set()
    for members in groups.values():
        libraries = {r[1] for r in members}
        if len(libraries) > 1:
            first = min(libraries, key=lambda lib: rank.get(lib, len(rank)))
            out |= {r[0] for r in members if r[1] != first}
    return out


def dedupe() -> dict:
    """Albums and audiobooks that more than one library has: the copy of the one first in line
    (order()) shows, the others are shadowed, songs with their album (db.py leaves them out of
    what's listed). An album is the same by its album artist and title (and year, for a
    compilation of various artists) or by its MusicBrainz id; a book by its author and title.
    A computer that's off has none: its copies wait, and others show meanwhile."""
    rank = order()
    with db.session() as s:
        away = set(s.scalars(select(Peer.id).where(Peer.away.is_(True))))
        albums = [r for r in s.execute(select(Album.id, Album.peer_id, Album.kind, Album.artist_name, Album.title,
                                                Album.year, Album.mbid)) if r[1] not in away]

        def album_keys(r):
            artist = _name(r[3])
            yield ("album", r[2], artist, _name(r[4]), r[5] if artist in VARIOUS else None)
            if r[6]:
                yield ("mbid", r[6])

        books = [r for r in s.execute(select(Book.id, Book.peer_id, Book.author, Book.title)) if r[1] not in away]
        shadowed = {
            Album: _shadows(albums, album_keys, rank),
            Book: _shadows(books, lambda r: [("book", _name(r[2]), _name(r[3]))], rank),
        }
        changed = {}
        for model, ids in shadowed.items():
            was = set(s.scalars(select(model.id).where(model.shadowed.is_(True))))
            on, off = ids - was, was - ids
            for flag, these in ((True, on), (False, off)):
                these = list(these)
                for i in range(0, len(these), 500):
                    s.execute(update(model).where(model.id.in_(these[i:i + 500])).values(shadowed=flag))
            changed[model.__tablename__] = len(on) + len(off)
        # artists only other servers' libraries have (left out for whoever leaves the network's music out)
        mine = union(select(Track.artist_id).where(Track.peer_id.is_(None), Track.artist_id.is_not(None)),
                     select(Album.artist_id).where(Album.peer_id.is_(None), Album.artist_id.is_not(None)))
        s.execute(update(Artist).where(Artist.peer_only.is_(False), Artist.id.not_in(mine)).values(peer_only=True))
        s.execute(update(Artist).where(Artist.peer_only.is_(True), Artist.id.in_(mine)).values(peer_only=False))
        # artists only computers that are off have (left out until one is on)
        off = select(Peer.id).where(Peer.away.is_(True))
        here = union(select(Track.artist_id).where(or_(Track.peer_id.is_(None), Track.peer_id.not_in(off)),
                                                   Track.artist_id.is_not(None)),
                     select(Album.artist_id).where(or_(Album.peer_id.is_(None), Album.peer_id.not_in(off)),
                                                   Album.artist_id.is_not(None)))
        s.execute(update(Artist).where(Artist.away.is_(False), Artist.id.not_in(here)).values(away=True))
        s.execute(update(Artist).where(Artist.away.is_(True), Artist.id.in_(here)).values(away=False))
        # a song is its album's copy
        copies = select(Album.id).where(Album.shadowed.is_(True))
        s.execute(update(Track).where(Track.shadowed.is_(False), Track.album_id.in_(copies)).values(shadowed=True))
        s.execute(update(Track).where(Track.shadowed.is_(True),
                                      or_(Track.album_id.is_(None), Track.album_id.not_in(copies)))
                  .values(shadowed=False))
    return {"albums": len(shadowed[Album]), "books": len(shadowed[Book]), "changed": changed}


# ------------------------------------------------------------ their audio, pictures and lyrics, through here

_http = httpx.Client(headers={"User-Agent": enrich.UA, "Accept-Encoding": "identity"},
                     timeout=httpx.Timeout(10, read=300), limits=httpx.Limits(max_connections=64))
PASS = ("content-type", "content-length", "content-range", "accept-ranges", "last-modified", "etag",
        "cache-control", "x-muzix-transcoded")
AWAY_FOR = 60       # seconds a server that didn't answer is left alone (a page of covers won't wait on each)
_away: dict[str, float] = {}
_away_lock = threading.Lock()


class Away(Exception):
    """What another server has can't be had: the status for the page, and why."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def where(ref: str) -> tuple[str, str, int, str]:
    """(server id, kind, its id, the rest) of a mirrored path or picture: peer:<sid>/<kind>s/<id>[/<rest>]."""
    sid, kinds, rid, *rest = ref[len(ROOT):].split("/")
    return sid, kinds.rstrip("s"), int(rid), "/".join(rest)


def computer(sid: str) -> int | None:
    """The peer id of a computer in the network (None: a server, or no member)."""
    with db.session() as s:
        return s.scalar(select(Peer.id).where(Peer.server_id == sid, Peer.kind == "computer"))


def _get(sid: str, path: str, params: dict | None = None, headers: dict | None = None,
         stream: bool = False) -> httpx.Response:
    with db.session() as s:
        p = s.scalar(select(Peer).where(Peer.server_id == sid))
        if p is None or network.state(p) != "linked":
            raise Away(404, "That server is no longer in the Library Network")
        if p.kind == "computer":
            raise Away(404, "Computers share songs only")
        address, key, who = p.address, p.key, p.name
    with _away_lock:
        if _away.get(sid, 0) > time.time():
            raise Away(502, f"{who} can't be reached right now")
    req = _http.build_request("GET", address + path, params=params,
                              headers={"Authorization": f"Bearer {key}", **(headers or {})})
    try:
        r = _http.send(req, stream=stream)
    except httpx.HTTPError:
        with _away_lock:
            _away[sid] = time.time() + AWAY_FOR
        raise Away(502, f"{who} can't be reached right now")
    if r.status_code >= 400 and r.status_code != 416:
        r.close()
        raise Away(404 if r.status_code == 404 else 502, f"{who} couldn't give it (HTTP {r.status_code})")
    return r


def audio(path: str, q: str, t: float, prefetch: bool, range_: str | None) -> Response:
    """A song or audiobook part on another server, passed through as it comes: the file (a part
    of it, for a Range), converted (q, t), or a 204 when it only gets ready (prefetch)."""
    sid, kind, rid, rest = where(path)
    params = {"q": q, **({"t": t} if t else {}), **({"prefetch": "true"} if prefetch else {})}
    r = _get(sid, f"/api/network/stream/{rid}" if kind == "track" else f"/api/network/books/{rid}/parts/{rest}/stream",
             params, {"Range": range_} if range_ else None, stream=True)
    if r.status_code == 204:
        r.close()
        return Response(status_code=204)

    def body():
        try:
            yield from r.iter_raw(64 * 1024)
        except httpx.HTTPError as e:      # it stopped halfway (gone, or its render failed): so does this
            log.warning("The server with %s stopped sending it: %s", path, e)
        finally:
            r.close()

    return StreamingResponse(body(), status_code=r.status_code,
                             headers={k: v for k, v in r.headers.items() if k.lower() in PASS})


def picture(ref: str, size: int) -> str | None:
    """Another server's picture (peer:<sid>/<kind>s/<id>/<version>) at about `size` px: fetched
    once, then kept like our own."""
    if found := art.cached(ref, size):
        return found
    sid, kind, rid, _ = where(ref)
    if (pc := computer(sid)) is not None:
        try:
            data = tunnel.picture(pc, kind, rid)
        except (tunnel.Gone, tunnel.Refused):
            return None
        return art.resized(data, ref, size) if data else None
    try:
        r = _get(sid, f"/api/network/art/{kind}/{rid}", {"s": art.pick_size(size)})
    except Away:
        return None
    return art.resized(r.content, ref, size)


def colors(ref: str) -> list[str]:
    """A cover's colours (what the page is tinted with): ours from its file, another server's
    from its picture here."""
    if not ref or ref.startswith("embedded:"):
        return []
    if ref.startswith(ROOT):
        ref = picture(ref, 300) or ""
    return art.dominant_colors(ref) if ref else []


def lyrics(path: str) -> dict | None:
    """A song's lyrics as the server it's on has them (its .lrc files and tags); None when it
    can't be asked."""
    sid, _, rid, _ = where(path)
    if (pc := computer(sid)) is not None:
        return tunnel.lyrics(pc, rid)
    try:
        return _get(sid, f"/api/network/lyrics/{rid}").json()
    except (Away, ValueError):
        return None
