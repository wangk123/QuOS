# 平台对接协议（QuOS v2 接口）

> req-organize 的附属文件。**只在需要把加工成果提交 QuOS 平台时读取本文件**；纯文档整理（不落平台）用不到。

加工成果一律经平台接口提交，平台不内置 LLM。基址默认 `http://127.0.0.1:8000`（本地无鉴权；若 8000 被占用，起服务时换端口并相应调整）。

## 调用顺序（短事务：唤起 → 拉取 → 加工 → 提交 → 退出）

1. `GET /api/v1/projects/{pid}/materials` — 拉材料清单（含 parsed_text，出处核对与 quote 复制的唯一来源）；
2. `GET /api/v1/projects/{pid}/doc/baseline` — 拉当前基线（无定稿返回 `{"empty":true}`，冷启动；有则增量加工）；
3. 加工（按 req-organize 全流程 + 写作纪律）产出 DocPayload：`{meta, overview, glossary, new_terms, chapters, rules}`。章节含 `id/title/pri/parent(可选,父章节id)/background/blocks/rule_nos`，blocks 是正文块有序列表，每块 `{type: para|states|table|figure|exceptions, text?, title?, columns?, rows?, flows?, items?}`；rules 每条含 `no/text/violation/quote/material_id/status/replaced_by`；
4. 本地预检：按 req-review 判据过一遍（含五查第 3-5 查与可读性检查），打回项修完再进下一步；
5. 提交草案（二选一）：
   - **推荐：`POST /api/v1/projects/{pid}/doc/draft/import`** — body `{"markdown": "<md 全文>", "rules_meta": {可选 "<规则号>": {"violation": "...", "quote": "..."}}}`。平台内置转换（章节/规则/块/表格/术语表/图），quote 自动匹配项目材料文本，violation 可选精修、缺省模板兜底。**agent 只产 md 文档即可**，不用手拼 JSON；
   - `POST /api/v1/projects/{pid}/doc/draft` — body 即 payload 本体（手工构造 payload 时用；quote 必须从材料 parsed_text 原文复制，NFKC+空白折叠后子串匹配；图片类材料 parsed_text 为空可豁免）；
6. `POST /api/v1/projects/{pid}/questions` — 批量提交消歧批注，元素 `{kind, payload, anchor}`：kind 限 choice/confirm/fill/scan；anchor `{chapter_id, rule_no?, seg?}` 把批注锚到正文片段（「术语确认」归 confirm，payload.klabel 区分）；
7. `GET /api/v1/projects/{pid}/questions?status=answered` — 下次唤起时取已答批注，据答案更新草案重新提交（覆盖 reviewing 旧草案）；
8. 全部批注收敛后提示用户在平台上「定稿发版」（版本号/说明由人定，agent 无发版权）。

## 校验报告处理纪律

- `POST draft` 硬错误 → 422，响应体 `{"detail":{"hard_errors":[{code, rule_no, detail}]}}`：**必须修正后重交，禁止绕过**。`QUOTE_NOT_FOUND` 的 detail.nearest 是材料内最相近片段，对照修正 quote；`BLOCK_*`/`CHAPTER_PARENT_*` 是正文块结构与层级错误，按 detail 修正；
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
