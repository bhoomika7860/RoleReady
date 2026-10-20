"""Database engine and session factory (SQLAlchemy 2, sync psycopg 3 driver)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(url: str | None = None, connect_args: dict | None = None) -> Engine:
    """Create the global engine. Tests call this with an isolated database URL."""
    global _engine, _SessionLocal
    settings = get_settings()
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(
        url or settings.sqlalchemy_url(),
        connect_args=connect_args if connect_args is not None else settings.db_connect_args(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=300,
        future=True,
    )
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, rolled back if the handler raises."""
    db = session_factory()()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def bulk_insert(db: Session, model, rows: list[dict]) -> None:
    """Insert many rows in ONE statement (multi-row VALUES). With a remote database each statement is a
    network round trip, so per-row ORM inserts are avoided on hot paths. Rows must share the same keys."""
    if not rows:
        return
    keys = set(rows[0])
    for r in rows:
        if set(r) != keys:
            raise ValueError("bulk_insert rows must have identical keys")
    db.execute(insert(model).values(rows))


@contextmanager
def session_scope() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
