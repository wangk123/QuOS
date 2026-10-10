# 版本管理优化（手动版本号 + 说明 + 回滚/废弃）· 设计 spec

> 日期：2026-10-10 ｜ 状态：设计定稿，待实现 ｜ 基线：main 4e084e1 ｜ 原型：reports/version-preview/index.html（场景直达 `?acts=1#s1`）

## 1. 背景与决策

现状版本 = data 目录 git tag：自增 `v1,v2…`；版本说明仅经 `window.prompt` 进 commit message，GET /baseline 只返回 tag+commit，时间线上说明与时间实际不显示；无回滚、无废弃。

多轮裁定后的最终口径：

1. **版本号 `x.x.x` 手动输入**，不再自增；tag 命名 `v{x.y.z}`（如 `v1.2.3`）。
2. **支持版本说明**：新增版本表单（替代 window.prompt）输入，纯文本，**不做 markdown 渲染**；时间线展示说明与时间。**预览/导出需求文档新增 markdown 渲染模式**（渲染 ⇄ 源码切换，默认渲染；下载仍 .md 源码）——「不支持 markdown」仅限定版本说明。
3. **回滚 = 直接回滚**：二次确认后工作区完整恢复到目标版本，**未存版修改丢弃且不可恢复**；不做「先留底再回滚」。
4. **废弃 = 彻底隐藏**：`git tag -d`，从时间线消失，不可再回滚/查看；commit 仍在 git 历史可手动找回。
5. **版本号校验三规则**：格式 `^\d+\.\d+\.\d+$`；不与已有版本重复；**不低于已有最大版本号**（仅新格式参与比较，防回滚后存出倒挂版本号；「当前」徽章独立按 HEAD 所指，见 §2 restore）。
6. 动作命名统一为**「新增版本」**（原「存为版本」）。

## 2. 后端设计（server/app/storage/gitops.py）

四函数职责：

- `save_baseline(root, version, note) -> dict`
  - 校验：version 匹配 `^\d+\.\d+\.\d+$`，否则 `ValueError`；tag `v{version}` 不得已存在；version 不得 ≤ 列表最大新格式版本（倒挂下限基准；旧 `vN` 不参与，回滚到旧版后仍可存高位版本）。
  - 行为：`git init`（无 .git 时）→ `add -A` → **恒建 commit**（无变更时空 commit `--allow-empty`；note 为 message，空 note 默认「基线存档」）→ 打 tag → 返回 `{tag, version, commit}`。恒建的理由：跳过 commit 会让 tag 挂旧 commit、时间线显示旧 message，本次输入的说明丢失（线上实测踩过）。
- `list_baselines(root) -> list[dict]`
  - `git for-each-ref refs/tags` 一次取 `%(refname:short) %(objectname) %(contents:subject) %(committerdate:unix)`，补齐 `note` / `time` 字段（轻量 tag 的 contents/committerdate 即指向 commit 的）；每项补 `cur: bool`（tag commit == `git rev-parse HEAD`，前端「当前」徽章依据——回滚后旧版标当前，不依赖列表末位）。
  - 排序：tag 解析为 `(major, minor, patch)` 语义化升序（末项 = 当前）；旧 `vN` 映射 `(N, 0, 0)` 兼容显示，行内带「旧格式」视觉标识（前端职责）。
- `restore_baseline(root, tag)`：`git reset --hard <tag>` + `git clean -fd`——工作区完整回到该版。回滚后 HEAD 即该 tag，「当前」= 时间线中 HEAD 所指版本；之后再新增版本从该点继续 commit（被丢弃线上的旧 commits 无 tag 引用即不可见，符合预期）。
- `delete_baseline(root, tag)`：`git tag -d <tag>`。tag 不存在时幂等成功。

## 3. API 变更（server/app/api/router.py）

| 端点 | 变更 |
|------|------|
| `POST /baseline` | Body 新增必填 `version: str`；校验失败 422（detail 区分格式/重复/倒挂）；`note` 默认值不变；响应 `v` 字段改 `version`（前端仅用 `tag`，无破坏面） |
| `GET /baseline` | 响应每项补 `time`（unix 秒）/`note`/`cur` 字段（数组结构不变，兼容） |
| `POST /baseline/restore?tag=` | 新增；tag 不存在 404 |
| `DELETE /baseline?tag=` | 新增（废弃） |

## 4. 前端设计（web/src/components/VerModal.vue + api.ts）

- **新增版本表单**（二级弹层，复用 head/body/foot 三段弹窗体系）：版本号 input（mono 字体、实时校验：格式/重复/倒挂 → 红字 + 红描边，合法 → 绿字 `将存为 vX.Y.Z`）+ 说明 textarea（可空）。提交成功 toast + 重拉列表。
- **时间线**：每行 `版本号 · 时间 · commit 短哈希` + 下方纯文本说明（`white-space: pre-wrap`，不渲染 markdown）；当前行（HEAD 所指）绿点 + 「当前」徽章；非当前行 hover 出「↩ 回滚到此版」「✕ 废弃」行操作，当前行无操作；旧 `vN` 行灰显 + 「旧格式」徽章。
- **回滚确认弹层**：标题「回滚到 X.Y.Z」，红字警示「当前未存版的修改将被丢弃，且不可恢复」+「已存版本不受影响」；确认按钮危险色。
- **废弃确认弹层**：标题「废弃版本 X.Y.Z」，说明「从时间线彻底消失，无法再回滚或查看；存档数据仍保留在 git 历史中，可手动找回」。
- 动作后均重拉列表；回滚后同时刷新父级详情数据（emit 既有 `saved` 语义扩展或新增 `restored` 事件）。
- **预览 markdown 渲染模式**：预览弹层头部加「渲染 / 源码」切换（默认渲染）。渲染走新增 `web/src/utils/md.ts`——受限渲染器，只覆盖导出文档实际用到的语法子集（`#`~`######` 标题、`- ` 无序列表、`| |` 表格含 `\|` 转义、空行分段；**不实现**代码块/引用/链接/图片），**全量 HTML escape 后再组标签**（规则文本源自材料与用户输入，v-html 前必须转义）。不新增依赖。

## 5. 错误与边界

- **旧数据兼容**：已有 `vN` tag 项目照常列出（`(N,0,0)` 排序）并可回滚/废弃；新版本号只与**新格式**版本比较倒挂（旧 vN 不参与下限）。
- **回滚目标为旧 vN**：允许（reset 不区分 tag 格式）。
- **无变更新增版本**：允许（同现状语义，tag 指向当前 commit）。
- **并发**：单人单机工具，不做并发锁（同现状）。
- **回滚到当前版本 / 废弃当前版本**：前端不出操作入口；后端收到请求按幂等处理（restore 到 HEAD 为 no-op，delete 当前 tag 允许但正常流程不会触达）。

## 6. 测试计划

- **gitops 单测**（真实临时目录 init 仓库）：版本号三规则校验各自拒绝；正常存版 tag/commit 正确；无变更存版 tag 指向当前 commit；list 补齐 time/note 且语义化排序（含旧 vN 混排）；restore 后文件内容与目标版一致且新增未跟踪文件被清理；delete 后列表移除、commit 仍在（`git log` 可见）。
- **API 测试**：POST 缺 version 422；三校验 422 detail 文案；restore 不存在 tag 404。
- **VerModal.spec.ts 适配**：表单校验态（格式/重复/倒挂红字）、确认弹层文案、动作后重拉；既有存版用例改走表单；预览模式切换（渲染视图含表格/标题 HTML、源码视图为 pre）。
- **md.ts 单测**：语法子集渲染（标题层级/列表/表格转义 `\|`）、HTML escape（`<script>` 等输入被转义）、未知语法按段落原文输出。
