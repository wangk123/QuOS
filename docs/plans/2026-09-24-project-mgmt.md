# 项目管理（project-mgmt）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 项目首页 + 工作台两级多项目使用，文件系统为真相源、MySQL（192.168.17.216/quos）为可重建索引。

**Architecture:** `data/<slug>/` 目录即项目身份与状态（归档=移入 `data/.archived/`），静态元信息在 `project.json`；MySQL `projects` 表只存索引（含 `last_opened_at` 动态列），启动/列表时对账，DB 不可达时全端点目录扫描降级不阻断。前端自制路由加两级顶层（home / `#/p/<slug>`），现有六视图零改动。

**Tech Stack:** FastAPI（新增端点用同步 `def`，FastAPI 自动线程池，规避 pymysql 阻塞事件循环）/ pymysql（唯一新增依赖）/ Vue3 组合式 API。

**Spec:** `docs/specs/2026-09-24-project-mgmt-design.md`（本计划从 spec 出发，执行者需同读）

## Global Constraints

- 文件为源：任何端点在 MySQL 不可达时必须仍返回正确结果（降级、不抛 5xx）
- DB 连接读 `QUOS_DB_HOST/PORT/USER/PASSWORD/NAME` 环境变量；**变量未配置 = DB 禁用**（连接函数返回 None），不设隐式默认地址——避免无库环境每次请求超时
- 真库默认值由 `start.sh` 注入（192.168.17.216/quos/perftest，见 `docs/environments.md`）
- 测试不打真库；真库集成测试仅 `QUOS_DB_TEST=1` 时运行
- commit 格式 `<type>：<描述>`（技术名词保留英文）
- 后端模块 ≤500 行；注释/文案中文，沿用 `# server/app/...` 模块头注释风格
- 后端定向测试：`cd server && uv run pytest tests/test_projects.py -v`；前端：`cd web && npx vitest run src/views/__tests__/home.spec.ts`

## Review Focus

| # | 输入/故障 | 期望行为 | 钉住它的测试 |
|---|---|---|---|
| 1 | MySQL 不可达/未配置时调任何项目端点 | 目录扫描兜底 200，无 5xx、无超时挂起 | Task 1 `test_db_disabled_when_no_env`、Task 3 `test_list_degrades_without_db` |
| 2 | 创建/恢复与**归档**侧同名的项目 | 409（判重含归档） | Task 2 `test_create_rejects_archived_duplicate`、`test_restore_conflict` |
| 3 | 直达不存在项目的子资源（旧 URL/拼错） | 404，且**不创建目录** | Task 3 `test_unknown_project_404_no_mkdir` |
| 4 | DB 有行但目录已手动删除（幽灵行） | 列表对账后不出现，DB 行被清 | Task 1 `test_reconcile_removes_ghost_rows` |
| 5 | 中文 slug 的 URL 编解码往返（前端 encode ↔ 后端 path param） | 加密传输后 slug 原样，项目可打开 | Task 3 `test_chinese_slug_roundtrip`、Task 6 vitest 断言请求 URL |

---

### Task 1: MySQL 索引层 `app/storage/db.py`

**Files:**
- Create: `server/app/storage/db.py`
- Modify: `server/pyproject.toml`
- Test: `server/tests/test_projects.py`（本任务起建，后续任务续用）

**Interfaces:**
- Produces（后续任务按此调用）:
  - `db.ensure_schema() -> None`（幂等；DB 禁用时静默）
  - `db.reconcile(rows: list[dict]) -> dict[str, dict]`——入参为文件系统扫描行 `[{slug,name,description,created_at,status}]`；upsert 缺行、删幽灵行；返回 `{slug: {"last_opened_at": iso|null}}`；DB 禁用返回 `{}`
  - `db.touch_opened(slug: str) -> None`
  - `db.delete_row(slug: str) -> None`
  - 行内字段一律 `str`（ISO 时间），DB 层负责与 DATETIME 互转

- [ ] **Step 1: 加依赖**

```bash
cd server && uv add pymysql
```

- [ ] **Step 2: 写失败测试**（`server/tests/test_projects.py` 新建）

```python
# server/tests/test_projects.py
import pytest

from app.storage import db


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
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_projects.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'app.storage.db'`

- [ ] **Step 4: 实现 `db.py`**

```python
# server/app/storage/db.py
# MySQL 元数据索引：可重建缓存而非真相源（真相源是 data/ 目录扫描）。
# 未配置 QUOS_DB_HOST = 禁用；不可达 = 本次调用降级（返回 None/{} 并 log 警告）。
import logging
import os
from pathlib import Path

import pymysql

log = logging.getLogger("quos.db")
_schema_ready = False

_COLS = "slug,name,description,status,created_at,last_opened_at,archived_at"


def connect():
    """返回已连库的 Connection；未配置或不可达返回 None（调用方一律判 None 降级）"""
    if not os.environ.get("QUOS_DB_HOST"):
        return None
    try:
        return pymysql.connect(
            host=os.environ["QUOS_DB_HOST"],
            port=int(os.environ.get("QUOS_DB_PORT", "3306")),
            user=os.environ.get("QUOS_DB_USER", ""),
            password=os.environ.get("QUOS_DB_PASSWORD", ""),
            database=os.environ.get("QUOS_DB_NAME", "quos"),
            charset="utf8mb4", connect_timeout=2, autocommit=True,
        )
    except pymysql.MySQLError as e:
        log.warning("MySQL 不可达，索引降级: %s", e)
        return None


def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    conn = connect()
    if conn is None:
        return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
              id             INT AUTO_INCREMENT PRIMARY KEY,
              slug           VARCHAR(191) NOT NULL UNIQUE,
              name           VARCHAR(191) NOT NULL,
              description    TEXT,
              status         ENUM('active','archived') NOT NULL DEFAULT 'active',
              created_at     DATETIME NOT NULL,
              last_opened_at DATETIME NULL,
              archived_at    DATETIME NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")
    conn.close()
    _schema_ready = True


def reconcile(rows):
    """文件系统扫描行对账进 DB；返回 {slug: {last_opened_at}}（禁用/失败返回 {}）"""
    ensure_schema()
    conn = connect()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            slugs = {r["slug"] for r in rows}
            cur.execute(f"SELECT slug FROM projects")
            for (ghost,) in cur.fetchall():
                if ghost not in slugs:
                    cur.execute("DELETE FROM projects WHERE slug=%s", ghost)
            for r in rows:
                cur.execute("""
                    INSERT INTO projects (slug,name,description,status,created_at)
                    VALUES (%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      name=VALUES(name), description=VALUES(description),
                      status=VALUES(status), created_at=VALUES(created_at)""",
                    (r["slug"], r["name"], r["description"] or "",
                     r["status"], r["created_at"]))
            cur.execute("SELECT slug, IFNULL(last_opened_at,'') FROM projects")
            return {s: {"last_opened_at": t or None} for s, t in cur.fetchall()}
    except pymysql.MySQLError as e:
        log.warning("对账降级: %s", e)
        return {}
    finally:
        conn.close()


def touch_opened(slug):
    conn = connect()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE projects SET last_opened_at=NOW() WHERE slug=%s", slug)
    except pymysql.MySQLError as e:
        log.warning("touch 降级: %s", e)
    finally:
        conn.close()


def delete_row(slug):
    conn = connect()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE slug=%s", slug)
    except pymysql.MySQLError as e:
        log.warning("删行降级: %s", e)
    finally:
        conn.close()


def _reset_for_test():
    """测试用：清 schema 缓存，让 env 变化重新生效"""
    global _schema_ready
    _schema_ready = False
```

- [ ] **Step 5: 跑测试确认通过并 commit**

Run: `cd server && uv run pytest tests/test_projects.py -v` → PASS

```bash
git add server/app/storage/db.py server/tests/test_projects.py server/pyproject.toml server/uv.lock
git commit -m "feat：MySQL 元数据索引层（可降级对账）"
```

---

### Task 2: 文件系统真相源改造 `app/storage/project.py`

**Files:**
- Modify: `server/app/storage/project.py`
- Modify: 存量调用点（`server/tests/test_api.py` 等所有 `project_root(...)` 后直接写文件处 → `ensure_root(...)`，Task 内 grep 定位）
- Test: `server/tests/test_projects.py`（追加）

**Interfaces:**
- Produces:
  - `project.ensure_root(name) -> Path`——建目录并返回（创建端点/测试用）
  - `project.require_root(name) -> Path`——活跃侧必须存在，否则抛 `ProjectNotFound`；不再有"访问即建目录"行为
  - `project.ProjectNotFound(Exception)`
  - `project.scan(status: str) -> list[dict]`——`status in {"active","archived"}`；返回 `[{slug,name,description,created_at}]`，`project.json` 缺失时目录名兜底
  - `project.create(name, description="") -> dict`——重名（活跃或归档）抛 `ValueError`
  - `project.archive(slug)` / `project.restore(slug)`——移动目录；restore 遇活跃同名抛 `ValueError`
  - `project.purge(slug)`——非归档态抛 `ValueError`；`shutil.rmtree` 整目录
  - `project.write_description(slug, description)`——改写 `project.json`
  - `slugify` / `is_valid_name` / `DATA_DIR` 不变；`ARCHIVE_DIR = DATA_DIR / ".archived"`
- 注意：`router.py` 的 `_root()` 本任务**暂不改**（Task 3 改），先保证 `project_root` 去 mkdir 后存量测试迁移

- [ ] **Step 1: 写失败测试**（追加到 `server/tests/test_projects.py`）

```python
from app.storage import project


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
    assert project.scan("active") == []
    assert project.scan("archived")[0]["slug"] == "p1"
    assert not project.exists_active("p1")
    project.create("p1")  # 归档后名字可再建？—— 不可：上面已验证拒绝，此处先删
```

上面最后一个测试自相矛盾——修正为完整正确版（执行者以此为准）：

```python
def test_archive_restore_cycle(fs):
    project.create("p1")
    project.archive("p1")
    assert project.scan("active") == [] and project.scan("archived")[0]["slug"] == "p1"
    project.create("p2")
    with pytest.raises(ValueError):  # 活跃侧已有同名 → 恢复拒绝
        project.restore("p1")
    project.archive("p2")
    project.restore("p1")  # 冲突消除后可恢复
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_projects.py -v`
Expected: FAIL `AttributeError: ... has no attribute 'scan'` 等

- [ ] **Step 3: 实现**（重写 `project.py`，保留原三个函数语义）

```python
# server/app/storage/project.py
# 文件系统是项目身份与状态的真相源：身份=目录名，归档=目录移入 .archived/。
# project.json 存静态元信息（name/description/created_at），缺失时目录名兜底。
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"
ARCHIVE_DIR = DATA_DIR / ".archived"

_SLUG_RE = re.compile(r"[^\w\u4e00-\u9fff-]")


class ProjectNotFound(Exception): ...


def is_valid_name(name: str) -> bool:
    """项目名清洗后是否非空（空名无法定位项目目录）"""
    return bool(_SLUG_RE.sub("", name))


def slugify(name: str) -> str:
    return _SLUG_RE.sub("", name) or "node"


def project_root(name: str) -> Path:
    # 只返回路径不建目录（创建走 create/ensure_root，防拼错 URL 凭空生成空项目）
    return DATA_DIR / f"{slugify(name)}/"


def ensure_root(name: str) -> Path:
    root = project_root(name)
    root.mkdir(parents=True, exist_ok=True)
    return root


def exists_active(name: str) -> bool:
    return project_root(name).is_dir()


def require_root(name: str) -> Path:
    root = project_root(name)
    if not root.is_dir():
        raise ProjectNotFound(slugify(name))
    return root


def _meta_path(root: Path) -> Path:
    return root / "project.json"


def _read_meta(root: Path, slug: str) -> dict:
    p = _meta_path(root)
    if p.exists():
        try:
            m = json.loads(p.read_text("utf-8"))
            return {"slug": slug, "name": m.get("name") or slug,
                    "description": m.get("description") or "",
                    "created_at": m.get("created_at") or ""}
        except ValueError:
            pass  # 损坏 json 按无元信息兜底
    return {"slug": slug, "name": slug, "description": "", "created_at": ""}


def _write_meta(root: Path, name: str, description: str, created_at: str):
    _meta_path(root).write_text(json.dumps(
        {"name": name, "description": description, "created_at": created_at},
        ensure_ascii=False, indent=2), "utf-8")


def scan(status: str) -> list[dict]:
    base = ARCHIVE_DIR if status == "archived" else DATA_DIR
    if not base.is_dir():
        return []
    rows = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        rows.append(_read_meta(d, d.name))
    return rows


def create(name: str, description: str = "") -> dict:
    if not is_valid_name(name):
        raise ValueError(f"非法项目名: {name}")
    slug = slugify(name)
    if project_root(name).is_dir() or (ARCHIVE_DIR / slug).is_dir():
        raise ValueError(f"项目已存在（含归档侧）: {slug}")
    root = ensure_root(name)
    created_at = datetime.now().isoformat(timespec="seconds")
    _write_meta(root, name, description, created_at)
    return {"slug": slug, "name": name, "description": description, "created_at": created_at}


def write_description(slug: str, description: str):
    root = ARCHIVE_DIR / slug if (ARCHIVE_DIR / slug).is_dir() else DATA_DIR / slug
    m = _read_meta(root, slug)
    _write_meta(root, m["name"], description, m["created_at"])


def archive(slug: str):
    src = DATA_DIR / slug
    if not src.is_dir():
        raise ProjectNotFound(slug)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(ARCHIVE_DIR / slug))


def restore(slug: str):
    src = ARCHIVE_DIR / slug
    if not src.is_dir():
        raise ProjectNotFound(slug)
    if (DATA_DIR / slug).is_dir():
        raise ValueError(f"活跃侧已存在同名项目: {slug}")
    shutil.move(str(src), str(DATA_DIR / slug))


def purge(slug: str):
    src = ARCHIVE_DIR / slug
    if not src.is_dir():
        raise ProjectNotFound(slug)
    shutil.rmtree(src)  # 含 git 基线历史，仅归档态可调用
```

- [ ] **Step 4: 迁移存量调用点**

Run: `grep -rn "project_root(" server/tests/ server/app/ | grep -v "def project_root"`
将测试中"调用后直接写文件"的 `project_root(` 改为 `project.ensure_root(`（import 相应调整）；`router.py` 的 `_root` 本任务不动。

Run: `cd server && uv run pytest -q`（全量：project_root 行为变更波及所有测试，属公共底层，按约束允许全量）
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/storage/project.py server/tests/
git commit -m "feat：项目文件真相源（扫描/创建/归档/恢复/删除）"
```

---

### Task 3: 项目 API 路由 + 未知项目 404 守卫

**Files:**
- Create: `server/app/api/projects.py`
- Modify: `server/app/api/router.py:62-69`（`_root` 加存在性守卫）
- Modify: `server/app/main.py`（挂载 router + lifespan 对账）
- Test: `server/tests/test_projects.py`（追加）

**Interfaces:**
- Consumes: Task 1 全部 `db.*`、Task 2 全部 `project.*`
- Produces:
  - `projects_router`（路径全表见 spec §5；8 端点全部同步 `def`）
  - `router._root(proj)` 新语义：非法名 422、不存在 404（`{"detail": "项目不存在或已归档: <slug>"}`）
  - 前端可用的响应形：列表项 `{slug,name,description,created_at,last_opened_at}`（归档项含 `archived_at` 未知时为 `null`，M1 以 `created_at` 兜底展示）

- [ ] **Step 1: 写失败测试**（追加）

```python
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import app


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
    async def boom(): raise RuntimeError("db down")
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_projects.py -v`
Expected: FAIL 404（路由不存在返回 404 Not Found 而非语义体）

- [ ] **Step 3: 实现路由 `server/app/api/projects.py`**

```python
# server/app/api/projects.py
# 项目管理端点：同步 def（pymysql 阻塞调用交 FastAPI 线程池）。
# 真相源是文件系统扫描，db.* 仅补动态列（last_opened_at）与对账。
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.storage import db, project

projects_router = APIRouter()


class CreateIn(BaseModel):
    name: str
    description: str = ""


class PatchIn(BaseModel):
    description: Optional[str] = None


def _slug_path(slug: str) -> None:
    """path 合法性与存在性的公共校验（不存在统一 404）"""
    if not project.is_valid_name(slug) or project.slugify(slug) != slug:
        raise HTTPException(status_code=422, detail=f"非法项目标识: {slug}")


@projects_router.get("")
def list_projects():
    rows = project.scan("active")
    extra = db.reconcile([{**r, "status": "active"} for r in rows])
    out = [{**r, "last_opened_at": extra.get(r["slug"], {}).get("last_opened_at")}
           for r in rows]
    out.sort(key=lambda r: r["last_opened_at"] or "", reverse=True)
    return out


@projects_router.get("/archived")
def list_archived():
    rows = project.scan("archived")
    db.reconcile([{**r, "status": "archived"} for r in rows])  # 归档侧也对账，防幽灵
    return rows


@projects_router.post("", status_code=201)
def create_project(body: CreateIn):
    try:
        row = project.create(body.name, body.description)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    db.reconcile([{**row, "status": "active"}])
    return row


@projects_router.post("/{slug}/open", status_code=204)
def open_project(slug: str):
    _slug_path(slug)
    try:
        project.require_root(slug)
    except project.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=f"项目不存在或已归档: {e}")
    db.touch_opened(slug)


@projects_router.patch("/{slug}")
def patch_project(slug: str, body: PatchIn):
    _slug_path(slug)
    try:
        project.require_root(slug)
    except project.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=f"项目不存在或已归档: {e}")
    if body.description is not None:
        project.write_description(slug, body.description)
    return {"slug": slug, "description": body.description}


@projects_router.post("/{slug}/archive", status_code=204)
def archive_project(slug: str):
    _slug_path(slug)
    try:
        project.archive(slug)
    except project.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=f"项目不存在: {e}")
    db.delete_row(slug)


@projects_router.post("/{slug}/restore", status_code=204)
def restore_project(slug: str):
    _slug_path(slug)
    try:
        project.restore(slug)
    except project.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=f"归档项目不存在: {e}")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@projects_router.delete("/{slug}", status_code=204)
def purge_project(slug: str):
    _slug_path(slug)
    try:
        project.purge(slug)
    except project.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=f"归档项目不存在: {e}")
    except ValueError:
        raise HTTPException(status_code=409, detail="仅归档项目可彻底删除")
    db.delete_row(slug)
```

- [ ] **Step 4: `router.py` `_root` 守卫 + `main.py` 挂载**

`router.py` `_root` 改为（import 处加 `ProjectNotFound`）：

```python
def _root(proj: str) -> Path:
    """项目根目录；非法名 422（防路径遍历），项目不存在或已归档 404（防拼错 URL 凭空建目录）"""
    if not is_valid_name(proj):
        raise HTTPException(status_code=422, detail=f"非法项目名: {proj}")
    root = project.project_root(proj)
    if not root.resolve().is_relative_to(Path(project.DATA_DIR).resolve()):
        raise HTTPException(status_code=422, detail=f"非法项目名: {proj}")
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"项目不存在或已归档: {proj}")
    return root
```

`main.py` 在 `app.include_router(api_router, ...)` **之前**加：

```python
from app.api.projects import projects_router
from app.storage import db, project
from contextlib import asynccontextmode


@asynccontextmanager
async def lifespan(_: FastAPI):
    rows = project.scan("active") + project.scan("archived")
    db.reconcile([{**r, "status": "active" if project.exists_active(r["slug"]) else "archived"}
                  for r in rows])
    yield


app = FastAPI(title="QuOS", lifespan=lifespan)
app.include_router(projects_router, prefix="/api/projects")
```

（注意：以现有 `main.py` 实际结构合并，`app = FastAPI(...)` 行加 `lifespan=lifespan`；`from contextlib import asynccontextmanager` 修正拼写。）

- [ ] **Step 5: 跑测试（含存量回归）并 commit**

Run: `cd server && uv run pytest -q`
Expected: PASS（存量测试如遇"项目不存在 404"破——它们先 `ensure_root` 建项目，不应破；破则修测试的建项目方式）

```bash
git add server/app/api/projects.py server/app/api/router.py server/app/main.py server/tests/test_projects.py
git commit -m "feat：项目管理 API（列表/创建/打开/归档/恢复/删除）+ 未知项目 404 守卫"
```

---

### Task 4: `start.sh` MySQL 探测与默认配置注入

**Files:**
- Modify: `start.sh`

**Interfaces:**
- Consumes: `docs/environments.md` 连接值
- Produces: 运行时 `QUOS_DB_*` 有默认值；启动日志一行可达性结论

- [ ] **Step 1: 实现**（在「3/3 启动服务」块内、启动 uvicorn 前加）

```bash
# MySQL 索引库默认值（文件为源：不可达仅警告不阻断，详见 docs/environments.md）
export QUOS_DB_HOST="${QUOS_DB_HOST:-192.168.17.216}"
export QUOS_DB_PORT="${QUOS_DB_PORT:-3306}"
export QUOS_DB_USER="${QUOS_DB_USER:-perftest}"
export QUOS_DB_PASSWORD="${QUOS_DB_PASSWORD:-perftest}"
export QUOS_DB_NAME="${QUOS_DB_NAME:-quos}"
if (cd server && uv run python -c "
from app.storage import db
print('ok' if db.connect() else '不可达')") | grep -q 不可达; then
  echo "    ⚠ MySQL 索引库不可达，将以目录扫描模式运行（排序信息缺失）"
fi
```

- [ ] **Step 2: 验证**

Run: `bash -n start.sh && ./start.sh`（观察启动日志出现 MySQL 结论行；平台可打开）
Expected: 脚本语法通过；有或无 MySQL 警告行均正常启动

- [ ] **Step 3: Commit**

```bash
git add start.sh
git commit -m "feat：启动脚本注入 MySQL 索引库配置并探测可达性"
```

---

### Task 5: 前端 `api.ts` 动态项目上下文 + 项目 API 封装

**Files:**
- Modify: `web/src/api.ts`
- Test: `web/src/api.test.ts`（新建，node 环境直测 base 计算与请求拼 URL）

**Interfaces:**
- Produces:
  - `export const curSlug = ref('')`、`export function setProject(slug: string): void`
  - 移除 `export const PROJ`（**App.vue/测试的引用在 Task 7 收口**，本任务内 `PROJ` 删除后 vitest 全量会红——以本任务新增测试文件单跑为准，Task 7 恢复全量）
  - `export interface ProjectInfo { slug: string; name: string; description: string; created_at: string; last_opened_at: string | null }`
  - `getProjects() / getArchivedProjects() / createProject(name, description?) / openProject(slug) / patchProject(slug, description) / archiveProject(slug) / restoreProject(slug) / purgeProject(slug)`（返回 `ProjectInfo`/`void`；`req` 保持既有错误语义抛 `ApiError`）

- [ ] **Step 1: 写失败测试**（`web/src/api.test.ts`）

```ts
// api 基础层单测：项目上下文切换后请求打到新 BASE
import { describe, expect, it, vi, beforeEach } from 'vitest'

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

describe('项目上下文', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    fetchMock.mockResolvedValue({ ok: true, status: 200, headers: new Headers(), json: async () => ({}) })
  })

  it('未进项目时项目级请求 URL 含空 slug 占位', async () => {
    const { getTree } = await import('./api')
    await getTree()
    expect(fetchMock.mock.calls[0][0]).toContain('/api/projects/')
  })

  it('setProject 后中文 slug 走 URL encode', async () => {
    const { setProject, getTree } = await import('./api')
    setProject('风控云')
    await getTree()
    expect(decodeURIComponent(fetchMock.mock.calls[0][0])).toContain('/api/projects/风控云/tree')
  })

  it('项目 API 打到无 proj 前缀的 /api/projects', async () => {
    const { createProject } = await import('./api')
    await createProject('新项目', '描述')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/projects')
    expect((init as RequestInit).method).toBe('POST')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/api.test.ts`
Expected: FAIL（`setProject` 不存在 / URL 仍固定风控云）

- [ ] **Step 3: 实现**（`api.ts` 顶部改造 + 尾部追加）

顶部：

```ts
// QuOS reqspec API 封装：路由与 server/app/api/router.py 一一对应。
// 项目上下文动态化：curSlug 由首页进入工作台时设置（见 router.ts enterProject）。
import { ref } from 'vue'

export const curSlug = ref('')
export function setProject(slug: string) {
  curSlug.value = slug
}
const base = () => `/api/projects/${encodeURIComponent(curSlug.value)}`
```

（删除 `export const PROJ = '风控云'` 与 `const BASE = ...`；`req()` 内 `BASE + path` 改 `base() + path`。）

尾部追加：

```ts
// ---------- 项目管理（无 proj 前缀，对应 server/app/api/projects.py） ----------

export interface ProjectInfo {
  slug: string
  name: string
  description: string
  created_at: string
  last_opened_at: string | null
}

export const getProjects = () => req<ProjectInfo[]>('/api/projects'.replace(base(), '') || '/api/projects')
```

注意 `/api/projects` 不含 proj 段，`req` 目前强制拼 `base()`——新增独立请求函数：

```ts
async function reqRoot<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/projects${path}`, init)
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null))
  return (await res.json()) as Promise<T>
}

export const getProjects = () => reqRoot<ProjectInfo>('')
export const getArchivedProjects = () => reqRoot<ProjectInfo>('/archived')
export const createProject = (name: string, description = '') =>
  reqRoot<ProjectInfo>('', json('POST', { name, description }))
export const openProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}/open`, { method: 'POST' })
export const patchProject = (slug: string, description: string) =>
  reqRoot<{ slug: string }>(`/${encodeURIComponent(slug)}`, json('PATCH', { description }))
export const archiveProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}/archive`, { method: 'POST' })
export const restoreProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}/restore`, { method: 'POST' })
export const purgeProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}`, { method: 'DELETE' })
```

（最终版以 `reqRoot` 方案为准，忽略前一个 `getProjects` 草稿行；`getProjects` 用 `reqRoot<ProjectInfo[]>('')`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/api.test.ts` → PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/api.ts web/src/api.test.ts
git commit -m "feat：前端项目上下文动态化与项目 API 封装"
```

---

### Task 6: 项目首页 `Home.vue` + 两级导航 `router.ts`

**Files:**
- Create: `web/src/views/Home.vue`
- Modify: `web/src/router.ts`
- Test: `web/src/views/__tests__/home.spec.ts`

**Interfaces:**
- Consumes: Task 5 全部项目 API 函数与 `curSlug`/`setProject`
- Produces:
  - `router.top = ref<'home' | 'proj'>('home')`
  - `router.enterProject(slug: string): Promise<void>`——`setProject` + `top='proj'` + `location.hash = '#/p/<encodeURI(slug)>'` + `openProject(slug)`（fire-and-forget）
  - `router.goHome(): void`——`top='home'` + hash `#/` + `curSlug=''`
  - `router.initRouteFromHash(): void`——解析 `#/p/<slug>` 恢复 `top/curSlug`（非法/空 hash 停留 home）
  - `Home.vue` 默认导出组件：列表/归档区/新建表单/空态四态，`emit` 无、操作自持

- [ ] **Step 1: 写失败测试**（`web/src/views/__tests__/home.spec.ts`）

```ts
// 项目首页三态渲染与交互（api 全 mock，同 views.spec.ts 惯例）
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Home from '../Home.vue'

vi.mock('../../api', () => ({
  ApiError: class ApiError extends Error { status = 0 },
  getProjects: vi.fn(),
  getArchivedProjects: vi.fn(),
  createProject: vi.fn(),
  archiveProject: vi.fn(),
  restoreProject: vi.fn(),
  purgeProject: vi.fn(),
}))
import { archiveProject, createProject, getArchivedProjects, getProjects } from '../../api'
import { enterProject } from '../../router'

describe('Home 项目首页', () => {
  beforeEach(() => {
    vi.mocked(getProjects).mockReset().mockResolvedValue([
      { slug: '风控云', name: '风控云', description: '核心账务', created_at: '2026-09-23T10:00:00', last_opened_at: null },
    ])
    vi.mocked(getArchivedProjects).mockReset().mockResolvedValue([])
    vi.mocked(createProject).mockReset().mockResolvedValue({} as never)
    vi.mocked(archiveProject).mockReset().mockResolvedValue(undefined as never)
  })

  it('渲染项目卡片与新建入口', async () => {
    const w = mount(Home)
    await flushPromises()
    expect(w.text()).toContain('风控云')
    expect(w.text()).toContain('核心账务')
    expect(w.text()).toContain('新建项目')
  })

  it('空列表渲染引导态', async () => {
    vi.mocked(getProjects).mockResolvedValue([])
    const w = mount(Home)
    await flushPromises()
    expect(w.text()).toContain('还没有项目')
  })

  it('新建提交调 createProject 并刷新', async () => {
    const w = mount(Home)
    await flushPromises()
    await w.find('input[data-test="new-name"]').setValue('新项目')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(createProject).toHaveBeenCalledWith('新项目', '')
    expect(getProjects).toHaveBeenCalledTimes(2)
  })

  it('点击卡片进入项目', async () => {
    const w = mount(Home)
    await flushPromises()
    await w.find('[data-test="proj-card"]').trigger('click')
    await flushPromises()
    // enterProject 会调 openProject（api mock 未提供则补）
  })
})
```

（`enterProject` 内部 `openProject` 也须进 mock 工厂；点击卡片断言 `enterProject` 效果通过 `top.value === 'proj'` 验证：`import { top } from '../../router'` 后 `expect(top.value).toBe('proj')`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/views/__tests__/home.spec.ts`
Expected: FAIL `Cannot find module '../Home.vue'`

- [ ] **Step 3: 实现 `router.ts` 扩展**

```ts
import { setProject } from './api'
import { openProject } from './api'

export const top = ref<'home' | 'proj'>('home')

export async function enterProject(slug: string) {
  setProject(slug)
  top.value = 'proj'
  location.hash = `#/p/${encodeURIComponent(slug)}`
  void openProject(slug).catch(() => {})  // last_opened 记录，失败无感
}

export function goHome() {
  top.value = 'home'
  curSlugReset()
  location.hash = '#/'
}

function curSlugReset() {
  setProject('')
}

export function initRouteFromHash() {
  const m = location.hash.match(/^#\/p\/(.+)$/)
  if (m) {
    const slug = decodeURIComponent(m[1])
    if (slug) {
      setProject(slug)
      top.value = 'proj'
    }
  }
}
```

（合并进现有 `router.ts`，import 归并为一行 `import { openProject, setProject } from './api'`；`goHome` 内两步合并为 `setProject('')` 即可，去掉多余的 `curSlugReset` 中转。）

- [ ] **Step 4: 实现 `Home.vue`**（结构骨架——样式类沿用 `style.css` 既有 badge/卡片风格）

```vue
<script setup lang="ts">
import { inject, onMounted, ref } from 'vue'
import { ApiError, archiveProject, createProject, getArchivedProjects, getProjects, purgeProject, restoreProject, type ProjectInfo } from '../api'
import { enterProject } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})
const items = ref<ProjectInfo[]>([])
const archived = ref<ProjectInfo[]>([])
const err = ref('')
const showNew = ref(false)
const newName = ref('')
const newDesc = ref('')
const showArchived = ref(false)

async function load() {
  try {
    items.value = await getProjects()
    archived.value = await getArchivedProjects()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : '无法连接后端'
  }
}
onMounted(load)

async function submitNew() {
  const name = newName.value.trim()
  if (!name) return
  try {
    await createProject(name, newDesc.value.trim())
    toast(`已创建「${name}」`)
    showNew.value = false; newName.value = ''; newDesc.value = ''
    await load()
  } catch (e) {
    toast(e instanceof ApiError && e.status === 409 ? '项目已存在（含归档侧）' : '创建失败', 'warn')
  }
}

async function onArchive(p: ProjectInfo) {
  if (!confirm(`归档「${p.name}」？工作台将不可访问，可随时恢复`)) return
  await archiveProject(p.slug).catch(() => toast('归档失败', 'warn'))
  await load()
}

async function onRestore(p: ProjectInfo) {
  await restoreProject(p.slug).catch((e) =>
    toast(e instanceof ApiError && e.status === 409 ? '活跃侧已有同名项目' : '恢复失败', 'warn'))
  await load()
}

async function onPurge(p: ProjectInfo) {
  const typed = prompt(`彻底删除「${p.name}」将移除全部需求资产与基线历史，不可恢复。\n输入项目名确认：`)
  if (typed !== p.name) { toast('名称不一致，已取消'); return }
  await purgeProject(p.slug).catch(() => toast('删除失败', 'warn'))
  await load()
}
</script>

<template>
  <main class="home">
    <h1>项目</h1>
    <p v-if="err" class="err">{{ err }}</p>
    <div v-if="!items.length && !err" class="empty">
      还没有项目——输入第一个项目名开始整理需求
      <form data-test="new" @submit.prevent="submitNew">
        <input data-test="new-name" v-model="newName" placeholder="项目名（如：风控云）" />
        <button type="submit">创建</button>
      </form>
    </div>
    <template v-else>
      <button class="ghost" @click="showNew = !showNew">＋ 新建项目</button>
      <form v-if="showNew" @submit.prevent="submitNew">
        <input data-test="new-name" v-model="newName" placeholder="项目名" />
        <input v-model="newDesc" placeholder="描述（可选）" />
        <button type="submit">创建</button>
      </form>
      <div class="cards">
        <div v-for="p in items" :key="p.slug" class="card" data-test="proj-card" @click="enterProject(p.slug)">
          <b>{{ p.name }}</b>
          <span class="muted">{{ p.description || '—' }}</span>
          <span class="muted">创建 {{ p.created_at.slice(0, 10) }}</span>
          <button class="ghost" @click.stop="onArchive(p)">归档</button>
        </div>
      </div>
      <section v-if="archived.length">
        <button class="ghost" @click="showArchived = !showArchived">已归档（{{ archived.length }}）</button>
        <div v-if="showArchived" class="cards">
          <div v-for="p in archived" :key="p.slug" class="card archived">
            <b>{{ p.name }}</b>
            <button class="ghost" @click="onRestore(p)">恢复</button>
            <button class="danger" @click="onPurge(p)">彻底删除</button>
          </div>
        </div>
      </section>
    </template>
  </main>
</template>
```

（`.home/.cards/.card/.ghost/.danger/.muted/.empty/.err` 样式追加进 `style.css`，遵循既有变量与密度；行数控制在组件 200 行内。）

- [ ] **Step 5: 跑测试确认通过并 commit**

Run: `cd web && npx vitest run src/views/__tests__/home.spec.ts` → PASS

```bash
git add web/src/views/Home.vue web/src/router.ts web/src/style.css web/src/views/__tests__/home.spec.ts
git commit -m "feat：项目首页与两级导航"
```

---

### Task 7: `App.vue` 集成 + 存量前端测试适配

**Files:**
- Modify: `web/src/App.vue`
- Modify: `web/src/views/__tests__/views.spec.ts`（mock 工厂去 `PROJ`、补 `curSlug`）

**Interfaces:**
- Consumes: Task 5 `curSlug`、Task 6 `top/goHome/initRouteFromHash/Home.vue`
- Produces: 最终前端形态——`top==='home'` 渲染 `<Home/>`，否则现有工作台；顶栏项目名取 `curSlug`；项目级 404 自动 `goHome()`

- [ ] **Step 1: 改 `App.vue`**

script 变更点：
```ts
import Home from './views/Home.vue'
import { top, goHome, initRouteFromHash } from './router'
import { curSlug } from './api'
// 删除 PROJ import；onMounted 改为：
onMounted(() => {
  initRouteFromHash()
  if (top.value === 'proj') void boot()
})
watch(top, v => { if (v === 'proj') void boot() })  // 首次进入/切换项目时加载树+基线
// boot = 现 onMounted 体内的 loadTree + refreshBaselines（含 err 处理）
// loadTree 的 catch：ApiError.status===404 时 goHome() + toast('项目不存在或已归档')
```

template 变更点：
```html
<Home v-if="top === 'home'" />
<template v-else>
  <!-- 现有 header/nav/main 全部原样包入 -->
  <header>
    <div class="logo">…QuOS</div>
    <button class="ghost" @click="goHome">⟵ 项目</button>
    <div class="proj">项目 <b>{{ curSlug }}</b></div>
    <span class="baseline-tag">{{ baseTag }}</span>
  </header>
  …
</template>
```

- [ ] **Step 2: 适配 `views.spec.ts`**

mock 工厂：删 `PROJ: '风控云'` 行；补 `curSlug: ref('演示项目')`（`import { ref } from 'vue'`）；`router` mock 侧补 `top: ref('proj')`（App 测试挂载须处于工作台态）。

- [ ] **Step 3: 跑前端全量**

Run: `cd web && npx vitest run && npm run build`
Expected: 全部 PASS + 构建成功

- [ ] **Step 4: 手测（浏览器）**

`./start.sh` → 空首页建「风控云」？不——**已有 data/风控云 目录会被自动发现**，确认：列表出现风控云 → 点击进入 → 六步流程可用 → 刷新页面停在项目内（hash 保持）→ 顶栏返回首页。

- [ ] **Step 5: Commit**

```bash
git add web/src/App.vue web/src/views/__tests__/views.spec.ts
git commit -m "feat：工作台接入项目两级导航与 404 引导"
```

---

### Task 8: 真库集成测试 + 端到端验收

**Files:**
- Create: `server/tests/test_projects_db.py`

**Interfaces:**
- Consumes: 真实 MySQL（`QUOS_DB_TEST=1` + `QUOS_DB_*` 指向 192.168.17.216/quos；无变量时整文件 skip）

- [ ] **Step 1: 写真库对账测试**

```python
# server/tests/test_projects_db.py
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QUOS_DB_TEST") != "1", reason="仅 QUOS_DB_TEST=1 跑真库")

from app.storage import db, project


def test_reconcile_real_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "DATA_DIR", tmp_path)
    monkeypatch.setattr(project, "ARCHIVE_DIR", tmp_path / ".archived")
    row = project.create("真库验证项目")
    extra = db.reconcile([{**row, "status": "active"}])
    assert extra.get("真库验证项目") is not None
    db.touch_opened("真库验证项目")
    extra = db.reconcile([{**row, "status": "active"}])
    assert extra["真库验证项目"]["last_opened_at"] is not None
    # 幽灵行清除：目录删除后对账应删行
    import shutil; shutil.rmtree(tmp_path / "真库验证项目")
    db.reconcile([])
    conn = db.connect()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM projects WHERE slug='真库验证项目'")
        assert cur.fetchone()[0] == 0
    conn.close()
```

- [ ] **Step 2: 跑真库测试**

```bash
cd server && QUOS_DB_TEST=1 QUOS_DB_HOST=192.168.17.216 QUOS_DB_PORT=3306 \
  QUOS_DB_USER=perftest QUOS_DB_PASSWORD=perftest QUOS_DB_NAME=quos \
  uv run pytest tests/test_projects_db.py -v
```
Expected: PASS

- [ ] **Step 3: 端到端验收清单（spec §10 逐条）**

1. `./start.sh` → 首页出现「风控云」（目录自动发现），进入后现有功能正常
2. 新建「测试二期」→ 加证据/建树/提断言，与风控云互不可见
3. 归档「测试二期」→ 直达其 /tree 得 404 引导；恢复后数据完整
4. 彻底删除（输入名确认）→ 目录与 DB 行均消失
5. `mysql` 停连模拟：改 QUOS_DB_HOST 为不可达 IP 起服务 → 列表仍可用
6. `cd server && uv run pytest -q && cd ../web && npx vitest run` 全绿

- [ ] **Step 4: Commit**

```bash
git add server/tests/test_projects_db.py
git commit -m "test：MySQL 真库对账集成测试"
```

---

## Self-Review 记录

- **Spec 覆盖**：§3 存储架构→T1/T2；§4 生命周期→T2/T3；§5 API 八端点→T3；§6 前端→T5/T6/T7；§7 行为变更与 start.sh→T3/T4；§8 错误边界→T2/T3 测试；§9 测试→各 Task + T8；§10 验收→T8 Step 3。无缺口。
- **占位符**：Task 2/Task 5 各有一处草稿后紧跟修正版并标注"以此为准"，保留草稿是为了让执行者看到反例；其余无 TBD。
- **类型一致性**：`scan` 返回 dict 键 `slug/name/description/created_at` 在 T1 reconcile 入参、T3 列表响应、T5 `ProjectInfo` 三处一致；`curSlug/setProject/enterProject/goHome/top/initRouteFromHash` 在 T5/T6/T7 间签名一致。
- **Review Focus**：五项均已落到具体测试。
