# QuOS v2 接口参考

> 本文是全部 HTTP 端点的**契约参考**（现状描述）。agent 调用协议与纪律（调用顺序、校验报告处理）见 `docs/quos-agent-api.md`。
>
> **维护规则**：接口增删改（端点/参数/请求体/响应/错误码）必须同一次改动同步本文——见仓库根 `AGENTS.md`。

- 基址：`http://127.0.0.1:8000`（本地无鉴权；8000 被占时换端口并相应调整）
- 全部响应 JSON、成功状态码 200；错误用 HTTP 语义：**404** 资源不存在（detail 字符串）/ **409** 冲突 / **422** 校验拒收
- **draft 提交两端点**（POST `/doc/draft`、`/doc/draft/import`）的 422/409 带 code：422 结构 `{"detail": {"hard_errors": [{"code", "rule_no?", "detail"}]}}`（import 的 FORMAT_CONTRACT/DIAGRAM_CHECK 无 rule_no；import 另有 `QUESTION_FORMAT`——附录A待确认清单转换出结构非法批注时整批拒收，一行式清单只支持填空/确认，选择题走 POST questions），`detail.nearest` 是 QUOTE_NOT_FOUND 时材料内最相近片段；409 见 `SINGLE_REVIEWING`。materials 的 409 也带 `{"code": ...}`（`DUPLICATE_MATERIAL`、`MATERIAL_IN_USE`）。其余端点的 422/409 为 FastAPI 默认结构或 detail 字符串，以各端点小节为准
- 主要错误码：`SCHEMA`（payload 结构不合法）/ `QUOTE_NOT_FOUND` / `BLOCK_*`、`CHAPTER_PARENT_*`（块结构与层级）/ `FORMAT_CONTRACT`、`DIAGRAM_CHECK`（md 导入格式与图结构硬校验）/ `SINGLE_REVIEWING`（409，并发撞唯一 reviewing）/ `DUPLICATE_MATERIAL`、`MATERIAL_IN_USE`（409）

## projects（项目管理）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/projects` | 项目列表（含状态总览） |
| POST | `/api/v1/projects` | 创建项目 |
| GET | `/api/v1/projects/{pid}` | 项目详情 |
| PATCH | `/api/v1/projects/{pid}` | 改名/描述/版本/状态 |
| DELETE | `/api/v1/projects/{pid}` | 删除项目（物理删除，不可逆） |

- **GET 列表**：响应数组，元素 `{id, name, description, status, version, created_at, stats}`；`stats = {materials, pending_annos, version, draft_status, requirement_status}`（draft_status 为 `"reviewing"` 或 null；requirement_status 为平台派生的需求状态：`idle 未开始 / in_review 待评审 / await_resubmit 待重交 / await_finalize 待定稿 / finalized 已定稿`，只统计当前 reviewing 草案名下批注）。
- **POST 创建**：body `{"name": str 必填非空, "description": str = ""}` → 200 元素同上（默认 `status="in_progress"`、`version="1.0.0"`）；name 空白 422 `"name required"`；**名称全局唯一**，trim 后重名 409 `{"code": "DUP_NAME"}`。pid 不存在 404 `"project not found"`（下同，不再逐条重复）。
- **GET 详情 / PATCH**：PATCH body `{"name"?: str, "description"?: str, "version"?: str, "status"?: str}` 均可选，只传要改的。`version` 须匹配 `^\d+\.\d+\.\d+$`（纯数字三段），否则 422 `{"code": "VERSION_FORMAT"}`；`status` 取值 `in_progress 进行中 / paused 已暂停 / closed 已结项`，非法值 422，非法转移（如 closed→paused）409 `{"code": "INVALID_STATUS_TRANSITION"}`（合法转移：进行中↔暂停、进行中/暂停→结项、结项→进行中）。
- **只读拦截**：项目 `paused/closed` 时一切写操作（材料上传/删除、draft 提交/导入、批注提交、批注作答、finalize、revert、name/description/version 修改）409 `{"code": "PROJECT_READ_ONLY", "status": <status>}`；治理动作（PATCH 仅 status、DELETE）与读操作不拦。
- **DELETE**：连带清除该项目全部材料 / 草案 / 版本 / 基线 / 变更记录 / 批注 / 规则 / 术语与磁盘目录 `data/<pid>/`；成功 `{"ok": true}`。

## materials（材料池）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/projects/{pid}/materials` | 上传材料（multipart，解析入库） |
| GET | `/api/v1/projects/{pid}/materials` | 材料列表（agent 拉取口） |
| DELETE | `/api/v1/projects/{pid}/materials/{mid}` | 删除材料 |

- **POST 上传**：multipart 字段 `file`（pdf/图片等二进制）。服务端 sha256 去重（材料只增不改）：同 hash 409 `{"code": "DUPLICATE_MATERIAL", "material_id": <原记录>}`。文本自动解析入库。响应 `{id, filename, type, sha256, size, parsed_text, created_at}`。
- **GET 列表**：响应数组，元素同上传响应。`parsed_text` 是出处核对与 quote 复制的**唯一来源**（图片类为空，quote 豁免）。
- **DELETE**：active 规则仍引用该材料时 409 `{"code": "MATERIAL_IN_USE", "rules": [引用的规则号]}`；成功 `{"ok": true}`（同时删文件）。

## doc（文档管线）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/projects/{pid}/doc/baseline` | 当前基线 |
| GET | `/api/v1/projects/{pid}/doc/draft` | 当前 reviewing 草案 |
| POST | `/api/v1/projects/{pid}/doc/draft/import` | markdown 导入（推荐提交路径） |
| POST | `/api/v1/projects/{pid}/doc/draft` | 手工 DocPayload 提交 |
| GET | `/api/v1/projects/{pid}/doc/versions` | 版本列表 |
| POST | `/api/v1/projects/{pid}/doc/finalize` | 定稿发版（人在平台操作） |
| POST | `/api/v1/projects/{pid}/doc/revert` | 回滚基线（人在平台操作） |
| GET | `/api/v1/projects/{pid}/doc/changes` | 条款级变更记录 |

- **GET baseline**：无定稿 `{"empty": true}`（冷启动）；有则 `{"empty": false, "version", "snapshot"(完整 DocPayload), "note", "one_pager_md"(str|null, finalize 时自草案复制)}`。
- **GET draft**：无 reviewing 草案 `{"empty": true}`；有则 `{"draft_id", "status", "payload", "check_report", "created_at", "one_pager_md"(str|null)}`；`check_report = {soft_warnings: [{code, rule_no}], auto_questions: [payload]}`。
- **POST draft/import**：**multipart**——`md`（file，markdown 全文）、`figures`（file[]，可选，diagram-design HTML 图文件集，filename 为 basename，服务端映射 `figures/<filename>`）、`rules_meta`（form，可选，JSON 字符串 `{"<规则号>": {"violation"?, "quote"?}}`）、`one_pager_md`（form，可选，伴生需求一页纸 ≤65536 字符，超限 422 ONE_PAGER_TOO_LARGE；重导不带=清空）。md 正文图以**整行引用** `![图意图](figures/<slug>.html)` 呈现，导入时图文件内容收进 diagram 块（payload 快照冻结版本）。平台内置 md→DocPayload 转换（章节/规则/块/表格/术语表/图；quote 自动匹配材料文本 ≥0.45）。硬校验导入即拒收 → 422：FORMAT_CONTRACT（ASCII 盒子图、引用块承载实质内容、图引用未独立成行、引用的图文件未随请求提交）；DIAGRAM_CHECK（HTML 图缺 title/desc、含 script 或 on*= 事件属性、含外链资源（仅豁免 Google Fonts）、内容越界 viewBox）。软警告不阻塞（进 check_report.soft_warnings，带 detail）：DIAGRAM_LEGACY（存量 mermaid 图源，请重画）、DIAGRAM_ORPHAN（提交了未被引用的图文件）。成功走与 POST draft 相同的校验落库，附录 A 待确认问题清单自动转批注（source=agent，锚定正文）。响应同 POST draft。
- **POST draft**：body 即 DocPayload `{meta, overview, glossary, new_terms, chapters, rules}`，可另带可选字段 `"one_pager_md"?: str`（语义同 import：≤65536、超限 422 ONE_PAGER_TOO_LARGE、覆盖式）。章节 `{id/title/pri/parent?/background/blocks/rule_nos}`，blocks 有序，每块 `{type: para|states|table|figure|exceptions|diagram, text?, title?, columns?, rows?, flows?, items?}`；rules 每条 `{no/text/violation/quote/material_id/status/replaced_by}`。校验两级：硬错误整体拒收 422（SCHEMA/QUOTE_NOT_FOUND/BLOCK_*/CHAPTER_PARENT_*）；软警告转批注（source=auto）。成功 `{"draft_id", "status": "reviewing", "check_report"}`；并发撞唯一 reviewing 409 SINGLE_REVIEWING。覆盖语义：旧 reviewing → superseded，其 pending 批注撤回。
- **GET versions**：响应 `[{version, note, created_at}]` 新在前。
- **POST finalize**：body `{"draft_id": int, "version": str, "note": str = ""}` → 版本快照 + 条款级变更记录；响应 `{"version", "note"}`。**version 只允许 `x.x.x`**（`^\d+\.\d+\.\d+$`，纯数字三段），否则 422 `{"code": "VERSION_FORMAT"}`；与历史重复 409 `DUP_VERSION`（存量历史版本号不迁移，回退照旧）。
- **POST revert**：body `{"version": str}` → 基线指回该版本；响应 `{"ok": true, "baseline": version}`。
- **GET changes**：query `version?`（过滤）。响应 `[{version, rule_no, kind, old_text, new_text, reason, approver, created_at}]`。

## questions（批注）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/projects/{pid}/questions` | 批注列表 |
| POST | `/api/v1/projects/{pid}/questions` | 批量提交批注（agent） |
| POST | `/api/v1/questions/{qid}/answer` | 作答（人在平台操作） |

- **GET 列表**：query `status?`（pending/answered/withdrawn）。响应 `[{id, batch_id, kind, payload, anchor, status, answer, answered_at, source, draft_id, created_at}]`；`source` = agent（agent 提交）/ auto（软警告转题）；`anchor = {chapter_id?, rule_no?, seg?, chapter?}`。锚定语义：`seg` 为正文原句片段时前端行内锚定（规则文本与章节段落内匹配），否则降级挂章节徽标——提交方应引用正文原文，勿用问题编号充当 seg。
- **POST 批量**：body 为数组，元素 `{kind: "choice"|"confirm"|"fill"|"scan", payload: {...}, anchor: {...}}`；`payload = {klabel?, q, ctx?, options?, items?}`——**`q`（题面）为所有题型必填且非空**，误用 `question`/`label` 等字段名会被 422 拒收并在明细中提示；choice 另需 `options` 为 ≥2 元素的数组且每个元素为 `{k, t}` 对象（k=选项键如 A/B 且**不重复**、t=文案、c 可选备注），非列表（数字/字符串等）与字符串数组/缺键一律打回；scan 需 `items` 为非空字符串数组。错误明细含序号与原因，agent 按明细修复重交。整批同 batch_id，挂当前 reviewing 草案。响应创建后的完整数组（同 GET 元素）。
- **POST answer**：body `{"answer": {...}}`；withdrawn 批注 409 `"question withdrawn"`。pending/answered 均可作答（重新作答=覆盖，scan 逐项提交依赖此语义）。
- **POST reopen**：`/questions/{qid}/reopen` 无 body；已答批注重开为 pending 并**清空旧答案**（评审页「重新作答」的持久化入口）。仅 answered 可重开：pending 409 `"仅已答批注可重开"`、withdrawn 409 `"question withdrawn"`、只读项目 409 `PROJECT_READ_ONLY`。

## health

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查，响应 `{"ok": true}` |
