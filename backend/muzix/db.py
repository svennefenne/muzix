"""SQLite database (WAL mode) shared by the web app and background jobs."""

from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import env


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal: sessionmaker | None = None


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
    with engine.begin() as conn:
        # one full-text index over everything searchable
        conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
            "kind UNINDEXED, ref UNINDEXED, title, subtitle, tokenize='unicode61 remove_diacritics 2')"))


def get_db():
    """FastAPI dependency."""
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
