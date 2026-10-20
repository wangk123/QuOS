"""db 启动 schema 同步:补列 + 废列幂等删除。"""
from sqlalchemy import create_engine, text

from app.db import _sync_schema


def _legacy_engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE project (id INTEGER NOT NULL PRIMARY KEY, name VARCHAR NOT NULL, "
            "description VARCHAR NOT NULL, archived BOOLEAN NOT NULL, created_at DATETIME NOT NULL)"))
        conn.execute(text("CREATE TABLE docdraft (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE docversion (id INTEGER PRIMARY KEY)"))
    return eng


def _cols(eng, table):
    with eng.connect() as conn:
        return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}


def test_sync_schema_drops_archived_and_is_idempotent(tmp_path):
    eng = _legacy_engine(tmp_path)
    _sync_schema(eng)
    assert "archived" not in _cols(eng, "project")
    assert "one_pager_md" in _cols(eng, "docdraft")
    _sync_schema(eng)
    assert "archived" not in _cols(eng, "project")
