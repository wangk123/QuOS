# 设计：项目资源导航、列表优化与状态两轴

设计基准：①交互原型 `web/prototype/nav-ia-r1.html`（R3：侧栏仅项目内、列表列结构、重名与版本号校验交互）；②状态设计 v1（2026-10-21 用户定稿，DeepSeek 稿）：**项目状态=能不能写（人手动设的治理开关），需求状态=等谁（平台按事实派生），两轴正交互不改写**。

**范围铁律（用户拍板）**：需求管理三个子页（材料/文档评审/版本）为已评审产物，**布局与交互不动**；仅两处文案级例外（见 §5 需求状态露出）。

## 1. 侧栏：仅项目内呈现（SideBar.vue + App.vue）

- **路由不变**：`#/projects` 与 `#/p/:pid/{materials,review,versions}` 保持；进入项目仍落文档评审页。
- **平台级（项目列表态）无侧栏**：`SideBar` 在列表态不渲染（`v-if`），`.app` 网格切单列全宽；顶栏左侧显示 QuOS 品牌标记 + 「项目总览」。
- **项目内态**侧栏：①「返回项目列表」；②当前项目名；③模块导航（配置驱动 `MODULES`）：`需求管理`（live：材料/文档评审/版本，带数量徽标）+ 六个 planned 模块（案例管理/接口自动化/UI 自动化/性能测试/安全测试/环境管理，灰色禁用+「即将上线」小标，`aria-disabled`）。
- 徽标刷新逻辑保留（`hashchange` + `quos:projects-changed`）。

## 2. 项目状态（治理开关，人手动设）

**取值与语义**：

| 状态 | 值 | 写权限 | 可达转移（操作） |
|---|---|---|---|
| 进行中 | `in_progress`（默认） | 全开 | →已暂停（暂停）/ →已结项（结项） |
| 已暂停 | `paused` | 只读，可恢复 | →进行中（恢复）/ →已结项（结项） |
| 已结项 | `closed` | 只读，可重开 | →进行中（重新开启） |

**写权限拦截矩阵**（server 统一守卫 `_assert_writable(db, pid)`，只读态返回 `409 {"code":"PROJECT_READ_ONLY","status":...}`）：

- 拦截：材料上传/删除、草案提交（POST doc/draft）、md 导入（import）、批注作答（answer）、定稿（finalize）、回退（revert）、项目编辑中名称/描述/版本字段修改。
- 不拦（治理动作本身）：项目状态切换、项目删除（有二次确认）、一切读操作。

**API**：`PATCH /api/v1/projects/{pid}` 扩展 `status` 字段（三值枚举校验 422；非法转移 409 `INVALID_STATUS_TRANSITION`）；前端编辑弹窗提供状态下拉（含转移语义文案），列表状态列 tag：进行中=ok 绿 / 已暂停=warn 琥珀 / 已结项=mute 灰。

## 3. 需求状态（等谁，平台派生）

**派生口径**（后端单点实现，`stats.requirement_status` 返回；CLI/前端同口径消费）。设 D=当前唯一 reviewing 草案：

| 状态 | 判定（平台事实） | 等谁·下一步 |
|---|---|---|
| 未开始 `idle` | 无 reviewing 草案 且 无基线 | 人：备料、唤起 agent |
| 待评审 `in_review` | D 存在 且 D 的 pending 批注 > 0 | 人：逐条作答 |
| 待重交 `await_resubmit` | D 存在 且 pending=0 且 D 落库后新答（draft_id=D.id 且 answered）> 0 | agent：取答案回写重交 |
| 待定稿 `await_finalize` | D 存在 且 pending=0 且 无 D 的新答 | 人：抽查、定稿发版 |
| 已定稿 `finalized` | 无 reviewing 草案 且 有基线 | 无人：等新素材 |

依据既有覆盖语义（doc-pipeline「草案覆盖与批注联动」：新草案落库→旧草案 superseded、pending 撤回、answered 存续且 draft_id 仍指旧草案）：agent 重交后 D 换新，D' 重新按上表计算——重交产生新批注→待评审，零批注→待定稿。口径自洽，无需新增数据。

**行为不变式**：五态只是展示层派生，不改管线行为；待重交态下人仍可直接定稿（现状语义，finalize 只要求草案 reviewing）。

## 4. 项目列表与项目版本（ProjectsView + Project 模型）

- 列：项目（名称+描述）/ 材料 / 批注 / **项目版本** / **项目状态** / 操作。需求的版本与状态**不出现在列表**（项目内看）。
- **项目版本**：`Project.version` 新字段，默认 `1.0.0`；`PATCH` 可改，`^\d+\.\d+\.\d+$` 硬校验（422 `VERSION_FORMAT`）；项目自有属性，与需求定稿完全解耦。
- **项目名称唯一**：POST/PATCH trim 后精确匹配查重（排除自身）→ 409 `DUP_NAME`；DB 启动幂等 `CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_name`（存量重名则记 warning 跳过，API 兜底）；前端表单内联报错。
- **操作栏**：`.btn.sm` 文字按钮族——进入（primary）/ 编辑 / 删除（danger，二次确认不变）。

## 5. 需求状态露出（两处文案级例外，子页布局不动）

- 评审页工具条既有徽标：文案由「草案评审中」升级为五态值（待评审/待重交/待定稿；无草案时维持既有「已定稿/基线」形态）——只换文案与颜色，不动布局。
- 版本页时间线「(草案) 评审中」条目徽标：同步换为当前需求状态文案。

## 6. 定稿版本号 x.x.x（snapshots.finalize + 定稿弹窗）

- 格式 `^\d+\.\d+\.\d+$`（纯数字三段，无 v 前缀）；不合法 422 `VERSION_FORMAT`（与项目版本共用格式常量）。
- 建议值：基线命中 x.x.x → patch+1；无基线或存量旧格式 → `1.0.0`。存量版本号不迁移，回退/展示照旧。
- 前端定稿弹窗：placeholder「如 1.2.0」+ 本地正则内联校验，后端兜底。

## 7. 文档同步（根 AGENTS.md 义务，随实施同批完成）

- `docs/api.md`：PATCH 扩展 status/version 字段与错误码（409 DUP_NAME / 409 PROJECT_READ_ONLY / 409 INVALID_STATUS_TRANSITION / 422 VERSION_FORMAT）；finalize 版本格式；stats 增 requirement_status。
- `server/app/cli.py` + `docs/quos-agent-api.md`：CLI 透传新错误码说明一句；对接命令表不变。
- `.agents/skills/req-organize/SKILL.md`「配套对接」：补只读项目（已暂停/已结项）提交被 409 拒收的提示一句（调用方式不变）。

## 8. 测试（定向）

- server：名称唯一（create/patch 409、唯一索引幂等）；项目状态枚举与转移校验、只读态写端点全拦（材料/草案/导入/作答/定稿/回退）、治理动作不拦；requirement_status 五态判定（覆盖 superseded/answered 存续口径）；项目版本与 finalize 版本格式 422、合法通过、建议值。
- web：现有 tests 定向补；派生口径若抽纯函数则单测，UI 结构不建新测试基建。

## 非目标

- 不新增项目概览首页；不迁移存量版本号；未来模块仅占位；不引入 vue-router；不锁前端入口（只读拦截以后端为准，前端 toast 错误）；子页布局交互不动（§5 两处文案除外）。
