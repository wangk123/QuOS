# QuOS v2 平台重建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 推倒重做 QuOS 为「接口 + 两级校验 + 批注式评审 + 版本管理」的平台,AI 加工外部化,前端照已定稿原型还原。

**Architecture:** FastAPI + SQLModel + SQLite 单库唯一真相源;前后端与 agent 共用一套 REST(localhost 无鉴权);批注锚定文档正文(Word 式),发版自定义版本号;v1 代码全部删除,仅移植材料解析。

**Tech Stack:** Python 3.12 + FastAPI + SQLModel + pypdf/Pillow + pytest/httpx;Vue 3 + Vite + TS(不引 UI 库,原型 CSS 照搬)。

**Spec:** `openspec/changes/quos-v2-rebuild/design.md`(含 §6 实施决定,方向性冲突以 design 为准)+ `specs/` 六能力域 + 原型 `web/prototype/quos-v2-prototype.html`(前端逐屏验收基准)+ ADR `docs/adr/001-003`。

## Global Constraints

- 单人本地:无鉴权、无并发设计;SQLite 开 WAL 于 `server/data/quos.db`
- 错误语义恒定:404 不存在 / 409 冲突(重复 hash、重复版本号)/ 422 校验失败
- 空态约定:`{"empty": true}`(非 404)用于 baseline 与 draft 读取;404 仅项目/资源不存在
- 原始材料二进制存 `server/data/{pid}/materials/`,库存 sha256+path;同 hash 重传 409 指向原记录
- 规则编号:草案内唯一;与 Rule 表同编号=修改路径放行;作废显式 status=voided+replaced_by
- 校验两级:硬错误拒收(整体不入库)、软警告转批注(source=auto,带 anchor,题型+关键内容跨草案去重)
- 批注四题型恒定:choice/confirm/fill/scan;「术语确认」属 confirm(payload.klabel 区分)
- 版本号任意非空字符串、项目内唯一;建议值=现有最大号+1
- 模块 ≤500 行按职责拆;前端新组件中文注释;commit `<type>:<描述>`
- 前端不写自动化测试(vitest 依赖保留给后续);验收=真机对照原型逐屏走查
- 端口:后端 8000,Vite dev 5173,proxy → 127.0.0.1:8000(绕系统代理)

## Review Focus(易咬人的输入类,测试已钉进对应任务)

1. **pypdf 提取文本的换行/全半角/大小写**导致 quote 误拒 → Task 4 归一化用例(必须含真实 PDF 换行场景)
2. **修改路径编号误杀**(草案复用 Rule 表现存编号) → Task 4 编号口径用例
3. **图片材料(parsed_text 空)引用规则**不得死锁 → Task 4 图片豁免用例
4. **重复 hash 上传 / 重复版本号发版**必须 409 且带指向信息 → Task 3 / Task 7
5. **发版 withdrawn 误伤 agent 提交批注**、**answered 批注跨草案存续**(reason 检索依赖) → Task 7
6. **浏览器与 agent 双入口竞态**破坏「单 reviewing」不变量 → Task 7 事务用例

## File Structure

```
server/
  app/main.py                 # FastAPI 装配:CORS(localhost)、router 挂载、建表
  app/db.py                   # engine(SQLite WAL)+ session 依赖
  app/models.py               # 8 表 SQLModel + 快照 payload pydantic(含 anchor)
  app/api/projects.py         # 项目 CRUD/归档恢复/总览
  app/api/materials.py        # 上传/列表
  app/api/doc.py              # baseline/draft(GET+POST)/versions/finalize/revert/changes
  app/api/questions.py        # 批注批量提交/列表/作答
  app/services/validators.py  # normalize/locate_quote/check_hard/check_soft(纯函数)
  app/services/snapshots.py   # 发版快照+ChangeLog+Term 重建+withdrawn+revert
  app/parsers/extract.py      # pdf/md/txt/img 解析(自 v1 移植)
  tests/conftest.py           # in-memory SQLite + TestClient + 临时 data 目录 fixture
  tests/test_{models,projects,materials,validators,doc_api,questions,finalize}.py
web/src/                      # Vue3 重写:router/侧栏骨架/项目总览/材料/文档评审(拆组件)/版本
.agents/skills/req-organize/SKILL.md   # 增补「平台对接」章节
```

---

### Task 1: 脚手架与数据模型

**Files:**
- Create: `server/app/main.py`、`server/app/db.py`、`server/app/models.py`、`server/tests/conftest.py`、`server/tests/test_models.py`
- Modify: `server/pyproject.toml`(加 sqlmodel、python-multipart;删 pymysql;dev 加 pytest、httpx)

**Interfaces:**
- Produces: `engine`/`get_session()`(db.py);8 个 SQLModel 类 `Project/Material/DocDraft/DocVersion/ChangeLog/Question/Rule/Term`(字段严格按 design §4.2+§6:Question.anchor 平铺 `{chapter_id, rule_no?, seg?, chapter?}`,全部表含 created_at);payload pydantic:`DocPayload{meta, overview, glossary, new_terms, chapters, rules}`、`RuleInPayload{no, text, violation, quote, material_id, status, replaced_by}`——后续所有任务的输入契约。

- [ ] **Step 1: 清场与依赖**

保留 v1 的 `server/data/`(原始材料作验收用例,但删除各项目已生成的 json/md/git 仓库,只留 `evidence/files` 下的原始文件移至 `server/data/raw-backup/`);删除 `server/app/`、`server/tests/`、`server/reports/` 全部旧代码。`uv add sqlmodel python-multipart && uv remove pymysql && uv add --group dev pytest httpx`,`uv sync` 通过。

- [ ] **Step 2: 写模型测试(先失败)**

```python
# tests/test_models.py 关键断言
def test_create_all_and_question_anchor(db):  # db fixture 见 conftest
    q = Question(kind="confirm", payload={"q": "术语「幂等键」收录?"},
                 anchor={"chapter_id": "c3", "rule_no": "R15", "seg": "idempotency_key"},
                 status="pending", source="auto")
    db.add(q); db.commit()
    assert db.query(Question).one().anchor["rule_no"] == "R15"

def test_docpayload_roundtrip():
    p = DocPayload.model_validate(json.loads(VOIDED_RULE_SNAPSHOT_JSON))  # 含 R9 voided+replaced_by 的样例
    assert p.rules["R9"].status == "voided" and p.rules["R9"].replaced_by == "R15"
```

Run: `uv run pytest tests/test_models.py -v` → FAIL(模块不存在)

- [ ] **Step 3: 实现 db.py / models.py / main.py / conftest.py**

db.py: `create_engine(f"sqlite:///{DATA}/quos.db", connect_args=...)` + `PRAGMA journal_mode=WAL` event;conftest 用 in-memory engine + `create_all`(每测试独立库);main.py 挂 CORS(`http://localhost:5173`)与 `/api/v1/health`。

- [ ] **Step 4: 跑测试通过** → `uv run pytest tests/test_models.py -v` PASS

- [ ] **Step 5: Commit** `feat:v2 脚手架——SQLModel 8 表与 payload 契约`

---

### Task 2: 项目 API

**Files:**
- Create: `server/app/api/projects.py`、`server/tests/test_projects.py`
- Modify: `server/app/main.py`(挂 router)

**Interfaces:**
- Produces: `GET/POST/PATCH /api/v1/projects`、`POST /api/v1/projects/{id}/archive|restore`;总览字段 `stats{materials, pending_annos, version, draft_status}`(前端项目总览页与侧栏徽标消费)。

- [ ] **Step 1: 失败测试**——`test_projects.py`:建项目(名称必填,空名 422)、改名、归档后列表默认不现/归档视图现、恢复;总览在空项目时 `stats={materials:0, pending_annos:0, version:null, draft_status:null}`。
- [ ] **Step 2: 跑失败** → FAIL
- [ ] **Step 3: 实现** router + 简单聚合查询(材料数=count、待答=count pending、版本=最新 DocVersion.ver、草案=reviewing 存在性)。
- [ ] **Step 4: 跑过** → PASS
- [ ] **Step 5: Commit** `feat:项目 CRUD/归档/总览 API`

---

### Task 3: 材料解析与上传

**Files:**
- Create: `server/app/parsers/extract.py`、`server/app/api/materials.py`、`server/tests/test_materials.py`
- Test fixture: `tests/files/sample.pdf`(pypdf 生成或内置小 PDF)、`tests/files/img.png`

**Interfaces:**
- Produces: `extract(file_bytes, mime) -> str`;`POST /api/v1/projects/{pid}/materials`(multipart,响应含 id/filename/type/sha256/size/parsed_text/created_at)、`GET .../materials`(列表,agent 消费口)。
- Consumes: Task1 模型、Task2 项目存在性(404)。

- [ ] **Step 1: 失败测试**——上传 PDF:parsed_text 非空且含 PDF 内文本;上传 png:parsed_text==""(不报错);**同内容二次上传 → 409,响应带原 material id**;上传到不存在项目 → 404。
- [ ] **Step 2: 跑失败** → FAIL
- [ ] **Step 3: 实现**——sha256 流式计算;落盘 `data/{pid}/materials/{sha256}{ext}`(同 hash 直接 409 不重写);extract 按 mime 分派(pypdf 提文本/md/txt utf-8 decode/其他文本类尽力;img 返回空串)。
- [ ] **Step 4: 跑过** → PASS
- [ ] **Step 5: Commit** `feat:材料上传/hash 去重/解析入库`

---

### Task 4: 校验器(纯函数,TDD 核心)

**Files:**
- Create: `server/app/services/validators.py`、`server/tests/test_validators.py`

**Interfaces:**
- Produces:
  - `normalize(s: str) -> str`(NFKC + 空白折叠 + casefold)
  - `locate_quote(quote, material_text) -> Located{ok: bool, nearest: str}`(子串;失败附 difflib 最相近片段)
  - `check_draft(payload: DocPayload, rules_existing: set[str], materials: dict[int, MaterialRow]) -> Report{hard_errors: list[Err], soft_warnings: list[Warn], auto_questions: list[AutoQ]}`
  - `Err{code, rule_no, detail}`;`AutoQ{kind, payload{klabel,q,ctx}, anchor}`(软警告→批注草稿,含 new_terms→confirm、术语写法不一致→confirm、violation 雷同→confirm、章节零规则/状态机空→fill)
- Consumes: Task1 DocPayload。

- [ ] **Step 1: 失败测试(必须覆盖 Review Focus 1-3)**

```python
def test_normalize_handles_pdf_noise():
    assert locate_quote("身份＋请求体、每个文件的\n  文件名:大小:SHA-256",
                        "……以 身份 + 请求体 + 每个文件的 文件名:大小:SHA-256 计算……").ok

def test_modify_path_reuses_existing_no():          # Review Focus 2
    rpt = check_draft(payload_with(rules={"R12": modified_rule}), rules_existing={"R12"}, ...)
    assert not any(e.code == "NO_CONFLICT" for e in rpt.hard_errors)

def test_new_no_colliding_existing_rejected(): ...
def test_image_material_skips_quote(): ...           # Review Focus 3
def test_short_quote_downgrades_to_soft(): ...       # quote < 6 字 → 软警告
def test_voided_rule_requires_replaced_by(): ...
def test_soft_terms_and_violation_clone(): ...       # new_terms→confirm;violation==text→confirm
```

- [ ] **Step 2: 跑失败** → FAIL
- [ ] **Step 3: 实现**(纯函数,无 IO;唯一准许的库:标准库 difflib/unicodedata)
- [ ] **Step 4: 跑过** → PASS;**加一条用真实 `server/data/raw-backup/` 内某 PDF 的解析文本做 locate_quote 的测试**(验收硬门槛锚定)
- [ ] **Step 5: Commit** `feat:两级校验器——归一化定位/编号口径/软警告转批注`

---

### Task 5: 基线与草案 API

**Files:**
- Create: `server/app/api/doc.py`、`server/tests/test_doc_api.py`
- Modify: `server/app/main.py`

**Interfaces:**
- Produces: `GET .../doc/baseline`(无定稿 `{"empty":true}`);`GET .../doc/draft`(reviewing 草案 payload+check_report,无则 empty);`GET .../doc/versions`;`POST .../doc/draft`——硬错误整体拒收(422,响应 `{hard_errors:[...]}`,不入库、**覆盖旧 reviewing 旧草案 pending 批注 withdrawn、answered 保留**)、通过则入库 reviewing 并落 soft 转出的自动批注(source=auto,带 anchor,题型+关键内容去重);同项目已有 reviewing 时新提交覆盖(事务内:旧草案置 superseded、其 pending 全 withdrawn)。
- Consumes: Task4 check_draft。

- [ ] **Step 1: 失败测试**——空项目 baseline empty;合法草案入库 reviewing + check_report;quote 不可定位 → 422 + hard_errors 含该 rule_no + nearest 片段 + 草案未入库;**覆盖语义**:旧草案 pending 批注(含 auto 与 agent 两种 source)→ withdrawn,answered 批注仍可 GET status=answered 查到(跨草案存续);重复编号(草案内)→ 422;material_id 不存在 → 422 单列错误码。
- [ ] **Step 2: 跑失败** → FAIL
- [ ] **Step 3: 实现**(draft POST 全程单 session 事务)
- [ ] **Step 4: 跑过** → PASS
- [ ] **Step 5: Commit** `feat:基线/草案 API——校验闸门与覆盖语义`

---

### Task 6: 批注 API

**Files:**
- Create: `server/app/api/questions.py`、`server/tests/test_questions.py`

**Interfaces:**
- Produces: `POST .../questions`(批量,元素含 kind/payload/anchor;choice 校验 ≥2 选项、fill 必有题干,违者 422;batch_id 平台生成随响应返回;source=agent);`GET .../questions?status=pending|answered`(返回含 anchor/answer/answered_at);`POST /api/v1/questions/{qid}/answer`(answer 按题型:choice=选项 key / confirm=bool+note / fill=文本 / scan=逐项 dict;答后 pending→answered)。
- Consumes: Task5 draft(批注挂 draft_id)。

- [ ] **Step 1: 失败测试**——批量提交 3 条返回同 batch_id;choice 仅 1 选项 422;answer fill 文本后 GET answered 含该文本;不存在 qid → 404。
- [ ] **Step 2: 跑失败** → FAIL
- [ ] **Step 3: 实现**
- [ ] **Step 4: 跑过** → PASS
- [ ] **Step 5: Commit** `feat:批注 API——批量提交/anchor/作答`

---

### Task 7: 发版与版本化

**Files:**
- Create: `server/app/services/snapshots.py`、`server/tests/test_finalize.py`
- Modify: `server/app/api/doc.py`

**Interfaces:**
- Produces: `POST .../doc/finalize` `{draft_id, version, note}` → 快照入库、ChangeLog 生成、Rule/Term 同步、auto 未答 withdrawn、draft→finalized;`POST .../doc/revert` `{version}` → 基线指针切换(历史保留);`GET .../changes?version=`。
- Consumes: 全部前序。

- [ ] **Step 1: 失败测试(Review Focus 4-6)**

```python
def test_finalize_custom_version_dup_409(): ...        # v2 已存在再发 v2 → 409
def test_first_release_changelog_all_added(): ...      # reason=材料文件名
def test_modify_rule_changelog_old_new(): ...          # 修改:old_text/new_text;reason 取同 rule_no answered 批注答案
def test_finalize_withdraw_auto_keeps_agent(): ...     # auto 未答→withdrawn;agent 提交 pending→保留
def test_answered_survives_across_drafts(): ...        # 覆盖过的草案 answered 参与 reason
def test_single_reviewing_invariant_under_race(): ...  # 并发两 draft POST,事务保证仅一个 reviewing(可用线程+两 session 模拟)
def test_revert_switches_baseline_not_delete(): ...    # revert v2 后 baseline=v2,v3 仍在 versions
def test_changelog_only_rule_level(): ...              # 章节文本改动不产生 ChangeLog
```

- [ ] **Step 2: 跑失败** → FAIL
- [ ] **Step 3: 实现** snapshots.py(发版全程事务)
- [ ] **Step 4: 跑过 + 后端全量回归** `uv run pytest -v` 全绿
- [ ] **Step 5: Commit** `feat:发版——自定义版本号/变更记录/Term 重建/回退`

---

### Task 8: 前端骨架与项目总览

**Files:**
- Create: `web/src/{main.ts,router.ts,App.vue,api.ts,style.css}`、`web/src/components/SideBar.vue`、`web/src/views/ProjectsView.vue`
- Modify: `web/vite.config.ts`(dev proxy `/api → http://127.0.0.1:8000`,`server.proxy` 配 `no-proxy` 直连);删除 v1 旧 src 其余文件

**Interfaces:**
- Produces: 路由 `#/projects`、`#/p/:pid/(materials|review|versions)`;`api.ts` 导出 typed fetch 封装(后续页共用);SideBar 消费 `GET /projects`(项目树+子导航+待答徽标)。

- [ ] **Step 1: 实现**(样式全部取自原型 `:root` token 与侧栏/表格 CSS,中文注释)
- [ ] **Step 2: 真机验收**——起后端+`npx vite dev`,强刷走查:项目列表/新建(空名前端拦截)/编辑/输名归档/恢复/归档 tab,对照原型逐项
- [ ] **Step 3: Commit** `feat:前端骨架——侧栏项目树与项目总览页`

---

### Task 9: 材料页

**Files:**
- Create: `web/src/views/MaterialsView.vue`、`web/src/components/MatDrawer.vue`

- [ ] **Step 1: 实现**——上传区(拖拽+点击,响应 409 时 toast「已存在」指向原记录)、表格、行点击 drawer 展 parsed_text
- [ ] **Step 2: 真机验收**——PDF/图片各传一份,解析状态流转,对照原型
- [ ] **Step 3: Commit** `feat:材料页——上传/去重提示/解析预览`

---

### Task 10: 文档评审页(照原型,核心)

**Files:**
- Create: `web/src/views/ReviewView.vue`、`web/src/components/rev/{RevToolbar.vue,MoreMenu.vue,ChapterTree.vue,DocPaper.vue,RulePopover.vue,AnnotationRail.vue,AnnotationCard.vue,FocusMode.vue}`

**Interfaces:**
- Consumes: `GET doc/draft`+`GET questions?status=pending`+`POST questions/{id}/answer`;组件 props/emits 由 ReviewView 统一编排。
- 实现纪律(原型踩坑):输入类作答局部更新保焦点;列表重渲染后节点先取引用再挂事件(Vue 响应式天然规避,但批注卡局部更新逻辑照此思路)。

- [ ] **Step 1: 实现三栏骨架**——固定视口独立滚动、页宽三档(MoreMenu 图形化选项)、工具条(草案状态+摘要+定稿发版+⋮);**无 reviewing 草案时渲染当前基线只读态**(复用三栏,工具条隐藏发版钮,版本下拉可切)
- [ ] **Step 2: 实现正文渲染**——章节/批注高亮(未答琥珀、已答绿)/规则编号 popover(violation+quote+材料 hash)/章节缺口红字关联批注
- [ ] **Step 3: 实现批注栏**——按章节分组、默认折叠(问题首行+编号·类型 meta)、展开作答四题型控件、定位按钮双向联动滚动高亮、答完自动收起转绿+正文同步、重新作答、对照/逐条两模式
- [ ] **Step 4: 实现定稿发版弹窗**——自定义版本号(默认建议值、重复 409 前端提示)+发版说明+未处理批注数提示;确认后跳版本页
- [ ] **Step 5: 真机验收**——对照原型逐屏:三栏滚动隔离、批注全交互、页宽、模式切换、发版流转
- [ ] **Step 6: Commit** `feat:文档评审页——批注式评审照原型还原`

---

### Task 11: 版本页

**Files:**
- Create: `web/src/views/VersionsView.vue`、`web/src/components/ChangeRow.vue`

- [ ] **Step 1: 实现**——时间线(草案评审中+历史定稿)、变更 diff 展开(新增/修改/作废+reason+approver)、「回退到此版」确认弹窗
- [ ] **Step 2: 真机验收**——发一版看 diff,回退后基线切换,对照原型
- [ ] **Step 3: Commit** `feat:版本页——时间线/变更 diff/回退`

---

### Task 12: skill 对接与端到端验收

**Files:**
- Modify: `.agents/skills/req-organize/SKILL.md`(增补「平台对接」章节:五+二接口清单与调用顺序、校验报告处理纪律、断点续跑约定、payload 与 DocPayload 对齐)、`README.md`(架构图与启动说明 v2 化)、`docs/requirements.md`(头部标注 v2 基线指向)

- [ ] **Step 1: 增补 skill 平台对接章节**(接口以 Task5/6/7 实测路由为准)
- [ ] **Step 2: 端到端验收(design §2 Goals)**——`server/data/raw-backup/` 多模态原始材料:建项目→上传→agent 按 req-organize 加工(真实会话执行)→draft 过闸(至少触发一次硬错误修正重交与一次软警告转批注)→平台批注评审作答→agent 取答案收敛重交→人自定义号发版→版本页核对 ChangeLog/diff→回退演练;全程人只在闸门
- [ ] **Step 3: 全量回归**——`uv run pytest -v` 全绿;前端真机四页走查
- [ ] **Step 4: Commit** `feat:v2 M1 端到端闭环——skill 对接与验收`

---

## 执行完检查单(收尾)

- [ ] `openspec validate quos-v2-rebuild` 通过;specs 与实现无冲突(发现即同步)
- [ ] 变更记录:`git log --oneline` 每任务一 commit
- [ ] 分支 `feature/quos-v2-rebuild` 未合并;合并方式等用户指示(squash 单条)
