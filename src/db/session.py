"""SQLAlchemy engine + session management."""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..common import config

_engine: Engine = create_engine(
    config.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=5,
    max_overflow=10,
)

_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_engine() -> Engine:
    return _engine


@contextmanager
def get_session() -> Iterator[Session]:
    """Yields a session; commits on success, rolls back on error."""
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def new_session() -> Session:
    """Return a raw session (caller manages lifecycle)."""
    return _SessionFactory()
