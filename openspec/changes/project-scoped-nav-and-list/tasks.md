# 项目资源导航、列表优化与状态两轴 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 侧栏改为项目内资源导航、项目列表展示项目级版本与状态（治理三态），需求状态五态由平台派生仅在项目内露出，配套名称唯一与 x.x.x 版本号硬校验。

**Architecture:** 后端单点派生（services 层纯查询函数 + stats 透出）、写守卫统一拦截只读项目、SQLite 幂等补列零手工迁移；前端仅动导航骨架与项目列表页，子页布局不动（两处徽标文案级升级）。

**Tech Stack:** FastAPI / SQLModel / SQLite；Vue3 + Vite（无新依赖）。

**Spec:** `openspec/changes/project-scoped-nav-and-list/design.md` 及 `specs/` delta（web-workbench / project-management / doc-versioning）。

## Global Constraints

- 需求管理三个子页（材料/评审/版本）布局与交互不动；仅评审页工具条徽标与版本页草案条目徽标两处文案升级。
- 错误码：409 DUP_NAME / 409 PROJECT_READ_ONLY / 409 INVALID_STATUS_TRANSITION / 422 VERSION_FORMAT（detail JSON 带 code）。
- 版本号格式 `^\d+\.\d+\.\d+$`（无 v 前缀），项目版本与定稿版本共用同一正则；存量版本号不迁移。
- 存量 quos.db 零手工迁移：db.py 启动幂等补列；唯一索引创建失败（存量重名）记 warning 跳过不阻塞。
- 接口增删改同批同步 `docs/api.md`；CLI 命令不变（`projects` 仅列表）；`.agents/skills/req-organize/SKILL.md` 补只读拦截提示一句。
- 行数上限：前端组件/后端模块 500 行，工具 300 行；中文注释；测试定向（`python3 -m pytest tests/<file> -v`，server/ 目录下执行）。

## Review Focus

1. **只读态漏拦写端点**（answer、materials delete、questions 批量提交最易漏）→ Task 3 矩阵测试逐一打。
2. **状态转移绕过**（closed→paused 直接 PATCH）→ Task 4 转移表测试。
3. **重名变体**（前后空白、重复 trim 后同名）→ Task 4 trim 精确匹配测试。
4. **派生误计**：superseded 草案的 answered 批注把状态误判「待重交」→ Task 2 用 draft_id=D.id 口径测试钉死。
5. **v 前缀漏拦**（`v1.2.0` 定稿）→ Task 5 格式测试。

---

### Task 1: Project 模型加 status/version + 幂等迁移

**Files:**
- Modify: `server/app/models.py:20-24`（Project）
- Modify: `server/app/db.py:29-46`（_sync_schema + 唯一索引）
- Test: `server/tests/test_db.py`

**Interfaces:**
- Produces: `Project.status: str = "in_progress"`（枚举 `in_progress|paused|closed`）、`Project.version: str = "1.0.0"`；启动后存量库自动补列并尽力建 `ix_projects_name` 唯一索引。

- [ ] **Step 1: 写失败测试**（test_db.py 补）：建库后断言 `PRAGMA table_info(project)` 含 `status`/`version` 两列；`PRAGMA index_list(project)` 含 `ix_projects_name`；重名两行插入触发 IntegrityError（新库场景）。

- [ ] **Step 2: 跑测试确认失败**：`python3 -m pytest tests/test_db.py -v`

- [ ] **Step 3: 实现**：models.py Project 加两字段（中文注释：治理开关/项目自有版本）；db.py `_sync_schema` 的 `patches` 加 `{"project": ["status", "version"]}`，同一 `eng.begin()` 内 `CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_name ON projects(name)`，包 try/except IntegrityError → print warning 跳过。

- [ ] **Step 4: 跑测试通过**（同命令）。

- [ ] **Step 5: Commit**：`feat：Project 增 status/version 字段与幂等迁移+名称唯一索引`

### Task 2: 需求状态派生服务

**Files:**
- Create: `server/app/services/doc_state.py`
- Modify: `server/app/api/projects.py`（_stats 与 _proj_out）
- Test: `server/tests/test_projects.py`

**Interfaces:**
- Produces: `derive_requirement_status(db: Session, pid: int) -> str`，返回 `"idle" | "in_review" | "await_resubmit" | "await_finalize" | "finalized"`；`_proj_out` 顶层增 `status`/`version`，`stats` 增 `requirement_status`。中文标签映射放前端（api.ts）。

- [ ] **Step 1: 写失败测试**（五态各一条 + 覆盖口径）：无草案无基线→idle；有 reviewing 草案+pending>0→in_review；pending=0 且 `Question.draft_id==D.id` 的 answered>0→await_resubmit；pending=0 且无 D 的 answered→await_finalize；superseded 旧草案残留 answered 而新草案 pending=0 无新答→await_finalize（钉死 draft_id 口径）；无草案有基线→finalized。

- [ ] **Step 2: 确认失败**：`python3 -m pytest tests/test_projects.py -v`

- [ ] **Step 3: 实现** `derive_requirement_status`：取 reviewing 草案 D（`DocDraft.status=="reviewing"`，理论上唯一，取 first）；无 D → 有 Baseline.version 则 finalized 否则 idle；有 D → `pending = count(Question where project_id, status=="pending", draft_id==D.id)`、`fresh_answered = count(... status=="answered", draft_id==D.id)`，按表派生。`_stats` 调用之。

- [ ] **Step 4: 跑测试通过**。

- [ ] **Step 5: Commit**：`feat：需求状态五态派生服务与 stats.requirement_status 透出`

### Task 3: 只读写守卫铺满写端点

**Files:**
- Modify: `server/app/api/projects.py`（定义守卫）
- Modify: `server/app/api/materials.py:27,61`、`server/app/api/doc.py:82,170,274,286`、`server/app/api/questions.py:65,95`
- Test: `server/tests/test_projects.py`（或新建 `test_readonly_guard.py`）

**Interfaces:**
- Produces: `assert_writable(db: Session, pid: int) -> None`（项目不存在 404；status != "in_progress" 时 `HTTPException(409, {"code": "PROJECT_READ_ONLY", "status": <status>})`）。位置：projects.py 顶层函数（无循环依赖）。

- [ ] **Step 1: 写失败测试**：暂停项目对 8 个写端点（材料上传/删除、doc/draft、doc/draft/import、questions 批量提交、questions/{qid}/answer、finalize、revert）逐个请求断言 409 code=PROJECT_READ_ONLY；进行中项目放行（抽 2 个端点）；读端点（GET draft/baseline）不拦；questions/{qid}/answer 需经批注反查 pid 再守卫。

- [ ] **Step 2: 确认失败**。

- [ ] **Step 3: 实现**：projects.py 定义 `assert_writable`；七个写端点在业务逻辑前调用（answer 端点先 `db.get(Question, qid)` 反查 project_id 再守卫；批注作答属写操作，只读态拦）。

- [ ] **Step 4: 跑测试通过**。

- [ ] **Step 5: Commit**：`feat：项目只读态统一写守卫,七写端点全拦`

### Task 4: 名称唯一 + PATCH 扩展（status/version）

**Files:**
- Modify: `server/app/api/projects.py`
- Test: `server/tests/test_projects.py`

**Interfaces:**
- Consumes: Task 1 字段、Task 3 `assert_writable`。
- Produces: `ProjectPatch` 增 `version: str | None`、`status: str | None`；`TRANSITIONS = {"in_progress": {"paused", "closed"}, "paused": {"in_progress", "closed"}, "closed": {"in_progress"}}`；409 DUP_NAME / 422 VERSION_FORMAT / 409 INVALID_STATUS_TRANSITION。

- [ ] **Step 1: 写失败测试**：创建重名（trim 后精确匹配，含 `' 多模态 '` 变体）→409 DUP_NAME；PATCH 改名撞他人→409、不改自身名→200；PATCH version `1.2`/`v1.2.0`→422、`1.2.3`→200；PATCH status 非法值→422、closed→paused→409 INVALID_STATUS_TRANSITION、paused→in_progress→200；暂停项目 PATCH 仅 status→200（治理不拦），PATCH name→409 PROJECT_READ_ONLY。

- [ ] **Step 2: 确认失败**。

- [ ] **Step 3: 实现**：POST/PATCH 查重（`select(Project).where(Project.name == name.strip())`，PATCH 排除自身）；PATCH 分两段：name/description/version 变更前 `assert_writable`，status 字段独立校验（枚举 422 + 转移表 409）后赋值；`VERSION_RE` 从 Task 5 前置——本任务先在 `services/validators.py` 定义 `VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")` 并导入使用。

- [ ] **Step 4: 跑测试通过**。

- [ ] **Step 5: Commit**：`feat：项目名唯一+PATCH 扩展 status/version(转移表与格式校验)`

### Task 5: finalize 版本号 x.x.x 硬校验

**Files:**
- Modify: `server/app/services/snapshots.py:87-100`（finalize）
- Test: `server/tests/test_finalize.py`

**Interfaces:**
- Consumes: `services/validators.py` 的 `VERSION_RE`。
- Produces: finalize 对 version 先格式校验：不匹配 → `HTTPException(422, {"code": "VERSION_FORMAT"})`；建议值逻辑在前端，后端不管。

- [ ] **Step 1: 写失败测试**：`v3`、`1.2`、`1.2.3.4` → 422 VERSION_FORMAT 不发版；`1.2.3` → 正常发版；存量库已有 `v2-onepager` 历史版本回退照旧（回归）。

- [ ] **Step 2: 确认失败**。

- [ ] **Step 3: 实现**：finalize 内 strip 后置于重复检查之前加格式校验。

- [ ] **Step 4: 跑测试通过**（含既有 finalize 用例回归）。

- [ ] **Step 5: Commit**：`feat：定稿版本号 x.x.x 硬校验(422 VERSION_FORMAT)`

### Task 6: 前端——导航骨架（列表态无侧栏 + 项目内资源导航）

**Files:**
- Modify: `web/src/App.vue`、`web/src/components/SideBar.vue`、`web/src/style.css`、`web/src/api.ts`（Project 类型补 status/version/stats.requirement_status）

**Interfaces:**
- Produces: `SideBar` 组件导出 `MODULES` 常量（key/label/live/subs），列表态由 App.vue `v-if="route.view !== 'projects'"` 控制；style.css 追加 `.item.soon`、`.soon-tag`、`.proj-head`、`.topbar .brand`。

- [ ] **Step 1: 实现**：App.vue 侧栏条件渲染 + 列表态 `.app` 加 `no-side` 类（style.css 定义单列）+ 列表态面包屑「品牌 mark + QuOS / 项目总览」；SideBar.vue 重写：返回入口、`proj-head` 项目名、需求管理组（材料蓝徽标/文档评审红徽标/版本）、六个 planned 模块 disabled 按钮（`aria-disabled`，右缘虚线「即将上线」小标）；徽标刷新事件保留。

- [ ] **Step 2: 验证**：`cd web && npx vite build` 零报错；dev 真机走查——列表态全宽无侧栏、进入项目侧栏结构正确、占位项不可点、返回正常、刷新徽标正常。

- [ ] **Step 3: Commit**：`feat：侧栏改项目内资源导航,列表态无侧栏全宽`

### Task 7: 前端——项目列表页

**Files:**
- Modify: `web/src/views/ProjectsView.vue`

**Interfaces:**
- Consumes: Task 4 的 PATCH 语义（409 DUP_NAME / 422 VERSION_FORMAT）、`TRANSITIONS` 同表在前端镜像为下拉可选项计算。
- Produces: 列=项目/材料/批注/项目版本/项目状态/操作；状态 tag 色：in_progress=ok、paused=warn、closed=mute。

- [ ] **Step 1: 实现**：表头与状态列（需求版本/状态不再出现）；操作栏三个 `.btn.sm`（进入 primary/编辑/删除 danger）；新建/编辑弹窗加版本输入（placeholder「如 1.2.0」，本地正则校验内联错）与状态下拉（选项=当前状态+TRANSITIONS 可达态，文案「进行中(写权限全开)/已暂停(只读·可恢复)/已结项(只读·可重开)」）；保存捕 409 DUP_NAME→名称字段内联「项目名称已存在」，409 READ_ONLY→toast。

- [ ] **Step 2: 验证**：build 零报错；真机走查——重名拦截、版本格式拦、状态切换后列表 tag 变色、暂停项目写操作 toast 拒收、删除确认不变。

- [ ] **Step 3: Commit**：`feat：项目列表页——项目版本/状态列,操作栏统一,弹窗含状态与版本`

### Task 8: 前端——定稿弹窗与两处徽标文案

**Files:**
- Modify: `web/src/views/ReviewView.vue`（仅定稿弹窗输入与工具条徽标文案）、`web/src/views/VersionsView.vue`（仅草案条目徽标文案）

**Interfaces:**
- Consumes: `stats.requirement_status`（Task 2）；标签映射 `idle:未开始 / in_review:待评审 / await_resubmit:待重交 / await_finalize:待定稿 / finalized:已定稿`。

- [ ] **Step 1: 实现**：定稿弹窗 placeholder「如 1.2.0」、建议值=基线命中 `^\d+\.\d+\.\d+$` 则 patch+1 否则 `1.0.0`、本地格式校验内联错；评审页工具条徽标文案换成需求状态标签（布局不动）；版本页草案条目「评审中」同步换。两页其余代码不动。

- [ ] **Step 2: 验证**：build 零报错；真机走查——建议值正确（含存量旧基线项目给 1.0.0）、`v3` 提交被内联拦、答完批注徽标转「待重交」。

- [ ] **Step 3: Commit**：`feat：定稿弹窗 x.x.x 建议与校验,评审/版本页徽标文案升级五态`

### Task 9: 文档同步（AGENTS.md 义务）

**Files:**
- Modify: `docs/api.md`、`docs/quos-agent-api.md`、`.agents/skills/req-organize/SKILL.md`（「配套对接」节一句）

- [ ] **Step 1: 更新**：api.md——POST/PATCH projects 字段与 409/422 错误码、stats.requirement_status、finalize VERSION_FORMAT、只读拦截端点清单（用 `app.routes` openapi() 提取核对）；quos-agent-api.md——错误码说明一句（命令表不变）；req-organize SKILL.md——只读项目提交被 409 拒收的提示。

- [ ] **Step 2: 验证**：api.md 条目与路由一一对照无漏。

- [ ] **Step 3: Commit**：`docs：接口文档与 CLI/skill 对接指引同步状态两轴与校验错误码`

### Task 10: 收尾——回归、真机验收、合并

- [ ] **Step 1: 定向回归**：`python3 -m pytest tests/test_projects.py tests/test_db.py tests/test_finalize.py tests/test_doc_api.py tests/test_materials.py tests/test_questions.py tests/test_cli.py -v`；`cd web && npx vitest run` + `npx vite build`。
- [ ] **Step 2: 真机验收**：8000/5175 全流程走查（列表→进入→暂停→写操作拒→恢复→作答→待重交→定稿 1.2.x→已定稿→列表状态列）；验收后 dev server 保持常驻。
- [ ] **Step 3: 删除交互原型** `web/prototype/nav-ia-r1.html`（交付后退役，先例：quos-v2-prototype）。
- [ ] **Step 4: squash 合并 main**：`git checkout main && git merge --squash proto/nav-ia-r1 && git commit`（含 change 目录全部文档）。
