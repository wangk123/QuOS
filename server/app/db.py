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
        _sync_schema(_engine)
    return _engine


def _sync_schema(eng: Engine) -> None:
    """create_all 不改既有表:启动时幂等补列、删废列(存量 quos.db 零手工迁移)。"""
    from sqlalchemy import text as _text

    patches = {
        "docdraft": ["one_pager_md"],
        "docversion": ["one_pager_md"],
        "project": ["status", "version"],
    }
    drops = {"project": ["archived"]}
    with eng.begin() as conn:
        for table, cols in patches.items():
            have = {r[1] for r in conn.execute(_text(f"PRAGMA table_info({table})"))}
            for col in cols:
                if col not in have:
                    conn.execute(_text(f"ALTER TABLE {table} ADD COLUMN {col} TEXT"))
        for table, cols in drops.items():
            have = {r[1] for r in conn.execute(_text(f"PRAGMA table_info({table})"))}
            for col in cols:
                if col in have:
                    conn.execute(_text(f"ALTER TABLE {table} DROP COLUMN {col}"))
        # 补列后存量行回填默认值,不留 NULL(旧行无治理状态/版本)
        conn.execute(_text("UPDATE project SET status='in_progress' WHERE status IS NULL"))
        conn.execute(_text("UPDATE project SET version='1.0.0' WHERE version IS NULL"))
        try:
            conn.execute(_text("CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_name ON project(name)"))
        except Exception as exc:  # 存量重名建不了索引:API 层查重兜底,不阻塞启动
            print(f"[db] 名称唯一索引创建跳过(存量重名?): {exc}")


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
