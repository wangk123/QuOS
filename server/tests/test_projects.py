# server/tests/test_projects.py
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

import pymysql

from app.main import app
from app.storage import db
from app.storage import project


def test_env_config_missing_means_disabled(monkeypatch):
    for k in ("QUOS_DB_HOST", "QUOS_PORT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("QUOS_DB_PORT", raising=False)
    db._reset_for_test()
    assert db.connect() is None


def test_reconcile_degrades_to_empty(monkeypatch, tmp_path):
    # DB 禁用：对账返回空 dict，不抛异常
    monkeypatch.delenv("QUOS_DB_HOST", raising=False)
    db._reset_for_test()
    assert db.reconcile([{"slug": "x", "name": "x", "description": "",
                          "created_at": "2026-09-24T00:00:00", "status": "active"}]) == {}


def test_ensure_schema_degrades_on_mysql_error(monkeypatch):
    # 半可达（如权限错误）：建表抛 MySQLError 时 ensure_schema 不抛、静默降级
    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            raise pymysql.MySQLError("access denied")

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(db, "connect", lambda: _FakeConn())
    db._reset_for_test()
    db.ensure_schema()  # 不抛即通过


def test_reconcile_returns_iso_string_last_opened(monkeypatch):
    # pymysql 默认 converter 把 DATETIME 解码为 datetime 对象；契约要求行内字段一律 str（ISO）
    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, *args):
            if sql.startswith("SELECT slug, IFNULL"):
                self._rows = [("x", datetime(2026, 9, 24, 10, 0, 0))]
            else:  # CREATE TABLE / 幽灵行 SELECT / INSERT / DELETE
                self._rows = []

        def fetchall(self):
            return self._rows

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(db, "connect", lambda: _FakeConn())
    db._reset_for_test()
    out = db.reconcile([{"slug": "x", "name": "x", "description": "",
                         "created_at": "2026-09-24T00:00:00", "status": "active"}])
    assert out == {"x": {"last_opened_at": "2026-09-24T10:00:00"}}


def _rec_db(monkeypatch, table):
    """记录 execute 调用并按 status 过滤幽灵 SELECT 的假连接；table=[(slug,status)]"""
    calls = []

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, args=None):
            calls.append((sql, args))
            if sql.startswith("SELECT slug FROM projects WHERE"):
                self._rows = [(s,) for s, st in table if st in args]
            elif sql.startswith("SELECT slug, IFNULL"):
                self._rows = [(s, "") for s, _ in table]
            else:
                self._rows = []

        def fetchall(self):
            return self._rows

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(db, "connect", lambda: _FakeConn())
    db._reset_for_test()
    return calls


def test_reconcile_ghost_cleanup_scoped_by_status(monkeypatch):
    # 单侧对账只清本 status 域的幽灵行：active 行对账删域内幽灵 c，不删 archived 行 b
    calls = _rec_db(monkeypatch, [("a", "active"), ("b", "archived"), ("c", "active")])
    db.reconcile([{"slug": "a", "name": "a", "description": "",
                   "created_at": "2026-09-24T00:00:00", "status": "active"}])
    ghost_select = next(c for c in calls if c[0].startswith("SELECT slug FROM projects"))
    assert "WHERE status IN" in ghost_select[0] and ghost_select[1] == ("active",)
    deletes = [c for c in calls if c[0].startswith("DELETE")]
    assert deletes == [("DELETE FROM projects WHERE slug=%s", ("c",))]


def test_reconcile_scoped_empty_rows_deletes_nothing(monkeypatch):
    # reconcile([]) 是纯查询语义：不清任何幽灵行
    calls = _rec_db(monkeypatch, [("a", "active"), ("b", "archived")])
    out = db.reconcile([])
    assert [c for c in calls if c[0].startswith(("DELETE", "INSERT"))] == []
    assert out == {"a": {"last_opened_at": None}, "b": {"last_opened_at": None}}


def test_reconcile_skips_empty_created_at(monkeypatch):
    # 手工目录（无 project.json，created_at="")不进索引，也不阻塞其他行 upsert
    calls = _rec_db(monkeypatch, [])
    db.reconcile([
        {"slug": "手工目录", "name": "手工目录", "description": "",
         "created_at": "", "status": "active"},
        {"slug": "正常项目", "name": "正常项目", "description": "",
         "created_at": "2026-09-24T00:00:00", "status": "active"},
    ])
    inserts = [c for c in calls if c[0].strip().startswith("INSERT")]
    assert len(inserts) == 1 and inserts[0][1][0] == "正常项目"


@pytest.fixture
def fs(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "DATA_DIR", tmp_path)
    monkeypatch.setattr(project, "ARCHIVE_DIR", tmp_path / ".archived")
    return tmp_path


def test_scan_discovers_manual_dir(fs):
    (fs / "手工目录").mkdir()
    rows = project.scan("active")
    assert rows == [{"slug": "手工目录", "name": "手工目录",
                     "description": "", "created_at": ""}]


def test_create_then_scan_with_json(fs):
    row = project.create("风控云", "核心账务")
    assert (fs / "风控云" / "project.json").exists()
    assert row["slug"] == "风控云" and row["description"] == "核心账务"
    assert project.scan("active")[0]["name"] == "风控云"


def test_create_rejects_duplicate_active_and_archived(fs):
    project.create("同名")
    with pytest.raises(ValueError):
        project.create("同名")
    project.archive("同名")
    with pytest.raises(ValueError):  # 归档侧同名同样拒绝
        project.create("同名")


def test_archive_restore_cycle(fs):
    project.create("p1")
    project.archive("p1")
    assert project.scan("active") == [] and project.scan("archived")[0]["slug"] == "p1"
    (fs / "p1").mkdir()  # 活跃侧出现同名目录（手工目录即合法项目）
    with pytest.raises(ValueError):  # 活跃侧已有同名 → 恢复拒绝
        project.restore("p1")
    (fs / "p1").rmdir()  # 冲突消除
    project.restore("p1")
    assert project.scan("active")[0]["slug"] == "p1"


def test_purge_only_archived(fs):
    project.create("p1")
    with pytest.raises(ValueError):
        project.purge("p1")  # 活跃态禁止彻底删除
    project.archive("p1")
    project.purge("p1")
    assert project.scan("archived") == [] and not (project.ARCHIVE_DIR / "p1").exists()


def test_require_root_missing_raises(fs):
    with pytest.raises(project.ProjectNotFound):
        project.require_root("不存在的项目")
    assert not (fs / "不存在的项目").exists()  # 且不凭空建目录


# ---------- 项目 API（Task 3）----------

@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "DATA_DIR", tmp_path)
    monkeypatch.setattr(project, "ARCHIVE_DIR", tmp_path / ".archived")
    monkeypatch.delenv("QUOS_DB_HOST", raising=False)  # DB 禁用路径
    db._reset_for_test()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_project_crud_flow(client):
    r = await client.get("/api/projects")
    assert r.status_code == 200 and r.json() == []
    r = await client.post("/api/projects", json={"name": "风控云", "description": "核心"})
    assert r.status_code == 201 and r.json()["slug"] == "风控云"
    r = await client.post("/api/projects", json={"name": "风控云"})
    assert r.status_code == 409
    r = await client.post("/api/projects/风控云/open")
    assert r.status_code == 204
    r = await client.get("/api/projects")
    assert r.json()[0]["last_opened_at"] is None  # DB 禁用：touch 降级，列表仍 200
    r = await client.post("/api/projects/风控云/archive")
    assert r.status_code == 204
    r = await client.get("/api/projects/archived")
    assert r.json()[0]["slug"] == "风控云"
    r = await client.request("DELETE", "/api/projects/风控云")
    assert r.status_code == 204 and project.scan("archived") == []


async def test_list_degrades_without_db(client, monkeypatch):
    project.create("降级项目")
    monkeypatch.setattr(db, "connect", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    r = await client.get("/api/projects")
    assert r.status_code == 200 and r.json()[0]["slug"] == "降级项目"


async def test_unknown_project_404_no_mkdir(client, tmp_path):
    r = await client.get("/api/projects/幽灵项目/tree")
    assert r.status_code == 404
    assert not (tmp_path / "幽灵项目").exists()  # 不凭空建目录


async def test_chinese_slug_roundtrip(client):
    await client.post("/api/projects", json={"name": "风控云"})
    r = await client.post(f"/api/projects/{__import__('urllib.parse', fromlist=['quote']).quote('风控云')}/open")
    assert r.status_code == 204


async def test_purge_active_409(client):
    await client.post("/api/projects", json={"name": "活跃项目"})
    r = await client.request("DELETE", "/api/projects/活跃项目")
    assert r.status_code == 409  # 彻底删除仅限归档态


async def test_create_empty_slug_name_422(client):
    # 清洗后为空的项目名（如纯符号）：422 而非 409"项目已存在"
    r = await client.post("/api/projects", json={"name": "///"})
    assert r.status_code == 422
    assert project.scan("active") == []


async def test_create_overlong_slug_422(client):
    # slug 超 VARCHAR(191)：入口拦截，防超长目录名毒化 reconcile
    r = await client.post("/api/projects", json={"name": "超" * 192})
    assert r.status_code == 422
    assert project.scan("active") == []
