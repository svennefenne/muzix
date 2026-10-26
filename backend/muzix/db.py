"""SQLite database (WAL mode) shared by the web app and background jobs."""

from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, ORMExecuteState, Session, sessionmaker, with_loader_criteria

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
    _add_new_columns()
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


@event.listens_for(Session, "do_orm_execute")
def _without_hidden(state: ORMExecuteState):
    """In sessions that serve the web pages, whatever an admin hid isn't there."""
    if not state.is_select or not state.session.info.get("hide") or state.execution_options.get("include_hidden"):
        return
    from .models import HIDEABLE
    for model in HIDEABLE:
        state.statement = state.statement.options(
            with_loader_criteria(model, lambda cls: cls.hidden.is_(False), include_aliases=True))


def get_db():
    """FastAPI dependency: a session that leaves out hidden items."""
    db = SessionLocal()
    db.info["hide"] = True
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
