# Design: quos-v2-rebuild

> 关联:ADR `docs/adr/001`(AI 加工外部化)、`002`(SQLite 真相源)、`003`(v1 废弃);specs delta 本 change `specs/` 六能力域;前端验收基准 `web/prototype/quos-v2-prototype.html`(R1-R6 六轮评审定稿)。

## 1. Intent(为什么做)

v1(reqspec)试用诊断出四条结构性病根:主产物错位(278 条规则条目库,粒度=拆解中间产物,人读不了)、标准焊死在代码(格式/可判定标准硬编码于 prompt 与 pydantic,规则约束层不存在)、AI 参与停留在单发调用(消歧无闭环、无整文自查、质量无裁判)、版本管理缺位(无变更记录、编号不稳、锚点失效)。四病同源:reqspec 把「需求整理」做成了「规则条目化引擎」,而平台定位是「工具汇总 + 规则约束 + 文档管理 + 评审交互」。

结论:**推倒重做**。v2 平台只做三件事——给 agent 定标准(接口+校验)、给人做闸门(批注式评审)、给文档管生命周期(版本);AI 加工完全外部化。

## 2. Goals / Non-goals / Anti-goals

**Goals(M1 验收即此)**
- 以「多模态」项目真实材料端到端跑通:上传材料 → agent(按 req-organize skill)拉取加工 → 草案过校验闸门 → 批注锚进正文 → 人批注式评审 → agent 取答案收敛 → 人自定义版本号发版 → 版本/变更记录可查可回退;人全程只在闸门出现。
- 前端与已定稿原型交互样式完全一致(照原型还原)。

**Non-goals(本期不做,不设计)**
- 多用户、鉴权、并发(单人本地);
- 平台侧触发/嵌入 agent(M3);
- 置信分层放行、抽查监控、埋错验证(M3);
- 文档 md 导出、版本对比增强(M2)。

**Anti-goals(做了即错,回归即返工)**
- 平台内置任何 LLM 调用(回归 v1 病根,ADR-001);
- 用 git 管理文档版本(用户明确否决,ADR-002);
- 规则条目库作为主产物、批注/题目脱离文档正文独立成队列(用户否决的形态);
- 修改接口时破坏既有端点语义(404/409/422 语义恒定)。

## 3. Constraints(全局约束,逐任务隐含)

- 后端 Python 3.12+ / FastAPI / SQLModel / SQLite(`server/data/quos.db`,单库唯一真相源);前端 Vue 3 + Vite + TS,不新增 UI 库(原型 CSS 全量照搬);包管理 uv;
- 原始材料二进制存 `server/data/{pid}/materials/`,库存路径+sha256;解析文本入库;
- 前后端与 agent 共用一套 REST(localhost 无鉴权);错误用 HTTP 语义:404 不存在 / 409 冲突(重复 hash、重复版本号)/ 422 校验失败;
- 校验两级:硬错误拒收、软警告转批注;机器判不了的语义一律变批注让人裁(「发现新词」是 agent 职责,平台不引分词依赖);
- 规则编号项目内唯一、跨草案修改复用同编号、作废显式声明(status=voided + replaced_by)不靠消失推断;
- 代码规范:模块 ≤500 行按职责拆;前端新组件中文注释;commit `<type>:<描述>`。

## 4. 已决定的 How

### 4.1 架构总图

```
外部 agent(ZCode 等)+ skill(req-organize)
        │  HTTP(localhost)
        ▼
QuOS v2 平台(FastAPI)
  统一 REST(前端与 agent 共用)│ 两级校验闸门 │ 状态机(批注/草案/版本)
  SQLite(唯一真相源)+ 文件系统(材料二进制)
        ▲
        │ 浏览器(材料上传/批注评审/发版/版本管理)
```

agent 无状态短事务:唤起 → 拉材料+基线 → 按 skill 加工 → 交草案 → 交批注 → 退出;进度以平台状态为准。

### 4.2 数据模型(SQLModel,8 表)

| 表 | 关键字段 | 说明 |
|---|---|---|
| Project | id, name, description, archived | 项目=材料/文档/批注/版本的容器 |
| Material | id, project_id, filename, path, sha256, mime, parsed_text | 图片类 parsed_text 允许为空 |
| DocDraft | id, project_id, payload(json), status, check_report(json) | 整份文档变更集;项目内同时仅一个 reviewing |
| DocVersion | id, project_id, version(自定义号), snapshot(json), draft_id | 定稿快照,只增不改,自包含 |
| ChangeLog | id, project_id, version, rule_no, old_text, new_text, reason, approver | 条款级变更;approver 固定 "owner" |
| Question | id, project_id, kind, payload, status, answer, answered_at, batch_id, source, draft_id, anchor(json) | 即批注:四题型 choice/confirm/fill/scan;anchor={ch, rule_no, seg} 或 {ch, chapter:true} 锚到正文 |
| Rule | id, project_id, no, text, violation, quote, material_id, status, replaced_by | 锚点层:编号稳定、作废留痕 |
| Term | id, project_id, name, definition | 定稿时由快照 glossary 全量重建 |

快照 payload 结构:meta/overview/glossary/new_terms/rules 与前版一致;chapters 见 §4.4a 文档形态契约。

### 4.3 REST 接口

```
GET/POST/PATCH   /api/v1/projects
POST             /api/v1/projects/{pid}/materials        # multipart;同 hash → 409 指向原记录
GET              /api/v1/projects/{pid}/materials        # 含 parsed_text(agent 消费口)
GET              /api/v1/projects/{pid}/doc/baseline     # 当前基线;无定稿 {"empty":true}
GET              /api/v1/projects/{pid}/doc/draft        # 当前 reviewing 草案(payload+check_report);无草案 {"empty":true}
GET              /api/v1/projects/{pid}/doc/versions
POST             /api/v1/projects/{pid}/doc/draft        # 两级校验闸门
POST             /api/v1/projects/{pid}/questions        # 批量批注(含 anchor);batch_id 平台生成
GET              /api/v1/projects/{pid}/questions?status=pending|answered
POST             /api/v1/questions/{qid}/answer
POST             /api/v1/projects/{pid}/doc/finalize     # {draft_id, version(自定义,唯一性校验→409), note}
POST             /api/v1/projects/{pid}/doc/revert       # {version} 设为当前基线,历史保留
GET              /api/v1/projects/{pid}/changes?version=
```

### 4.4 两级校验闸门(POST /doc/draft)

| 级别 | 检查 | 判定 |
|---|---|---|
| 硬拒收 | quote 归一化定位(去空白/全半角/大小写折叠子串匹配;图片类 parsed_text 为空跳过;quote<6 字降软;失败附最相近片段) | active 规则必查 |
| 硬拒收 | 编号:草案内唯一;与 Rule 表同编号=修改路径放行;新编号不与现存冲突;引用闭合;material_id 不存在单列报错 | — |
| 硬拒收 | 结构:active 规则 violation 非空、章节有标题、作废必带 replaced_by | — |
| 软转批注 | new_terms 申报→术语确认(confirm);已登记术语正文写法不一致→confirm;violation 与 text 完全雷同→confirm;空壳章节(无正文块且零规则)→fill;有叙述或规则的章节不出题 | 不阻塞,草案 reviewing,自动批注带 anchor+source=auto,同内容去重 |

### 4.4a 文档形态契约(2026-10-14 首例草案五连批后修订)

章节正文由**有序自由块 blocks** 组成,取代固定四槽(background/states/exceptions 死板模板):
- 块类型:para(叙述) / states(状态链,→ 连接) / table(columns+rows) / figure(title+flows,每行一条链路,表号/图号渲染时自动编) / exceptions(items);
- 章节 `parent: 父章节 id` 构成层级(渲染自动编号 1 / 1.1),引用不闭合或成环为硬错误;
- 参数表/字段清单/接口契约成 table 块、主链路成 figure 块——不得拆散塞进规则 text(写作纪律由 req-organize/req-review skill 执行,平台只做块结构合法性硬校验);
- 术语表词条与正文的定位:前端确定性匹配自动锚定,点击词条滚动到出现章节(不新增字段,不靠 agent 申报)。

### 4.5 状态机

```
Question(批注): pending → answered;pending → withdrawn(发版时撤未答自动批注;agent 提交批注保留)
DocDraft:  reviewing(校验通过即此态,无 submitted) → finalized(无打回态——不满意=不发版,agent 重交覆盖)
DocVersion: 自定义号只增不改;revert 设当前基线不删历史
Rule:     active → voided(replaced_by)
```

**草案覆盖语义(核心循环)**:agent 重交新草案覆盖 reviewing 旧草案时,旧草案的 pending 批注(含自动与 agent 提交)批量 withdrawn;**answered 批注永久保留**(带原 draft_id,跨草案存续)——发版时 reason 检索范围为项目内全部 answered,不只限当前草案。自动批注按(题型+关键内容)跨草案去重,防重复问。

发版流程:reviewing 草案 + 自定义 version + note → 自包含快照 → 与**当前基线**逐规则比对生成 ChangeLog(作废以草案声明为准;reason 优先取同 rule_no 的 answered 批注答案,仅规则级匹配)→ Rule 表同步 → Term 表由 glossary 全量重建 → 未答自动批注 withdrawn → 草案 finalized。变更记录只覆盖规则层(编号/文本/状态),章节结构变更不进 ChangeLog。

### 4.6 前端(验收基准=原型,照原型还原)

骨架:深色侧栏项目树 + 浅色内容;材料/文档评审/版本是项目内子页;面包屑 QuOS/项目/子页。

1. **项目总览**:表格(材料数/待答批注/当前版本/草案状态)、新建/编辑/输名归档/恢复;
2. **材料页**(项目内):拖拽上传(hash 去重 409)、列表、解析文本 drawer;
3. **文档评审页**(核心,固定视口三栏独立滚动):左章节树(批注计数)+术语表;中正文(批注高亮:未答琥珀/已答绿;规则编号 popover:violation+quote+材料 hash);右批注栏(按章节分组;默认折叠=问题摘要+编号·类型 meta 行;展开作答;定位按钮滚正文;答完自动收起转绿;重新作答);对照/逐条两模式;工具条=草案状态+变更摘要+定稿发版+「⋮ 更多」菜单(低频设置:页宽三档图形化选项);无打回;
4. **版本页**:时间线(草案评审中+历史定稿)+条款变更 diff+「回退到此版」。

实现注意(原型踩过的坑,直接规避):输入类作答用轻量局部更新保焦点;`replaceWith` 后先取引用再绑定事件。

### 4.7 agent 侧配套

`req-organize` skill 增补「平台对接」章节:五接口调用顺序、校验报告处理纪律(硬错误必修正重交、禁止绕过)、断点续跑(进度以平台状态为准)、payload 字段与快照结构对齐。

### 4.8 v1 资产处置

AI 编排(`server/app/ai/`)、树/证据/规则/画像存储、git 基线、MySQL 索引、web 前端:全部删除;材料解析逻辑(pypdf/Pillow)移植为新 `parsers/`;`server/data/` 旧生成数据不迁移,原始材料保留作验收用例。

## 5. 分期

- **M1(本 change)**:上表全部 + skill 对接 + 端到端验收;
- **M2**:变更 diff 视图增强、md 导出、多项目体验完善;
- **M3**:置信分层+抽查监控、埋错验证、req-breakdown(casegen)接入、平台侧触发 agent。

## 6. 实施决定(2026-10-14 二轮 builder check 定案,执行时不再问)

- DocDraft 无 submitted 态:校验通过直接落 reviewing;
- anchor API 形状平铺:`{chapter_id, rule_no?, seg?, chapter?}`;
- 原型「术语批注」归 confirm 题型,payload.klabel 区分展示;四题型恒定;
- answer 按题型:choice=选项 key / confirm=bool(+note 可选)/ fill=文本 / scan=逐项结果,落 json 字段;
- Material 表与响应补 created_at、size、path;图片不引 OCR,parsed_text 空串;
- 版本号任意非空字符串、项目内唯一(409 兜底),建议值 = 现有最大号 +1;revert 后「与上一版比对」取当前基线而非最新版;
- 首版 ChangeLog reason 取材料文件名(缺省草案说明);
- M1 无人工创建批注入口(原型定稿未含,留 M2),withdrawn 仅作用于 source=auto;文案统一「agent 提交批注」非「手动批注」;
- ChangeLog 只记规则层;reason 匹配仅规则级(rule_no);
- 归一化基线:Unicode NFKC + 空白折叠 + 大小写折叠后子串匹配;失败附 difflib 最相近片段;
- SQLite 开 WAL;各表带 created_at;Vite dev proxy → 127.0.0.1:8000;前端在 web/ 内删除 v1 src 重写;
- 「项目内仅一个 reviewing」不变量在 draft 提交与 finalize 处用事务保证(浏览器与 agent 双入口竞态)。

- (2026-10-14 修订)章节正文 blocks 自由块 + parent 层级取代固定四槽;空壳章(无块无规则)才出 fill 题,删除零规则/状态机空逼填出题;块结构与 parent 闭合/成环为硬校验(BLOCK_*/CHAPTER_PARENT_*);术语定位由前端确定性匹配实现;agent 侧新增 req-review skill 作为提交前与人工评审前的强制评审门(可读性判据),req-organize 增写作纪律(规则收敛行为级/结构化内容成块/背景写动机/主链路落图)。

## 7. 留给实施计划(builder)的自由度

- SQLModel 具体 column 类型与索引细节(遵循 §4.2 字段);
- 前端组件文件拆分(遵循 ≤500 行/职责拆分与原型结构,评审页必拆);
- 测试组织(文件划分、fixture 设计)。

## 8. 本文档的演进

本设计经 brainstorming 会话对齐(2026-10-14)、builder check 修订(四阻塞已修)、原型 R1-R6 六轮评审定稿后重写;后续变更先改本文件与对应 spec,再动代码。
