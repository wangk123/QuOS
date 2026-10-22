# 平台对接协议（QuOS v2 接口）

> req-organize 的附属文件。**只在需要把加工成果提交 QuOS 平台时读取本文件**；纯文档整理（不落平台）用不到。

加工成果一律经平台接口提交，平台不内置 LLM。基址默认 `http://127.0.0.1:8000`（本地无鉴权；若 8000 被占用，起服务时换端口并相应调整）。

## 调用顺序（短事务：唤起 → 拉取 → 加工 → 提交 → 退出）

1. `GET /api/v1/projects/{pid}/materials` — 拉材料清单（含 parsed_text，出处核对与 quote 复制的唯一来源）。CLI：`uv run --directory server python -m app.cli materials PID`（找 pid 用 `projects`）；
2. `GET /api/v1/projects/{pid}/doc/baseline` — 拉当前基线（无定稿返回 `{"empty":true}`，冷启动；有则增量加工）。CLI：`uv run --directory server python -m app.cli baseline PID`；
3. 加工（按 req-organize 全流程 + 写作纪律）产出 DocPayload：`{meta, overview, glossary, new_terms, chapters, rules}`。章节含 `id/title/pri/parent(可选,父章节id)/background/blocks/rule_nos`，blocks 是正文块有序列表，每块 `{type: para|states|table|figure|exceptions, text?, title?, columns?, rows?, flows?, items?}`；rules 每条含 `no/text/violation/quote/material_id/status/replaced_by`；
4. 本地预检：按 req-review 判据过一遍（含五查第 3-5 查与可读性检查），打回项修完再进下一步；
5. 提交草案（二选一）：
   - **推荐：`POST /api/v1/projects/{pid}/doc/draft/import`** — **multipart**：`md` 文件 part + `figures` 图文件集（diagram-design HTML 图，md 以整行 `![图意图](figures/<slug>.html)` 引用，引用文件缺失或引用未独立成行会被 422 拒收）+ `rules_meta`（form，可选）+ `one_pager_md`（form，可选，一页纸由 req-onepager skill 产出的伴生概览，随草案入库、评审页可查看）。平台内置转换（章节/规则/块/表格/术语表/图），quote 自动匹配项目材料文本，violation 可选精修、缺省模板兜底。**agent 只产 md + figures/ 图目录即可**，不用手拼 JSON。CLI：`uv run --directory server python -m app.cli import-draft PID --md 文档.md [--figures 图目录] [--meta meta.json] [--one-pager 一页纸.md]`；
   - `POST /api/v1/projects/{pid}/doc/draft` — body 即 payload 本体（手工构造 payload 时用；quote 必须从材料 parsed_text 原文复制，NFKC+空白折叠后子串匹配；图片类材料 parsed_text 为空可豁免）。CLI：`uv run --directory server python -m app.cli submit-draft PID --file payload.json`；
6. `POST /api/v1/projects/{pid}/questions` — 批量提交消歧批注，元素 `{kind, payload, anchor}`：kind 限 choice/confirm/fill/scan；`payload = {klabel?, q, ctx?, options?}`——**q 所有题型必填非空**（误用 question 等字段名 422 拒收），choice 的 options 元素须为 `{k, t}` 对象（字符串数组拒收）；anchor `{chapter_id, rule_no?, seg?}` 把批注锚到正文片段——`seg` 须为正文原句片段（可在正文搜到）才行内锚定，仅章节级粒度只给 `chapter_id`，勿用问题编号充当 seg（「术语确认」归 confirm，payload.klabel 区分）。CLI：`uv run --directory server python -m app.cli post-questions PID --file items.json`；
7. `GET /api/v1/projects/{pid}/questions?status=answered` — 下次唤起时取已答批注，据答案更新草案重新提交（覆盖 reviewing 旧草案）。CLI：`uv run --directory server python -m app.cli questions PID --status answered`；
8. 全部批注收敛后提示用户在平台上「定稿发版」（版本号/说明由人定，agent 无发版权）。

## CLI 手册

对接平台**优先用 CLI**（相对手拼 curl）：大内容（md 全文、payload、批注数组）一律文件传参，不经 shell 转义；422 拒收明细完整输出 stdout（JSON 机器可读），配合「校验报告处理纪律」修复重交。在**仓库根**执行，完整形式 `uv run --directory server python -m app.cli <cmd>`；`--base` 为全局参数、**须置于子命令之前**（如 `python -m app.cli --base http://127.0.0.1:9000 projects`），默认 `http://127.0.0.1:8000`；不设命令别名。

**输出与退出码**：成功响应 JSON 出 stdout、退出码 0；HTTP 错误（422/404/409）响应体 JSON 仍出 stdout、stderr 一行状态、退出码 1；连接失败（服务未起）或输入文件不存在/非法 JSON，退出码 2（stderr 说明原因）。参数细节另可 `--help`；HTTP 端点契约（请求/响应结构全量）见 `docs/api.md`。

**速查表**

| 命令 | 用途 |
|---|---|
| `projects` | 项目列表（找 pid） |
| `materials PID` | 材料清单（parsed_text 出处源） |
| `baseline PID` | 当前基线（冷启动判断） |
| `draft PID` | 当前 reviewing 草案 |
| `import-draft PID --md FILE [--figures DIR] [--meta FILE] [--one-pager FILE]` | markdown 草案导入（推荐提交路径） |
| `submit-draft PID --file FILE` | 手工 DocPayload 提交 |
| `questions PID [--status STATUS]` | 批注列表 |
| `post-questions PID --file FILE` | 批量提交消歧批注 |
| `versions PID` | 版本列表 |
| `changes PID [--version V]` | 条款级变更记录 |

### 查询类

- **`projects`** — 全量项目。元素含 `id`（即 pid）/`name`/`status`/`version`/`stats`（materials、pending_annos、version、draft_status、requirement_status）。
- **`materials PID`** — 项目材料。元素含 `id`/`filename`/`sha256`/`parsed_text`——**quote 复制与出处核对的唯一来源**。
- **`baseline PID`** — 当前基线；无定稿返回 `{"empty":true}`（冷启动，全量整理），有则增量加工。
- **`draft PID`** — 当前 reviewing 草案（无则 `empty:true`）。`payload` 章节id 形如 `c2`/`c2-1`（按文档顺序生成）——**批注 anchor.chapter_id 必须从这里取**；`one_pager_md` 为伴生一页纸（可空）。
- **`questions PID [--status pending|answered|withdrawn]`** — 批注列表（默认全量）。元素字段同 GET 端点：`{id, batch_id, kind, payload, anchor, status, answer, answered_at, source, draft_id, created_at}`。
- **`versions PID` / `changes PID [--version V]`** — 版本历史与条款级变更记录。

### 提交类

#### `import-draft PID --md FILE [--figures DIR] [--meta FILE] [--one-pager FILE]`（推荐路径）

| 参数 | 必填 | 说明 |
|---|---|---|
| `--md` | ✓ | 草案 markdown 文件（UTF-8） |
| `--figures` | | 图目录：diagram-design 自包含 HTML 图集；目录内所有 `.html` 全量随交，md 以整行 `![图意图](figures/<slug>.html)` 引用 |
| `--meta` | | rules_meta JSON：`{规则号: {violation, quote}}`（violation 精修；quote 缺省由平台自动匹配材料） |
| `--one-pager` | | 需求一页纸 markdown（req-onepager skill 产出的伴生概览，随草案入库、评审页可查看） |

- **覆盖语义（事务）**：新草案入库同时，旧 reviewing 转 superseded、其 pending 批注自动撤回（answered 存续）——重导重发安全。
- **422 拒收**：图引用未独立成行/引用文件缺失（`FORMAT_CONTRACT`）、ASCII 盒子图、mermaid 语法错误（`MERMAID_SYNTAX`，detail 带位置与修法）。导入即验证，按明细修复重导。
- **409**：`PROJECT_READ_ONLY`（项目暂停/结项，停等人侧恢复）；`SINGLE_REVIEWING`（并发提交）。

#### `submit-draft PID --file FILE`（手工 payload，一般不用）

文件为 DocPayload JSON：`{meta, overview, glossary, new_terms, chapters, rules}`。章节 `{id, title, pri, parent?, background, blocks, rule_nos}`，blocks 每块 `{type: para|states|table|figure|exceptions, text?, title?, columns?, rows?, flows?, items?}`；rules 每条 `{no, text, violation, quote, material_id, status, replaced_by}`。**quote 必须从材料 parsed_text 原文复制**（NFKC+空白折叠后子串匹配；图片类材料豁免）。422 硬错误 `{"detail":{"hard_errors":[{code, rule_no, detail}]}}`——`QUOTE_NOT_FOUND` 的 detail.nearest 为最相近片段，必须修正重交。

#### `post-questions PID --file FILE`

文件为批注 JSON 数组，每个元素：

```json
{
  "kind": "choice | confirm | fill | scan",
  "payload": {
    "klabel": "待确认 Q1（可选，列表展示标签）",
    "q": "题面：所有题型必填且非空",
    "ctx": "来源说明（可选）",
    "options": [{ "k": "A", "t": "选项文案", "c": "可选备注" }]
  },
  "anchor": {
    "chapter_id": "c2-1（draft payload 真实章节 id）",
    "rule_no": "GP-01（可选，有规则文档时）",
    "seg": "题面所指的正文原句片段（逐字）"
  }
}
```

- **`payload.q` 所有题型必填非空**——误用 `question`/`label` 等字段名 422 拒收（明细会提示误用字段）；
- **choice 的 `options` ≥2 且每个元素为 `{k, t}` 对象**（k=选项键、t=文案、c 可选）——字符串数组/缺键拒收；
- **锚定语义**：`seg` 为正文原句片段（可在 draft payload 章节文本搜到）→ 前端行内锚定；只有章节/场景级粒度 → 只给 `chapter_id`（挂章节徽标）；**禁止拿问题编号（Q1/TBD-01）充当 seg**；
- 「术语确认」归 confirm，`payload.klabel` 用「术语确认」区分；
- **整批原子**：任一元素校验失败全批拒收，不落半批。错误明细格式 `批注校验失败[第N条 kind]: 原因`——按明细修复整批重交。

## 校验报告处理纪律

- **项目只读态**：项目被暂停/结项后一切提交（材料/draft/import/批注）409 `{"code": "PROJECT_READ_ONLY"}`——停等人侧恢复/重开项目后再提交，不要重试绕过；定稿版本号非 `x.x.x` 三段数字 422 `VERSION_FORMAT`。
- `POST draft` 硬错误 → 422，响应体 `{"detail":{"hard_errors":[{code, rule_no, detail}]}}`：**必须修正后重交，禁止绕过**。`QUOTE_NOT_FOUND` 的 detail.nearest 是材料内最相近片段，对照修正 quote；`BLOCK_*`/`CHAPTER_PARENT_*` 是正文块结构与层级错误，按 detail 修正；
- **import 的格式硬校验**：ASCII 盒子图、mermaid 节点半角括号、引用块承载实质内容、mermaid 语法错误（平台用 node 端真实 parse 校验）→ 422 拒收（`FORMAT_CONTRACT`/`MERMAID_SYNTAX`，detail 带位置与修法）。**导入即验证、agent 自动修复重导，全程无人工**——渲染层不静默降级（与文档内容层 fail fast 原则一致）；前端源码降级仅为 bug 兜底且页面显式标注；
- 软警告 → 平台自动转批注（source=auto，带 anchor），不阻塞入库；`new_terms` 由本 skill 自查申报（发现新词是 AI 职责，平台不猜词）；
- 编号口径：active 复用基线同编号 = 修改路径放行；**复活已作废编号会被拒**；作废必须显式 `status:"voided"` + `replaced_by`；
- 断点续跑：进度以平台状态为准（draft/questions/baseline），agent 不自记进度。

## 其他端点

`GET /doc/draft`（读当前 reviewing 草案）、`GET /doc/versions`、`GET /doc/changes?version=`（变更记录）、`POST /doc/finalize`/`POST /doc/revert`（仅人在平台操作）。

## 有效做法（实战沉淀）

提交前用平台同款校验器本地预检（`server/app/services/validators.py` 的 `check_draft`，材料 parsed_text 从接口拉），quote 全部原文切片并在脚本里断言 `quote in material_text`——一次过 422 往返。参考重做脚本模式（2026-10-14 首例 91→68 条重做验证过）。

**md→payload 转换已内置平台**（2026-10-15，`POST /doc/draft/import`），以下清洗规则在 `server/app/services/md_import.py` 维护，外部转换脚本退役。历史沉淀（转换器实现依据）：
- 行内 `**粗体**` → 中文括注【】；反引号删除；
- 有序列表行（`1. `）每条独立成段，去编号；
- figure 的 flows 只收含 `→`/`-->` 的行；` --label--> ` 转为 ` → label → `（label 变中间节点）；行首续链箭头剥除；mermaid 围栏内容不进 flows；
- 注意脱敏手机号 `138****2344` 是合法内容，粗体正则需成对包裹才转换，不会误伤，但检测残留时要把四连星排除。
