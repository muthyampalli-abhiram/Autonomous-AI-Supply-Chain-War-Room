"""Database session and connection management for Autonomous AI Supply Chain War Room."""

from __future__ import annotations

from pathlib import Path
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from warroom.config import get_settings
from warroom.db.models import Base


def resolve_db_url(db_url: str | None = None) -> str:
    """Resolve database URL, expanding relative SQLite paths relative to project root."""
    if db_url is None:
        db_url = get_settings().db_url

    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:///:memory:"):
        # Strip sqlite:/// prefix to get the raw path
        raw_path = db_url[len("sqlite:///") :]
        p = Path(raw_path)
        if not p.is_absolute():
            project_root = get_settings().project_root
            resolved_file = (project_root / p).resolve()
        else:
            resolved_file = p.resolve()

        resolved_file.parent.mkdir(parents=True, exist_ok=True)
        # Use as_posix() to ensure forward slashes across platforms
        return f"sqlite:///{resolved_file.as_posix()}"

    return db_url


def get_engine(db_url: str | None = None, echo: bool = False) -> Engine:
    """Create and return a SQLAlchemy Engine configured with foreign key support."""
    resolved_url = resolve_db_url(db_url)
    engine = create_engine(resolved_url, echo=echo)

    # Enable foreign key constraint checking for SQLite
    if resolved_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            if type(dbapi_connection).__module__.startswith("sqlite3"):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    return engine


def get_session(engine: Engine | None = None) -> Session:
    """Return a new SQLAlchemy Session bound to the provided or default engine."""
    if engine is None:
        engine = get_engine()
    return Session(bind=engine)


def init_db(engine: Engine | None = None, drop: bool = False) -> None:
    """Initialize database tables according to declarative models.

    Args:
        engine: Optional Engine instance. If None, default engine is created.
        drop: If True, drop existing tables before creating them.
    """
    if engine is None:
        engine = get_engine()

    if drop:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
