# 项目管理（project-mgmt）设计 spec

> 2026-09-24 brainstorming 定稿。前置讨论：项目生命周期两级（归档/彻底删除）、前端形态（项目首页 + 工作台）、存储架构（文件为源 + MySQL 索引）均已确认。

## 1. 背景与目标

现状：数据已按 `server/data/<slug>/` 目录隔离，但无项目管理面——前端 `PROJ='风控云'` 硬编码（`web/src/api.ts`），后端 `project_root()` 访问即建目录，无列表/创建/归档端点。

目标：

1. 多项目使用：项目首页（列表/新建/归档/彻底删除）→ 进入项目工作台
2. 引入 MySQL 作为元数据索引，为后续模块（defect 聚合、casegen 覆盖率、观测记录）的 SQL 查询需求铺路
3. 既有项目「风控云」零迁移自动出现在列表

成功标准：

- 「风控云」无任何配置出现在列表并可进入，现有 reqspec 功能回归通过
- 新建第二个项目走完整六步流程，两项目数据互不可见
- 归档后工作台不可达（404 引导回首页），恢复后数据完整
- MySQL 停止时平台核心流程仍可用，恢复后对账无损

## 2. 非目标（本次排除）

项目重命名（需目录迁移）、跨项目树复制、跨项目基线对比、多人/权限、项目导出。

## 3. 存储架构：文件为源 + MySQL 索引

**身份与状态的真相源是文件系统**：

- 项目身份 = `data/<slug>/` 目录名
- 归档状态 = 目录移入 `data/.archived/<slug>/`（文件系统视角可见，无需打开平台）
- 静态元信息 = `data/<slug>/project.json`（`name` / `description` / `created_at`）；缺失时目录名兜底——手工创建的目录自动成为项目

**MySQL 只做索引（可重建，不存资产）**：

```sql
CREATE TABLE IF NOT EXISTS projects (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  slug          VARCHAR(191) NOT NULL UNIQUE,
  name          VARCHAR(191) NOT NULL,
  description   TEXT,
  status        ENUM('active','archived') NOT NULL DEFAULT 'active',
  created_at    DATETIME NOT NULL,
  last_opened_at DATETIME NULL,
  archived_at   DATETIME NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

分层规则：

- **静态列**（name/description/created_at）：源是 `project.json`，DB 是冗余副本
- **动态列**（last_opened_at/status/archived_at）：只存 DB，丢了无害（重开一次/重新对账即恢复）
- 任何文件内容（材料/md/git 仓库）不入 DB

**对账与 rebuild**：

- 启动时及 `GET /api/projects` 时对账：目录存在无行 → 从 `project.json`/目录名补行；行存在无目录 → 删行
- DB 整体丢失 → rebuild（全量扫描 `data/` 与 `data/.archived/` 重建），零资产损失

**降级**：DB 不可达时列表走目录扫描（仅静态信息、无最近排序），`open` 的 touch 与状态更新静默跳过并日志警告。核心流程不因索引库故障受阻。

连接配置 `QUOS_DB_HOST/PORT/USER/PASSWORD/NAME`（环境变量，见 `docs/environments.md`）。

## 4. 生命周期

| 操作 | 语义 |
|---|---|
| 创建 | 名称清洗后非空；slug 在**活跃 + 归档**中判重 → 409；建目录 + `project.json` + DB 行 |
| 打开 | `POST /open` → DB 更新 `last_opened_at`（DB 挂则跳过） |
| 归档 | 目录移入 `.archived/` + DB `status='archived'`；工作台内旧 URL → 404 引导回首页 |
| 恢复 | 移回 `data/` + `status='active'`；若活跃侧同名已存在 → 409（先处理冲突） |
| 彻底删除 | **仅归档态**可用；UI 输入项目名确认；`rm -rf` 整目录（含 git 基线历史）+ 删 DB 行 |

## 5. API

新增 `projects_router`（无 `{proj}` 前缀，`main.py` 挂载 `/api/projects`；与现有 `/api/projects/{proj}/*` 路由并存，具体路径优先匹配）：

| 方法与路径 | 行为 |
|---|---|
| `GET /api/projects` | 活跃列表（按 `last_opened_at` 排序；DB 降级时按目录 mtime） |
| `GET /api/projects/archived` | 归档列表 |
| `POST /api/projects` | 创建，`{name, description?}` → 201；重名 409 |
| `POST /api/projects/{slug}/open` | 记录打开时间 → 204 |
| `PATCH /api/projects/{slug}` | 改描述（写 `project.json` + DB）→ 200 |
| `POST /api/projects/{slug}/archive` | 归档 → 204；不存在（活跃侧）404 |
| `POST /api/projects/{slug}/restore` | 恢复 → 204；同名冲突 409 |
| `DELETE /api/projects/{slug}` | 彻底删除 → 204；非归档态 409 |

slug 含中文，走 URL encode；FastAPI path param 原样接收。

## 6. 前端

- **新视图 ProjectsHome**：项目卡片列表（名称/描述/最近打开）+ 新建弹层（名称必填、描述可选）+ 折叠的已归档区（恢复/彻底删除，删除需输入项目名）+ 空列表引导；独立布局，不套工作台导航
- **router.ts**：顶层两级——项目首页（无项目段）与 `#/p/<slug>/...`（现有视图流挂入项目段）；刷新/直链保持上下文
- **api.ts**：模块常量 `BASE` → 按当前 slug 函数化；移除硬编码 `PROJ`
- **App.vue**：顶栏当前项目名 + 「⟵ 项目」返回入口；现有六个视图（证据/树/事实/卡片/问人/基线）零改动，仍从项目上下文取 BASE

## 7. 行为变更（一处，需知晓）

`project_root()` 不再访问即建目录：改为 `require_project()`，项目不存在或已归档 → 404（前端引导回首页）。消除「拼错 URL 凭空生成空项目」的现状；创建只经 `POST /api/projects`。

`start.sh`：依赖检查增加 MySQL 可达性探测（不可达打警告不阻断——文件为源仍可用），提示 `QUOS_DB_*` 配置。

## 8. 错误与边界

- 同名创建（与活跃或归档重名）→ 409
- 打开不存在/已归档项目的任何子资源 → 404 + 前端引导回首页
- 非归档态彻底删除 → 409
- DB 不可达 → 目录扫描兜底，写侧跳过并警告
- slug 非法字符（斜杠等）→ `slugify` 清洗（沿用现有实现）
- `.archived` 内无 `project.json` 的手工目录 → 目录名兜底
- 单人使用，不考虑并发

## 9. 测试

- 后端 pytest：目录发现（含无 `project.json` 的手工目录）、创建判重（活跃+归档两侧）、归档/恢复的目录移动与同名冲突、删除仅限归档态、`require_project` 404、DB 不可达降级（monkeypatch 连接失败）
- DB 集成测试连真库 `quos`（建库后）；无库环境自动 skip
- 前端 vitest：首页三态渲染（列表/归档区/空态）、新建交互、路由项目段往返保持

## 10. 验收清单

1. 「风控云」出现在列表，进入后现有功能与测试全通过
2. 新建项目 → 六步流程完整走通，与「风控云」数据隔离
3. 归档 → 工作台 URL 404 引导；恢复 → 数据完整、重新出现在列表
4. 彻底删除归档项目 → 目录与 DB 行均消失，输入名称确认生效
5. 停 MySQL → 列表仍可用；恢复 → 对账补齐，无幽灵行/幽灵目录
