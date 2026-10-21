"""db 启动 schema 同步:补列 + 废列幂等删除。"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db import _sync_schema
from app.models import Project


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


def test_sync_schema_adds_project_status_version_with_backfill(tmp_path):
    eng = _legacy_engine(tmp_path)
    with eng.begin() as conn:  # 存量行:补列前入库
        conn.execute(text(
            "INSERT INTO project (name, description, archived, created_at) "
            "VALUES ('旧项目', 'x', 0, '2026-01-01 00:00:00')"))
    _sync_schema(eng)
    assert {"status", "version"} <= _cols(eng, "project")
    with eng.connect() as conn:  # 补列后旧行回填默认值,不留 NULL
        row = conn.execute(text("SELECT status, version FROM project WHERE name='旧项目'")).fetchone()
    assert tuple(row) == ("in_progress", "1.0.0")


def test_sync_schema_creates_unique_name_index(tmp_path):
    eng = _legacy_engine(tmp_path)
    _sync_schema(eng)
    with Session(eng) as s:
        s.add(Project(name="A", description=""))
        s.commit()
        s.add(Project(name="A", description=""))
        with pytest.raises(IntegrityError):
            s.commit()
