"""SQLite 引擎与会话依赖。quos.db 为唯一真相源(ADR-002)。"""
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  确保表注册

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DATA_DIR / 'quos.db'}",
            connect_args={"check_same_thread": False},
        )
        event.listens_for(_engine, "connect")(_set_wal)
        SQLModel.metadata.create_all(_engine)
    return _engine


def _set_wal(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_session():
    with Session(get_engine()) as session:
        yield session


def reset_engine_for_tests():
    """测试与工具用:重置全局引擎。"""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
