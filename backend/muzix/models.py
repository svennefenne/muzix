"""Database tables."""

from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- users & settings

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    prefs: Mapped[dict] = mapped_column(JSON, default=dict)   # theme, volume, ...


class AuthSession(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    user: Mapped[User] = relationship()


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


class Root(Base):
    """A folder Muzix scans. kind: music | vgm | audiobooks."""
    __tablename__ = "roots"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="music")
    name: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    upload_target: Mapped[bool] = mapped_column(Boolean, default=False)
    excludes: Mapped[list] = mapped_column(JSON, default=list)   # sub-paths to skip
    last_scan: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------- library

class Artist(Base):
    __tablename__ = "artists"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(512), index=True)
    sort_name: Mapped[str] = mapped_column(String(512), default="")
    mbid: Mapped[str] = mapped_column(String(64), default="")
    genre: Mapped[str] = mapped_column(String(128), default="")        # main genre folder
    tags: Mapped[list] = mapped_column(JSON, default=list)             # [[tag, weight], ...]
    tags_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    image: Mapped[str] = mapped_column(String(1024), default="")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")   # admin: hidden from everyone
    __table_args__ = (UniqueConstraint("name", name="uq_artist_name"),)


class Album(Base):
    __tablename__ = "albums"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="music")     # music | vgm
    title: Mapped[str] = mapped_column(String(512))
    artist_id: Mapped[int | None] = mapped_column(ForeignKey("artists.id", ondelete="SET NULL"),
                                                  nullable=True, index=True)
    artist_name: Mapped[str] = mapped_column(String(512), default="")
    year: Mapped[int] = mapped_column(Integer, default=0)
    genre: Mapped[str] = mapped_column(String(128), default="", index=True)
    folder: Mapped[str] = mapped_column(String(1024), index=True)
    key: Mapped[str] = mapped_column(String(1100), unique=True)        # folder + album identity
    art: Mapped[str] = mapped_column(String(1024), default="")         # path to image or "embedded:<track id>"
    track_count: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0)
    formats: Mapped[str] = mapped_column(String(128), default="")
    mbid: Mapped[str] = mapped_column(String(64), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")   # admin: hidden from everyone
    artist: Mapped[Artist | None] = relationship()


class Track(Base):
    __tablename__ = "tracks"
    id: Mapped[int] = mapped_column(primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("roots.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    subsong: Mapped[int] = mapped_column(Integer, default=-1)   # -1: whole file; n: chip subsong
    kind: Mapped[str] = mapped_column(String(16), default="music")
    format: Mapped[str] = mapped_column(String(16), default="")         # file extension
    codec: Mapped[str] = mapped_column(String(32), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    artist: Mapped[str] = mapped_column(String(512), default="")
    albumartist: Mapped[str] = mapped_column(String(512), default="")
    album: Mapped[str] = mapped_column(String(512), default="")
    album_id: Mapped[int | None] = mapped_column(ForeignKey("albums.id", ondelete="SET NULL"),
                                                 nullable=True, index=True)
    artist_id: Mapped[int | None] = mapped_column(ForeignKey("artists.id", ondelete="SET NULL"),
                                                  nullable=True, index=True)
    track_no: Mapped[int] = mapped_column(Integer, default=0)
    disc_no: Mapped[int] = mapped_column(Integer, default=0)
    year: Mapped[int] = mapped_column(Integer, default=0)
    genre: Mapped[str] = mapped_column(String(255), default="")
    duration: Mapped[float] = mapped_column(Float, default=0)
    bitrate: Mapped[int] = mapped_column(Integer, default=0)
    sample_rate: Mapped[int] = mapped_column(Integer, default=0)
    bit_depth: Mapped[int] = mapped_column(Integer, default=0)
    channels: Mapped[int] = mapped_column(Integer, default=0)
    size: Mapped[int] = mapped_column(Integer, default=0)
    mtime: Mapped[float] = mapped_column(Float, default=0)
    embedded_art: Mapped[bool] = mapped_column(Boolean, default=False)
    mbid: Mapped[str] = mapped_column(String(64), default="")
    extra: Mapped[dict] = mapped_column(JSON, default=dict)   # system, game, dumper, comment...
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    seen_scan: Mapped[int] = mapped_column(Integer, default=0)   # scan generation marker
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")   # admin: hidden from everyone
    __table_args__ = (UniqueConstraint("path", "subsong", name="uq_track_path"),
                      Index("ix_tracks_album_order", "album_id", "disc_no", "track_no"))


class TagOverride(Base):
    """An admin's edit of a file whose tags can't be written (chip and tracker formats):
    applied over what the file says whenever it is read."""
    __tablename__ = "tag_overrides"
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    subsong: Mapped[int] = mapped_column(Integer, primary_key=True)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)


class TrashItem(Base):
    """Something deleted from the library: its files sit in a .muzix-trash folder of its
    library folder until it is restored or the trash is emptied."""
    __tablename__ = "trash"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))             # album | track | artist | playlist
    title: Mapped[str] = mapped_column(String(512), default="")
    subtitle: Mapped[str] = mapped_column(String(512), default="")
    root_id: Mapped[int | None] = mapped_column(ForeignKey("roots.id", ondelete="SET NULL"), nullable=True)
    folder: Mapped[str] = mapped_column(String(1024), default="")   # the trash folder that holds it
    moves: Mapped[list] = mapped_column(JSON, default=list)          # [[original path, path in the trash], ...]
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EditRecord(Base):
    """An admin's edit and what it changed (tags, file names, folders, fields), so it can be undone."""
    __tablename__ = "edits"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))             # album | track | artist | book | ...
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    summary: Mapped[str] = mapped_column(String(1024), default="")
    undo: Mapped[dict] = mapped_column(JSON, default=dict)     # what was there before, see manage.py
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Playlist(Base):
    __tablename__ = "playlists"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")   # admin: hidden from everyone


class PlaylistItem(Base):
    __tablename__ = "playlist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FilePlaylist(Base):
    """A playlist file found in a library folder; everyone sees these."""
    __tablename__ = "file_playlists"
    id: Mapped[int] = mapped_column(primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("roots.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    entries: Mapped[int] = mapped_column(Integer, default=0)   # lines in the file, found or not
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")   # admin: hidden from everyone


class FilePlaylistItem(Base):
    __tablename__ = "file_playlist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("file_playlists.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))


class Like(Base):
    __tablename__ = "likes"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    item_type: Mapped[str] = mapped_column(String(16), primary_key=True)   # track | album | artist | station
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RecentSearch(Base):
    """Something a user picked from search results: their recent searches, as on Spotify."""
    __tablename__ = "recent_searches"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)   # artist | album | track | book
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class LyricsCache(Base):
    """What LRCLIB had for a song (or that it had nothing, until it's time to ask again)."""
    __tablename__ = "lyrics"
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)
    synced: Mapped[str] = mapped_column(Text, default="")
    plain: Mapped[str] = mapped_column(Text, default="")
    instrumental: Mapped[bool] = mapped_column(Boolean, default=False)
    found: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ArtVersion(Base):
    """How many times a picture has changed: part of its address, so browsers fetch it again."""
    __tablename__ = "art_versions"
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)   # album | artist | book
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class PlayEvent(Base):
    __tablename__ = "plays"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


# ---------------------------------------------------------------- audiobooks

class Book(Base):
    __tablename__ = "books"
    id: Mapped[int] = mapped_column(primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("roots.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)   # folder, or the .m4b file
    title: Mapped[str] = mapped_column(String(512))
    author: Mapped[str] = mapped_column(String(512), default="")
    narrator: Mapped[str] = mapped_column(String(512), default="")
    series: Mapped[str] = mapped_column(String(512), default="")
    year: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    art: Mapped[str] = mapped_column(String(1024), default="")
    duration: Mapped[float] = mapped_column(Float, default=0)
    chapters: Mapped[list] = mapped_column(JSON, default=list)   # [{title, start}] over the whole book
    signature: Mapped[str] = mapped_column(String(64), default="")  # changes when its files change
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    seen_scan: Mapped[int] = mapped_column(Integer, default=0)
    custom: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")   # admin's edits, kept over rescans
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")   # admin: hidden from everyone


class BookPart(Base):
    """One audio file of a book, in reading order."""
    __tablename__ = "book_parts"
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512), default="")
    duration: Mapped[float] = mapped_column(Float, default=0)
    offset: Mapped[float] = mapped_column(Float, default=0)   # start time within the book
    format: Mapped[str] = mapped_column(String(16), default="")


class BookProgress(Base):
    __tablename__ = "book_progress"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[float] = mapped_column(Float, default=0)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ---------------------------------------------------------------- podcasts

class Feed(Base):
    __tablename__ = "feeds"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    author: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    image: Mapped[str] = mapped_column(String(2048), default="")
    link: Mapped[str] = mapped_column(String(2048), default="")
    categories: Mapped[list] = mapped_column(JSON, default=list)
    etag: Mapped[str] = mapped_column(String(255), default="")
    modified: Mapped[str] = mapped_column(String(255), default="")
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    custom: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")   # admin's edits, kept over refreshes
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")   # admin: hidden from everyone


class Subscription(Base):
    __tablename__ = "subscriptions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feeds.id", ondelete="CASCADE"), primary_key=True)
    auto_download: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)   # its page last opened


class Episode(Base):
    __tablename__ = "episodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feeds.id", ondelete="CASCADE"), index=True)
    guid: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(1024), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    duration: Mapped[float] = mapped_column(Float, default=0)
    audio_url: Mapped[str] = mapped_column(String(2048), default="")
    mime: Mapped[str] = mapped_column(String(64), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    image: Mapped[str] = mapped_column(String(2048), default="")
    local_path: Mapped[str] = mapped_column(String(1024), default="")
    added_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=now)   # first read
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)   # show notes as safe HTML; None: not read yet
    __table_args__ = (UniqueConstraint("feed_id", "guid", name="uq_episode_guid"),)


class EpisodeProgress(Base):
    __tablename__ = "episode_progress"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[float] = mapped_column(Float, default=0)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ---------------------------------------------------------------- radio

class Station(Base):
    """A saved internet radio station (per user)."""
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    uuid: Mapped[str] = mapped_column(String(64), default="")   # radio-browser.info id
    name: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(2048))
    homepage: Mapped[str] = mapped_column(String(2048), default="")
    favicon: Mapped[str] = mapped_column(String(2048), default="")
    tags: Mapped[str] = mapped_column(String(1024), default="")
    country: Mapped[str] = mapped_column(String(128), default="")
    codec: Mapped[str] = mapped_column(String(32), default="")
    bitrate: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")   # admin: hidden from everyone


class RadioPlay(Base):
    """A song a station played while this user listened (the title the stream announced)."""
    __tablename__ = "radio_plays"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    station: Mapped[str] = mapped_column(String(2048))   # radio-browser id, or the stream address
    title: Mapped[str] = mapped_column(String(512))
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_radio_plays_user_station", "user_id", "station", "played_at"),)


# ---------------------------------------------------------------- spotify & jobs

class SpotifyLink(Base):
    __tablename__ = "spotify_links"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, default="")
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[float] = mapped_column(Float, default=0)
    scope: Mapped[str] = mapped_column(Text, default="")
    display_name: Mapped[str] = mapped_column(String(255), default="")
    product: Mapped[str] = mapped_column(String(32), default="")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued")   # queued|running|done|failed|cancelled
    progress: Mapped[float] = mapped_column(Float, default=0)          # 0..1
    message: Mapped[str] = mapped_column(Text, default="")
    log: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# what an admin can hide: hidden rows stay out of every page and list (db.py)
HIDEABLE = (Artist, Album, Track, Playlist, FilePlaylist, Book, Feed, Station)
