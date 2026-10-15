# QuOS v2 接口参考

> 本文是全部 HTTP 端点的**契约参考**（现状描述）。agent 调用协议与纪律（调用顺序、校验报告处理）见 `docs/quos-agent-api.md`。
>
> **维护规则**：接口增删改（端点/参数/请求体/响应/错误码）必须同一次改动同步本文——见仓库根 `AGENTS.md`。

- 基址：`http://127.0.0.1:8000`（本地无鉴权；8000 被占时换端口并相应调整）
- 全部响应 JSON、成功状态码 200；错误用 HTTP 语义：**404** 资源不存在（detail 字符串）/ **409** 冲突 / **422** 校验拒收
- **draft 提交两端点**（POST `/doc/draft`、`/doc/draft/import`）的 422/409 带 code：422 结构 `{"detail": {"hard_errors": [{"code", "rule_no?", "detail"}]}}`（import 的 FORMAT_CONTRACT/MERMAID_SYNTAX 无 rule_no），`detail.nearest` 是 QUOTE_NOT_FOUND 时材料内最相近片段；409 见 `SINGLE_REVIEWING`。materials 的 409 也带 `{"code": ...}`（`DUPLICATE_MATERIAL`、`MATERIAL_IN_USE`）。其余端点的 422/409 为 FastAPI 默认结构或 detail 字符串，以各端点小节为准
- 主要错误码：`SCHEMA`（payload 结构不合法）/ `QUOTE_NOT_FOUND` / `BLOCK_*`、`CHAPTER_PARENT_*`（块结构与层级）/ `FORMAT_CONTRACT`、`MERMAID_SYNTAX`（md 导入格式硬校验）/ `SINGLE_REVIEWING`（409，并发撞唯一 reviewing）/ `DUPLICATE_MATERIAL`、`MATERIAL_IN_USE`（409）

## projects（项目管理）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/projects` | 项目列表（含状态总览） |
| POST | `/api/v1/projects` | 创建项目 |
| GET | `/api/v1/projects/{pid}` | 项目详情 |
| PATCH | `/api/v1/projects/{pid}` | 改名/改描述 |
| POST | `/api/v1/projects/{pid}/archive` | 归档 |
| POST | `/api/v1/projects/{pid}/restore` | 恢复 |

- **GET 列表**：query `archived: bool = false`。响应数组，元素 `{id, name, description, archived, created_at, stats}`；`stats = {materials, pending_annos, version, draft_status}`（draft_status 为 `"reviewing"` 或 null）。
- **POST 创建**：body `{"name": str 必填非空, "description": str = ""}` → 200 元素同上；name 空白 422 `"name required"`。pid 不存在 404 `"project not found"`（下同，不再逐条重复）。
- **GET 详情 / PATCH**：PATCH body `{"name"?: str, "description"?: str}` 均可选，只传要改的。

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

- **GET baseline**：无定稿 `{"empty": true}`（冷启动）；有则 `{"empty": false, "version", "snapshot"(完整 DocPayload), "note"}`。
- **GET draft**：无 reviewing 草案 `{"empty": true}`；有则 `{"draft_id", "status", "payload", "check_report", "created_at"}`；`check_report = {soft_warnings: [{code, rule_no}], auto_questions: [payload]}`。
- **POST draft/import**：body `{"markdown": str 必填, "rules_meta"?: {"<规则号>": {"violation"?, "quote"?}}}`。平台内置 md→DocPayload 转换（章节/规则/块/表格/术语表/图；quote 自动匹配材料文本 ≥0.45）。格式硬校验导入即拒收（FORMAT_CONTRACT：ASCII 盒子图、mermaid 节点半角括号、引用块承载实质内容；MERMAID_SYNTAX：node 端真实 parse）→ 422。成功走与 POST draft 相同的校验落库，附录 A 待确认问题清单自动转批注（source=agent，锚定正文）。响应同 POST draft。
- **POST draft**：body 即 DocPayload `{meta, overview, glossary, new_terms, chapters, rules}`。章节 `{id/title/pri/parent?/background/blocks/rule_nos}`，blocks 有序，每块 `{type: para|states|table|figure|exceptions|diagram, text?, title?, columns?, rows?, flows?, items?}`；rules 每条 `{no/text/violation/quote/material_id/status/replaced_by}`。校验两级：硬错误整体拒收 422（SCHEMA/QUOTE_NOT_FOUND/BLOCK_*/CHAPTER_PARENT_*）；软警告转批注（source=auto）。成功 `{"draft_id", "status": "reviewing", "check_report"}`；并发撞唯一 reviewing 409 SINGLE_REVIEWING。覆盖语义：旧 reviewing → superseded，其 pending 批注撤回。
- **GET versions**：响应 `[{version, note, created_at}]` 新在前。
- **POST finalize**：body `{"draft_id": int, "version": str, "note": str = ""}` → 版本快照 + 条款级变更记录；响应 `{"version", "note"}`。
- **POST revert**：body `{"version": str}` → 基线指回该版本；响应 `{"ok": true, "baseline": version}`。
- **GET changes**：query `version?`（过滤）。响应 `[{version, rule_no, kind, old_text, new_text, reason, approver, created_at}]`。

## questions（批注）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/projects/{pid}/questions` | 批注列表 |
| POST | `/api/v1/projects/{pid}/questions` | 批量提交批注（agent） |
| POST | `/api/v1/questions/{qid}/answer` | 作答（人在平台操作） |

- **GET 列表**：query `status?`（pending/answered/withdrawn）。响应 `[{id, batch_id, kind, payload, anchor, status, answer, answered_at, source, draft_id, created_at}]`；`source` = agent（agent 提交）/ auto（软警告转题）；`anchor = {chapter_id?, rule_no?, seg?, chapter?}`。
- **POST 批量**：body 为数组，元素 `{kind: "choice"|"confirm"|"fill"|"scan", payload: {...}, anchor: {...}}`；语义校验失败 422（choice 需 ≥2 options）。整批同 batch_id，挂当前 reviewing 草案。响应创建后的完整数组（同 GET 元素）。
- **POST answer**：body `{"answer": {...}}`；withdrawn 批注 409 `"question withdrawn"`。pending/answered 均可作答（重新作答=覆盖，scan 逐项提交依赖此语义）。

## health

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查，响应 `{"ok": true}` |
