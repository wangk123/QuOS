# Design: 项目删除（归档模块退役）

## 1. 已拍板（2026-10-20）

- 归档模块整体退役（端点、字段、视图、按钮），项目列表始终展示全部项目。
- 删除随时可用，不设前置条件。
- 二次确认 = 普通确认弹窗（显示项目名 + 不可逆警告），不要求输入项目名。

## 2. 已定（我的决定）

- **硬删不软删**。
- **先库后文件**。同一事务删完 9 张表再 commit；commit 成功后再删 `data/<pid>/` 目录，目录删不掉不回滚（库是唯一真相源，孤儿文件可清理，悬空记录不行）。与现有 `delete_material` 一致。
- **`archived` 列真删不留死字段**。SQLite 3.50.4 支持 `ALTER TABLE ... DROP COLUMN`；该列无索引无外键，可直接删。不删会怎样：模型去掉字段后 INSERT 不写该列，而存量列是 `NOT NULL` 无默认值，建项目直接炸。
- **不进 CLI**。`docs/quos-agent-api.md` 不涉及 archived，不动。

## 3. 后端

### `models.py`

`Project` 删 `archived: bool = False`。

### `db.py` 启动迁移

`_ensure_columns` 现在只补列（`one_pager_md`）。扩成补列 + 删废列，同一处幂等执行：

```
patches = {"docdraft": ["one_pager_md"], "docversion": ["one_pager_md"]}
drops = {"project": ["archived"]}
```

按 `PRAGMA table_info` 判断：缺则 `ADD COLUMN`，有废列则 `DROP COLUMN`。函数改名 `_sync_schema`（调用点仅 `get_engine` 一处），docstring 同步。

### `api/projects.py`

- 删 `archive_project`、`restore_project`。
- `list_projects` 去 `archived` 参数，`select(Project)` 全量。
- `_proj_out` 去 `"archived"`。
- 加：

`DELETE /api/v1/projects/{pid}` → 200 `{"ok": true}`；404 `"project not found"`。

清理顺序（生产库 `PRAGMA foreign_keys=ON`，模型外键无 CASCADE，顺序错即 IntegrityError）：

1. `DocVersion`（`draft_id` 指向 DocDraft，必须先于 DocDraft）
2. `DocDraft`、`Baseline`、`ChangeLog`、`Question`、`Rule`、`Term`、`Material`（互不引用）
3. `Project`

全部 `where project_id == pid` 批量 delete，一次 commit，再 `shutil.rmtree(DATA_DIR / str(pid), ignore_errors=True)`（材料固定落 `DATA_DIR/<pid>/materials`，图源在 payload 不落盘）。

**实施红线**：`projects.py` 必须 `from app import db as dbmod` 后取 `dbmod.DATA_DIR`，不能 `from app.db import DATA_DIR`。conftest 用 `monkeypatch.setattr(dbmod, "DATA_DIR", tmp_path)` 隔离落盘，`from ... import` 会固化真实路径，测试跑 rmtree 就会删真实 `server/data/1/`。

（顺带发现的既有隐患，不在本 change 处理：`materials.py` 就是 `from app.db import DATA_DIR`，材料测试一直在写真实 `server/data/<pid>/materials/`。）

## 4. 前端

### `api.ts`

- `Project` 接口去 `archived`。
- `listProjects` 去参数（`SideBar.vue` 已是无参调用，兼容）。
- 删 `archiveProject`、`restoreProject`；加 `deleteProject = (pid) => api.del(`/projects/${pid}`)`。

### `ProjectsView.vue`

- 删：`tab` 状态与 seg 切换条、`archiving/archName/archErr` 状态、`askArchive/doArchive/doRestore`、归档按钮、恢复按钮、归档弹窗、各处 `v-if="!p.archived"`；空状态只留「尚无项目,点击右上角新建」。
- 加：`deleting = ref<Project | null>(null)`；行末删除 `icon-btn`（垃圾桶）；`AppModal`「删除项目」，正文「删除「X」？项目下全部材料、文档、版本、批注将永久删除，不可恢复。」，底部「取消」+ `btn danger`「删除」；成功 toast「「X」已删除」并刷新。
- 头注释改为「项目总览:表格/新建/编辑/删除」。不新增全局 CSS 类。

### `SideBar.vue`

侧栏项目树只在挂载与 hashchange 时刷新,停留在总览页删除后会残留已删项目的死链接(点进去 404)。`ProjectsView` 的 `refresh()` 末尾派发 `window.dispatchEvent(new Event('quos:projects-changed'))`,`SideBar` 监听该事件刷新(创建 / 改名同样受益)。头注释「+ 归档区」陈旧,一并删掉。

## 5. 测试

- `test_projects.py`：删 `test_archive_hides_from_default_and_restore`；加 `test_delete_project_cascades`（建项目 → 造从属数据：至少 Material 一条 + DocDraft + DocVersion（draft_id 指向该草案）+ Baseline + Question + Rule + Term + ChangeLog，并在 `tmp_path/<pid>/materials/` 落一个文件 → DELETE 200 → GET 404 → 9 张表该 pid 计数全 0 → 目录不存在）；加 `test_delete_missing_project_404`。
- 新 `test_db.py`：文件库建含 `archived BOOLEAN NOT NULL` 的旧 `project` 表 → 调 `_sync_schema(eng)` → `PRAGMA table_info` 无 archived；再调一次不报错（幂等）。
- 前端沿项目惯例不加组件测试，真机渲染验收（强刷）。

## 6. 文档同步（同一次改动）

- `docs/api.md` projects 表删 archive / restore 两行、加 DELETE 行；GET 列表说明去 `archived` query 与字段。
- `docs/requirements.md` §4.1「项目生命周期」句改为「创建（名称必填）、改名、描述编辑、删除（弹窗二次确认；物理清除全部从属数据与文件，不可恢复）」。
- spec delta 见 `specs/project-management/spec.md`。
