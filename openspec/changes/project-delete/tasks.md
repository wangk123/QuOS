# 项目删除（归档模块退役）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用「物理删除 + 弹窗二次确认」替代项目归档/恢复，归档模块（端点、`archived` 列、前端视图与按钮）整体退役。

**Architecture:** 后端 `api/projects.py` 删归档两端点、加 `DELETE /{pid}` 按外键依赖顺序显式清 9 张表后删项目目录；`db.py` 启动 schema 同步扩成补列 + 删废列，存量库零手工迁移。前端 `ProjectsView.vue` 去掉归档 tab/弹窗/按钮，加删除按钮与确认弹窗，并以自定义事件通知 `SideBar.vue` 刷新项目树。

**Tech Stack:** FastAPI / SQLModel / SQLite 3.50（`DROP COLUMN` 需 ≥3.35）；Vue 3 + TypeScript；pytest / vue-tsc。

**Spec:** `openspec/changes/project-delete/design.md`（§3 后端、§4 前端、§5 测试、§6 文档同步）；行为 delta `openspec/changes/project-delete/specs/project-management/spec.md`。

## Global Constraints

- `projects.py` 取数据目录必须 `from app import db as dbmod` 后用 `dbmod.DATA_DIR`，禁止 `from app.db import DATA_DIR`（conftest 以 `monkeypatch.setattr(dbmod, "DATA_DIR", tmp_path)` 隔离落盘，固化导入会让测试 rmtree 真实 `server/data/<pid>/`）。
- 子表删除顺序：`DocVersion` 先于 `DocDraft`（`DocVersion.draft_id` 外键）；其余 `Baseline / ChangeLog / Question / Rule / Term / Material` 互不引用；最后 `Project`。一次 commit。
- 接口增删改同一次改动同步 `docs/api.md`（根 AGENTS.md 规则 1）；CLI 与 `docs/quos-agent-api.md` 不动（归档/删除均非 agent 通道）。
- 前端不新增全局 CSS 类，复用 `icon-btn` / `btn danger` / `AppModal` / `toast`；`ProjectsView.vue` 保持 ≤500 行（现 166）。
- 不新增依赖。测试命令：`cd server && uv run pytest tests/<file> -v`；前端类型检查 `cd web && npx vue-tsc -b`。
- Git：全部任务完成后**单条 commit**（用户偏好：大任务一条记录），格式 `feat：<描述>`（中文冒号）。实施 Task 3 前先 Read `ui-ux-pro-max` skill（全局 AGENTS.md 前端规则）。

## Review Focus

1. **删子表顺序只在生产库暴露**：生产 `PRAGMA foreign_keys=ON`，conftest 引擎默认 OFF，顺序错测试照样绿。→ Task 2 的级联测试显式对测试引擎开 `PRAGMA foreign_keys=ON`。
2. **删除后侧栏残留死链接**：`SideBar.vue` 只在挂载与 hashchange 刷新，停留在总览页删除后项目树仍显示已删项目，点进去 `getProject` 404。→ Task 3 以 `window.dispatchEvent(new Event('quos:projects-changed'))` 通知侧栏刷新，真机验收覆盖。
3. **从未上传材料的项目无 `data/<pid>/` 目录**：rmtree 不得抛错。→ Task 2 `test_delete_project_without_files_ok`。
4. **存量库二次启动 `archived` 列已不存在**：迁移必须幂等。→ Task 1 `test_sync_schema_drops_archived_and_is_idempotent`。
5. **重复删除同一 pid**：第二次应 404 而非 500。→ Task 2 `test_delete_twice_second_404`。

---

### Task 1: 后端归档退役 + `archived` 列启动迁移

**Files:**
- Modify: `server/app/models.py:20-25`（`Project` 删 `archived`）
- Modify: `server/app/db.py:28-39`（`_ensure_columns` → `_sync_schema`，加 drops）、`server/app/db.py:25`（调用点改名）
- Modify: `server/app/api/projects.py:54-68, 101-116`（`_proj_out` 去 archived、`list_projects` 去参数、删 archive/restore）
- Create: `server/tests/test_db.py`
- Modify: `server/tests/test_projects.py:19-31`（删归档测试，加两条）
- Modify: `docs/api.md:14-23`（删 archive/restore 行，GET 说明去 archived）

**Interfaces:**
- Produces: `app.db._sync_schema(eng: Engine) -> None`（幂等：补 `docdraft.one_pager_md` / `docversion.one_pager_md`，删 `project.archived`）；`GET /api/v1/projects` 无 query、返回全部项目，元素无 `archived` 键。

- [ ] **Step 1: 写迁移失败测试 `server/tests/test_db.py`**

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_db.py -v`
Expected: FAIL `ImportError: cannot import name '_sync_schema'`

- [ ] **Step 3: `db.py` 实现 `_sync_schema(eng: Engine) -> None`**

把 `_ensure_columns` 改名为 `_sync_schema`，`get_engine` 调用点同步；在 `patches` 旁加 `drops = {"project": ["archived"]}`，同一 `eng.begin()` 内按 `PRAGMA table_info` 判断：缺则 `ALTER TABLE {t} ADD COLUMN {c} TEXT`，有废列则 `ALTER TABLE {t} DROP COLUMN {c}`。docstring 改为「create_all 不改既有表：启动时幂等补列、删废列（存量 quos.db 零手工迁移）」。

- [ ] **Step 4: 运行确认通过**

Run: `cd server && uv run pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 5: `test_projects.py` 删 `test_archive_hides_from_default_and_restore`，加两条**

```python
def test_list_returns_all_without_archived_field(client):
    client.post("/api/v1/projects", json={"name": "A"})
    items = client.get("/api/v1/projects").json()
    assert len(items) == 1 and "archived" not in items[0]


def test_archive_endpoints_removed(client):
    pid = client.post("/api/v1/projects", json={"name": "X"}).json()["id"]
    assert client.post(f"/api/v1/projects/{pid}/archive").status_code == 404
    assert client.post(f"/api/v1/projects/{pid}/restore").status_code == 404
```

- [ ] **Step 6: 运行确认失败**

Run: `cd server && uv run pytest tests/test_projects.py -v`
Expected: 两条新测试 FAIL（响应含 `archived`；archive 返回 200）

- [ ] **Step 7: 删模型字段与归档端点**

`models.py` `Project` 删 `archived: bool = False`。`projects.py`：`_proj_out` 删 `"archived"` 键；`list_projects(db: Session = Depends(get_session))` 改为 `select(Project)` 全量；整体删除 `archive_project`、`restore_project` 两个函数；模块 docstring 改「项目 CRUD / 删除 / 状态总览」（删除端点 Task 2 加）。

- [ ] **Step 8: 运行确认通过**

Run: `cd server && uv run pytest tests/test_projects.py tests/test_db.py -v`
Expected: 全部 PASS

- [ ] **Step 9: `docs/api.md` 同步**

projects 表删 `archive` / `restore` 两行；「GET 列表」条改为：`响应数组，元素 {id, name, description, created_at, stats}；stats = {...}（不变）`，去掉 `query archived` 说明。

### Task 2: `DELETE /api/v1/projects/{pid}` 级联删除

**Files:**
- Modify: `server/app/api/projects.py`（加 `delete_project`；import `shutil`、`from app import db as dbmod`、`ChangeLog, Rule, Term` 模型）
- Modify: `server/tests/test_projects.py`（加四条测试）
- Modify: `docs/api.md`（projects 表加 DELETE 行 + 说明）
- Modify: `docs/requirements.md:101`

**Interfaces:**
- Consumes: Task 1 的无 `archived` 模型。
- Produces: `DELETE /api/v1/projects/{pid}` → 200 `{"ok": true}` / 404 `"project not found"`；前端 Task 3 调用。

- [ ] **Step 1: 写级联删除失败测试（追加到 `test_projects.py`）**

```python
from sqlmodel import select

from app.models import Baseline, ChangeLog, DocDraft, DocVersion, Material, Question, Rule, Term

CHILD_TABLES = [Material, DocDraft, DocVersion, Baseline, ChangeLog, Question, Rule, Term]


def _enable_fk(engine):
    """生产库 foreign_keys=ON,测试引擎默认 OFF:显式开启,让删表顺序错误在测试中暴露。"""
    raw = engine.raw_connection()
    raw.cursor().execute("PRAGMA foreign_keys=ON")
    raw.close()


def _seed_tree(db, tmp_path, pid):
    draft = DocDraft(project_id=pid, payload={}, status="finalized")
    db.add(draft)
    db.commit()
    db.refresh(draft)
    mat_dir = tmp_path / str(pid) / "materials"
    mat_dir.mkdir(parents=True)
    (mat_dir / "a.md").write_text("# a")
    db.add_all([
        DocVersion(project_id=pid, version="v1", snapshot={}, draft_id=draft.id),
        Baseline(project_id=pid, version="v1"),
        ChangeLog(project_id=pid, version="v1", rule_no="R1", kind="added"),
        Question(project_id=pid, kind="confirm", payload={}, anchor={}),
        Rule(project_id=pid, no="R1", text="t"),
        Term(project_id=pid, name="术语"),
        Material(project_id=pid, filename="a.md", path=str(mat_dir / "a.md"), sha256="x"),
    ])
    db.commit()


def test_delete_project_cascades(client, db, engine, tmp_path):
    _enable_fk(engine)
    pid = client.post("/api/v1/projects", json={"name": "D"}).json()["id"]
    _seed_tree(db, tmp_path, pid)

    r = client.delete(f"/api/v1/projects/{pid}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get(f"/api/v1/projects/{pid}").status_code == 404
    for T in CHILD_TABLES:
        assert db.exec(select(T).where(T.project_id == pid)).all() == []
    assert not (tmp_path / str(pid)).exists()


def test_delete_project_without_files_ok(client, tmp_path):
    pid = client.post("/api/v1/projects", json={"name": "空"}).json()["id"]
    assert not (tmp_path / str(pid)).exists()
    assert client.delete(f"/api/v1/projects/{pid}").status_code == 200


def test_delete_twice_second_404(client):
    pid = client.post("/api/v1/projects", json={"name": "T"}).json()["id"]
    assert client.delete(f"/api/v1/projects/{pid}").status_code == 200
    assert client.delete(f"/api/v1/projects/{pid}").status_code == 404


def test_delete_missing_project_404(client):
    assert client.delete("/api/v1/projects/9999").status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_projects.py -v -k delete`
Expected: 四条 FAIL，状态码 405（路由不存在）

- [ ] **Step 3: 实现 `delete_project(pid: int, db: Session = Depends(get_session)) -> dict`**

`@router.delete("/{pid}")`。`_get_or_404` 取项目；按 Global Constraints 顺序对 8 张子表各执行 `db.execute(delete(T).where(T.project_id == pid))`（`from sqlalchemy import delete`），再 `db.delete(proj)`，一次 `db.commit()`；commit 后 `shutil.rmtree(dbmod.DATA_DIR / str(pid), ignore_errors=True)`；返回 `{"ok": True}`。import 行：`from app import db as dbmod`（与现有 `from app.db import get_session` 并存）。

- [ ] **Step 4: 运行确认通过，并验证 FK 测试真能抓顺序错误**

Run: `cd server && uv run pytest tests/test_projects.py -v`
Expected: 全部 PASS。随后临时把 `DocDraft` 的删除挪到 `DocVersion` 之前再跑 `-k cascades`，Expected: FAIL `IntegrityError: FOREIGN KEY constraint failed`；恢复顺序后再跑一次 PASS。

- [ ] **Step 5: 全量 server 测试（模型为公共底层改动，影响范围不可定位）**

Run: `cd server && uv run pytest -q`
Expected: 全部 PASS（基线 98 条，减 1 归档 + 加 7 条）

- [ ] **Step 6: 文档同步**

`docs/api.md` projects 表加行 `| DELETE | /api/v1/projects/{pid} | 删除项目（物理删除，不可逆） |`，说明条加：`- **DELETE**：连带清除该项目全部材料 / 草案 / 版本 / 基线 / 变更记录 / 批注 / 规则 / 术语与磁盘目录 data/<pid>/；成功 {"ok": true}。`
`docs/requirements.md:101` 句改为：`项目生命周期：创建（名称必填）、改名、描述编辑、删除（弹窗二次确认；物理清除全部从属数据与文件，不可恢复）。项目列表每行可见：……（后半不变）`。

### Task 3: 前端——删归档 UI、加删除按钮与确认弹窗、侧栏同步

**Files:**
- Modify: `web/src/api.ts:44-50`
- Modify: `web/src/views/ProjectsView.vue`（全文重整）
- Modify: `web/src/components/SideBar.vue:1, 12-14`

**Interfaces:**
- Consumes: Task 2 的 `DELETE /projects/{pid}`。
- Produces: `deleteProject(pid: number): Promise<{ok: boolean}>`；全局事件 `quos:projects-changed`（`ProjectsView` 增删改后派发，`SideBar` 监听刷新）。

- [ ] **Step 0: Read `/Users/wangk/.agents/skills/ui-ux-pro-max/SKILL.md` 全文并遵循**

- [ ] **Step 1: `api.ts` 改项目段**

`Project` 接口删 `archived: boolean`；`listProjects = () => api.get('/projects') as Promise<Project[]>`；删 `archiveProject`、`restoreProject`；加 `export const deleteProject = (pid: number) => api.del(`/projects/${pid}`)`。

- [ ] **Step 2: `ProjectsView.vue` 重整**

删除：`tab` 与 `switchTab`、seg 切换条、`archiving / archName / archErr`、`askArchive / doArchive / doRestore`、归档 `icon-btn`、恢复 `btn sm`、归档 `AppModal`、所有 `v-if="!p.archived"`；空状态只留「尚无项目,点击右上角新建」；`refresh()` 改为无参 `listProjects()`。
新增：`const deleting = ref<Project | null>(null)`；行末删除 `icon-btn`（`title="删除"`，垃圾桶 SVG：`<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>`）；`AppModal v-if="deleting" title="删除项目"`，正文 `<p>删除「<b>{{ deleting.name }}</b>」？项目下全部材料、文档、版本、批注将永久删除，不可恢复。</p>`，`#foot`：`btn` 取消 + `btn danger` 删除；`async function doDelete()`：`await deleteProject(deleting.value!.id)` → `toast(`「${name}」已删除`)` → `deleting.value = null` → `refresh()`。
`refresh()` 末尾加 `window.dispatchEvent(new Event('quos:projects-changed'))`（创建/改名/删除后侧栏同步）。头注释改「项目总览:表格/新建/编辑/删除」。

- [ ] **Step 3: `SideBar.vue` 监听事件、改陈旧注释**

`window.addEventListener('hashchange', ...)` 下一行加 `window.addEventListener('quos:projects-changed', () => refresh())`；头注释改「侧栏:项目树 + 项目内子导航(材料/文档评审/版本)」。

- [ ] **Step 4: 类型检查**

Run: `cd web && npx vue-tsc -b`
Expected: 无输出（0 错误）；若报 `archived` 残留引用则按报错清除

- [ ] **Step 5: 真机验收（强刷）**

启动：`./start.sh`（或按 docs/development.md 分别起 8000 / 5175）。浏览器打开项目总览，依次确认：① 列表无「进行中/归档」切换条，原归档项目 id 1、2 回到列表；② 每行有编辑、删除两个图标，无归档图标；③ 点删除弹窗显示项目名与不可逆警告，取消不删；④ 新建临时项目 → 删除 → toast「已删除」→ 列表与左侧项目树同时消失；⑤ 浏览器 Network 面板 `DELETE /api/v1/projects/<pid>` 200；⑥ 服务端 `server/data/<pid>/` 目录不存在（若曾上传材料）。

### Task 4: 收尾

- [ ] **Step 1: 全量验证**

Run: `cd server && uv run pytest -q && cd ../web && npx vitest run && npx vue-tsc -b`
Expected: server 全绿、web 24 条全绿、tsc 0 错

- [ ] **Step 2: 单条 commit**

```bash
git add server/app/models.py server/app/db.py server/app/api/projects.py server/tests/test_db.py server/tests/test_projects.py web/src/api.ts web/src/views/ProjectsView.vue web/src/components/SideBar.vue docs/api.md docs/requirements.md openspec/changes/project-delete
git commit -m "feat：项目删除替代归档——DELETE /projects/{pid} 级联清 9 表+项目目录，归档端点/archived 列/归档视图退役（启动幂等 DROP COLUMN），前端删除按钮+二次确认弹窗+侧栏同步刷新"
```

- [ ] **Step 3: 未归档 change 提醒（不执行归档）**

输出一行：`未归档 change：diagram-design-integration、project-delete`。
