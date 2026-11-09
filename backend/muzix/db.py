"""SQLite database (WAL mode) shared by the web app and background jobs."""

from contextlib import contextmanager

from sqlalchemy import and_, create_engine, event, or_, select, text
from sqlalchemy.orm import DeclarativeBase, ORMExecuteState, Session, sessionmaker, with_loader_criteria
from starlette.requests import HTTPConnection

from . import env


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal: sessionmaker | None = None
computers_away = False      # whether a computer of the Library Network is off (tunnel.py says)


def init(url: str | None = None):
    global engine, SessionLocal
    env.ensure_dirs()
    # covers and streams can hold a connection for a moment; leave room for page loads
    engine = create_engine(url or f"sqlite:///{env.DB_PATH}", pool_size=10, max_overflow=30,
                           connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
        # SQLite's lower() only knows A-Z; "Árstíðir" and "Проект Звездолет" need real casefolding
        conn.create_function("casefold", 1, lambda v: v.casefold() if isinstance(v, str) else v, deterministic=True)

    SessionLocal = sessionmaker(engine, expire_on_commit=False)
    from . import models  # noqa: F401  (register tables)
    Base.metadata.create_all(engine)
    _add_new_columns()
    _drop_gone()
    with engine.begin() as conn:
        # one full-text index over everything searchable
        conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
            "kind UNINDEXED, ref UNINDEXED, title, subtitle, tokenize='unicode61 remove_diacritics 2')"))


def _add_new_columns():
    """Columns added to a table since the database was made (create_all only makes new tables)."""
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {r[1] for r in conn.execute(text(f'PRAGMA table_info("{table.name}")'))}
            for col in table.columns:
                if col.name in have:
                    continue
                default = col.server_default.arg if col.server_default is not None else None
                if default is None and not col.nullable:
                    raise RuntimeError(f"{table.name}.{col.name} needs a server default to be added")
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                if default is not None:
                    ddl += f" NOT NULL DEFAULT '{default}'" if not col.nullable else f" DEFAULT '{default}'"
                conn.execute(text(ddl))


# what Muzix had and doesn't any more, out of databases made before: Spotify, and the server's Appearance
# settings, which are each device's own now (both 2026-11)
GONE_TABLES = ("spotify_links",)
GONE_SETTINGS = ("spotify_client_id", "module_spotify", "default_scheme", "default_mode", "genre_skins", "skin_map")


def _drop_gone():
    with engine.begin() as conn:
        for name in GONE_TABLES:
            conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        conn.execute(text("DELETE FROM settings WHERE key IN (%s)" % ", ".join(f"'{k}'" for k in GONE_SETTINGS)))


def _visible(cls):
    return cls.hidden.is_(False)


def _listed(cls):
    return and_(cls.hidden.is_(False), cls.shadowed.is_(False))


def _ours(cls):
    return and_(cls.hidden.is_(False), cls.peer_id.is_(None))


def _ours_artist(cls):
    return and_(cls.hidden.is_(False), cls.peer_only.is_(False))


# the same, without chiptunes (the VGM module is off)
def _visible_music(cls):
    return and_(cls.hidden.is_(False), cls.kind != "vgm")


def _listed_music(cls):
    return and_(cls.hidden.is_(False), cls.shadowed.is_(False), cls.kind != "vgm")


def _ours_music(cls):
    return and_(cls.hidden.is_(False), cls.peer_id.is_(None), cls.kind != "vgm")


def _nothing(cls):
    """What a module that's off holds (its audiobooks, podcasts or stations)."""
    return cls.id.is_(None)


def _present(cls):
    """Not on a computer of the Library Network that's off."""
    from .models import Peer
    return or_(cls.peer_id.is_(None), cls.peer_id.not_in(select(Peer.id).where(Peer.away.is_(True))))


def _present_artist(cls):
    return cls.away.is_(False)


@event.listens_for(Session, "do_orm_execute")
def _without_hidden(state: ORMExecuteState):
    """In sessions that serve the web pages, whatever an admin hid isn't there; nor is another
    library's copy of an album or audiobook that one first in line has (the Library Network:
    mirror.dedupe), unless the session keeps copies (or the statement asks for them). For
    someone who left the network's music out (their "network" preference: security.py says
    so as the request comes in), only this server's own library is there, every copy of it; so
    it is for everyone while the Library Network is off. What a module that's off holds isn't
    there either (modules.py), nor what's only on a computer of the Library Network that's off
    (tunnel.py)."""
    if not state.is_select or not state.session.info.get("hide") or state.execution_options.get("include_hidden"):
        return
    from . import modules
    from .models import HIDEABLE, SHADOWABLE, Album, Artist, Book, Feed, Station, Track
    off = modules.off()
    gone = {model for model, key in ((Book, "audiobooks"), (Feed, "podcasts"), (Station, "radio")) if key in off}
    no_vgm = "vgm" in off
    copies = state.session.info.get("copies") or state.execution_options.get("include_copies")
    viewer = state.session.info.get("viewer")
    ours = "network" in off or viewer is not None and getattr(viewer, "network", True) is False
    for model in HIDEABLE:
        music = no_vgm and model in (Album, Track)
        if model in gone:
            crit = _nothing
        elif ours and model is Artist:
            crit = _ours_artist
        elif ours and hasattr(model, "peer_id"):
            crit = _ours_music if music else _ours
        elif model in SHADOWABLE and not copies and not ours:
            crit = _listed_music if music else _listed
        else:
            crit = _visible_music if music else _visible
        state.statement = state.statement.options(with_loader_criteria(model, crit, include_aliases=True))
        if computers_away and model not in gone and (model is Artist or hasattr(model, "peer_id")):
            away = _present_artist if model is Artist else _present
            state.statement = state.statement.options(with_loader_criteria(model, away, include_aliases=True))


def get_db(conn: HTTPConnection):
    """FastAPI dependency: a session that leaves out hidden items, and other libraries' copies."""
    db = SessionLocal()
    db.info["hide"] = True
    db.info["viewer"] = conn.state
    try:
        yield db
    finally:
        db.close()


def get_db_with_copies(conn: HTTPConnection):
    """FastAPI dependency for what someone saved, played or put in a playlist themselves (and
    what's asked for by its id): hidden items left out, but every library's copy kept, so a song
    stays where it was put when another library's copy of its album comes first."""
    db = SessionLocal()
    db.info["hide"] = db.info["copies"] = True
    db.info["viewer"] = conn.state
    try:
        yield db
    finally:
        db.close()


def get_db_all():
    """FastAPI dependency for the admin's own lists: hidden items included."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session() -> Session:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
