# req-onepager（需求一页纸）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 需求一页纸三件套——独立轻量 skill `req-onepager`（成稿 md → 画像式一页纸 md）、平台伴生存储与 API（`one_pager_md` 随 draft/version 生命周期）、评审页独立渲染入口（含点卡跳正文）。

**Architecture:** 生成侧新 skill 一次提炼（不做评审循环）；平台侧 `one_pager_md` 为 draft/version 表独立列（不入 DocPayload），finalize 时从草案复制进 version，GET draft/baseline 带出；前端新增纯函数解析器 + OnePager.vue 按固定骨架渲染，评审页工具条入口，文档区在 DocPaper↔OnePager 间切换。

**Tech Stack:** FastAPI + SQLModel/SQLite（server，uv）；Vue 3 + vitest（web，零新增依赖）；skill 为纯 markdown。

**Spec:** `docs/superpowers/specs/2026-10-19-req-onepager-design.md`（设计含骨架语法与提炼纪律，本计划与之冲突时以设计为准）；视觉基准 `web/prototype/onepager-r1.html`（R3）。

## Global Constraints

- API 不破坏既有端点/请求响应结构/状态码；错误用 HTTP 语义（422 校验 / 404 / 409）。
- 接口改动同次同步 `docs/api.md`；CLI 改动同次同步 `server/app/cli.py` + `docs/quos-agent-api.md`「CLI 调用」节（根 AGENTS.md 规则）。
- web 零新增依赖；组件 ≤500 行；中文注释；新组件中文文案。
- 后端测试 `cd server && uv run pytest tests/test_onepager.py -v`；前端测试 `cd web && npx vitest run`；真机验收 localhost 绕代理。
- `one_pager_md` 上限 65536 字符（`ONE_PAGER_MAX`），超限 422 `{"code": "ONE_PAGER_TOO_LARGE"}`。
- 覆盖语义：重导/重交不带 `one_pager_md` → 新草案该列为 null（伴生物随文档版本走，防陈旧画像）。

## Review Focus

1. **重导清空**：带一页纸导入后，再不带 `one_pager_md` 重导同项目 → GET draft 的 `one_pager_md` 为 null（防新旧不一致）。测试钉在 Task 2。
2. **超长拒收**：`one_pager_md` 塞入 >64KB → 422 拒收，草案不入库。测试钉在 Task 2。
3. **骨架不合式 md**：缺节/乱序/未知行/全角标点变体 → 解析器不抛异常，缺什么不渲染什么（容错不白屏）。测试钉在 Task 3。
4. **〔正文 N〕章号不存在**（skill 写错或文档改版）→ 卡仍渲染、跳转禁用。钉在 Task 3（解析保留原文）+ Task 4 真机。
5. **finalize 后入口不消失**：定稿切到基线态，入口与内容仍可用（数据走 version 行）。钉在 Task 2 测试 + Task 4 真机。

---

### Task 1: skill `req-onepager`

**Files:**
- Create: `.agents/skills/req-onepager/SKILL.md`
- Create: `docs/reqdoc-multimodal-onepager.md`（实测产物，兼 Task 4 真机 fixture）

**Interfaces:**
- Consumes: `docs/reqdoc-multimodal.md`（v4 成稿）、设计文档骨架与纪律。
- Produces: skill 可被任意 agent 按路径加载执行；实测产物 md 遵守 Task 3 定义的骨架语法（H1/`>` meta/`**K**：V` 头行/`## 核心链路`〔人工〕标注/`## 能力速览` 两组卡 `**名**（角色）〔正文 N〕：叙述`/`## 场景速览`/`## 待裁事项`）。

- [ ] **Step 1: 写 SKILL.md**

frontmatter（name/description 简述「成稿需求文档 → 画像式一页纸，独立轻量，一次提炼」）。正文从设计文档移植三块：①固定骨架（含精确语法——〔人工〕尾缀、（角色）、〔正文 N 或 N-M〕）；②提炼纪律（画像优先/卡≠章节概要按叙事重组主线+支撑/精炼叙述参数细节不进卡/每句有依据限定词不丢/标识符逐字/数字如实/【AI 推测】/高亮 `**粗体**`）；③输入输出约定（输入=过完 req-review 门的成稿 md；输出=一页纸 md 文件）。单文件，无流程编排、无评审循环。

- [ ] **Step 2: 派独立子代理实测**

Agent(general-purpose)：读 `.agents/skills/req-onepager/SKILL.md` + `docs/reqdoc-multimodal.md`，按 skill 产出一页纸，写入 `docs/reqdoc-multimodal-onepager.md`。子代理不读设计文档（测 skill 自足性）。

- [ ] **Step 3: 校验产物**

核对清单：骨架六节齐全且语法匹配 Task 3 定义；卡 2~3 句叙述、无阈值数字/错误码/Qn 残留；能力卡重组为「主线/支撑」两组且〔正文 N〕与 v4 章号对应（合并卡给范围）；待裁 7·7·5 与 v4 问题清单一致；【AI 推测】标注位保留；高亮 `**` 成对。不合格项修 SKILL.md 措辞后重跑 Step 2。

- [ ] **Step 4: 盲测——只看一页纸能否建立正确画像（用户加的硬验收）**

派 general-purpose 子代理：仅给 `docs/reqdoc-multimodal-onepager.md` 路径，明确禁止读取需求原文、素材、skill、任何项目文档与全局记忆；任务=读完总结梳理「这个需求大概是什么样的」（这是什么/给谁/怎么工作/主线/支撑/边界/要裁什么）。拿子代理的总结对照 `docs/reqdoc-multimodal.md` 核对：主线与分工原则是否正确、能力理解有无偏差、边界有无读错。**看不明白或总结错误 → 一页纸不合格**，定位是 skill 提炼问题还是骨架表达问题，修改后重跑 Step 2-4，直到盲测通过。

- [ ] **Step 5: Commit**

```bash
git add .agents/skills/req-onepager/SKILL.md docs/reqdoc-multimodal-onepager.md
git commit -m "feat：req-onepager skill——成稿需求文档画像式一页纸(主线/支撑叙事重组,精炼叙述,参数细节不进卡)"
```

### Task 2: server 契约——存储、端点、CLI

**Files:**
- Modify: `server/app/models.py:40-63`（DocDraft/DocVersion 各加一列）
- Modify: `server/app/db.py:21-28`（get_engine 建表后幂等补列）
- Modify: `server/app/api/doc.py`（ImportBody/import_draft/submit_draft/_persist_draft/get_draft/get_baseline）
- Modify: `server/app/services/snapshots.py:87-112`（finalize 复制）
- Modify: `server/app/cli.py:82-87,115-121`（import-draft 加 --one-pager）
- Modify: `docs/api.md`、`docs/quos-agent-api.md`
- Test: `server/tests/test_onepager.py`

**Interfaces:**
- Consumes: 现有 `_persist_draft(db, pid, payload, report=None) -> dict`、`snapshots.finalize(...) -> DocVersion`。
- Produces:
  - `DocDraft.one_pager_md: str | None`、`DocVersion.one_pager_md: str | None`（均 `SF(default=None, nullable=True)`）
  - `_persist_draft(db, pid, payload, report=None, one_pager_md: str | None = None)`
  - `ImportBody.one_pager_md: str | None = None`
  - GET `/api/v1/projects/{pid}/doc/draft` 响应增 `"one_pager_md": str | null`（无草案 `{"empty": true}` 不变）
  - GET `/api/v1/projects/{pid}/doc/baseline` 响应增 `"one_pager_md": str | null`（取 version 行；empty 不变）
  - CLI `import-draft --one-pager <文件路径>`（读文件文本进 body）

- [ ] **Step 1: 写失败测试** `server/tests/test_onepager.py`（沿用现有 conftest 的 client/tmp db 模式）

五个用例：①import 带 `one_pager_md` → GET draft 带出原文；②同项目再次 import 不带 → GET draft 为 null（重导清空）；③`submit_draft`（POST /doc/draft）body 混入 `one_pager_md` → 落库带出；④带一页纸导入 → finalize → GET baseline 的 `one_pager_md` 来自 version 行且与草案一致；⑤64KB+1 字符 → 422 且 detail 含 `ONE_PAGER_TOO_LARGE`，GET draft 仍无新草案。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_onepager.py -v`；Expected: FAIL（字段/行为不存在）。

- [ ] **Step 3: 实现**

models 两表加列；db.py 在 `create_all` 后对两表跑 `PRAGMA table_info` 检查缺列则 `ALTER TABLE ... ADD COLUMN one_pager_md TEXT`（幂等 shim）；doc.py：ImportBody 加字段、import_draft 与 submit_draft（body 为裸 dict，`body.pop("one_pager_md", None)` 取出并做长度校验）传入 `_persist_draft` 新参数（import 与手工提交同闸门）；get_draft/get_baseline 响应各加一键；snapshots.finalize 建 DocVersion 时 `one_pager_md=draft.one_pager_md`。CLI import-draft 加 `--one-pager` 参数与 dispatch 分支。

- [ ] **Step 4: 跑测试确认通过 + 定向回归**

Run: `cd server && uv run pytest tests/test_onepager.py tests/test_md_import.py -v`；Expected: 全 PASS。

- [ ] **Step 5: 同步文档**

`docs/api.md`：draft/import、draft(POST)、draft(GET)、baseline(GET) 四处加 `one_pager_md` 可选字段/响应键与覆盖语义、64KB 上限；`docs/quos-agent-api.md` CLI 表 import-draft 行加 `--one-pager`。

- [ ] **Step 6: Commit**

```bash
git add server/app/models.py server/app/db.py server/app/api/doc.py server/app/services/snapshots.py server/app/cli.py server/tests/test_onepager.py docs/api.md docs/quos-agent-api.md
git commit -m "feat：one_pager_md 伴生契约——draft/version 独立列(幂等补列),import/submit 可选携带,finalize 复制,baseline/draft 带出,64KB 上限,重导覆盖清空;CLI --one-pager;api.md 同步"
```

### Task 3: web 解析器 + OnePager 组件

**Files:**
- Create: `web/src/utils/onepager.ts`（纯函数解析器 + 类型）
- Create: `web/src/components/rev/OnePager.vue`（渲染，样式移植原型 R3）
- Test: `web/tests/onepager.test.ts`（vitest 首例）

**Interfaces:**
- Consumes: Task 1 定义的骨架语法。
- Produces:
  ```ts
  interface OneCard { name: string; role: string; chapters: string; segs: Array<{ t: string; hl: boolean }> }
  interface OnePagerDoc {
    title: string; meta: string[];
    head: Array<{ k: string; v: string }>;
    flow: Array<{ label: string; human: boolean }>; flowNote: string;
    groups: Array<{ title: string; cards: OneCard[] }>;
    scenarios: string[]; todo: { x: number; y: number; z: number };
  }
  export function parseOnePager(md: string): OnePagerDoc
  ```
  `OnePager.vue`：props `{ doc: OnePagerDoc }`；emits `{ jump: [chapters: string] }`；卡色由卡片序号对内置色板循环注入 `--c`。

- [ ] **Step 1: 写失败测试** `web/tests/onepager.test.ts`

解析器用例：完整骨架样例逐字段断言（title 去「· 需求一页纸」后缀、〔人工〕剥离置 human、`**名**（角色）〔正文 5-6〕：叙述` 分解、正文 `**粗体**` 切 segs 且 hl 位正确、场景按「、」分、todo 三数）；容错用例：缺「## 待裁事项」→ todo 为 0,0,0 不抛；未知节与未知行被忽略；全角变体（（角色）为半角括号时）角色为空串不炸。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run tests/onepager.test.ts`；Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `parseOnePager`**

逐行状态机：H1 → title；连续 `> ` → meta；`**K**：V` 行 → head；`## 核心链路` 后首个含 `→` 行按箭头切节点（剥 `〔人工〕`），其余非空行为 flowNote；`### X` 开组、组内段落正则 `^\*\*(.+?)\*\*（(.*?)）〔正文\s*(.*?)〕：(.*)$` 成卡（角色/章号允许空）；`## 场景速览` 下行按 、，切；`## 待裁事项` 正则抽 `送裁 (\d+).*确认 (\d+).*填空 (\d+)`；正文 segs 由 `**` 成对切分（不成对整段低亮处理，不抛）。

- [ ] **Step 4: 实现 OnePager.vue**

结构照原型 R3：头部卡（title+meta+head 四行）→ 链路卡（节点 pill，human 琥珀）→ 两组卡网格（左缘色条+卡头 name/role/「正文 ↗」+叙述段，`**` hl 渲染为域色 b，esc 转义）→ 场景 chips → 待裁统计块。点击卡或「正文 ↗」emit `jump(card.chapters)`。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd web && npx vitest run`；Expected: PASS。另用 node 或 vitest 附加一条组件挂载冒烟（mount(OnePager) 渲染出组/卡节点数）。

- [ ] **Step 6: Commit**

```bash
git add web/src/utils/onepager.ts web/src/components/rev/OnePager.vue web/tests/onepager.test.ts
git commit -m "feat：一页纸前端——parseOnePager 骨架解析(容错不抛)+OnePager.vue 画像式渲染(R3 样式,点卡 emit jump)"
```

### Task 4: 评审页入口 + 跳转正文

**Files:**
- Modify: `web/src/api.ts:71-72`（draft/baseline 响应类型加 `one_pager_md?: string | null`）
- Modify: `web/src/views/ReviewView.vue`（工具条入口 + 视图切换 + 跳章处理）

**Interfaces:**
- Consumes: Task 3 的 `parseOnePager`/`OnePager.vue`；DocPaper 既有 `jump` 滚动处理；`flattenChapters`（utils/chapters）。
- Produces: 评审页 `view: 'doc' | 'onepager'` 状态；`onepagerJump(chapters: string)`——取章号（范围取首数），在 flattenChapters 中找 `no === N` 或 `no.startsWith(N + '.')` 的首章，命中则切回 doc 视图滚动至该章并复用现有关联高亮，未命中则不跳（跳转禁用态在 OnePager 侧由可选 prop `resolve` 提供，简单起见：未命中静默不跳）。

- [ ] **Step 1: 实现入口与切换**

ReviewView 加载 draft/baseline 后保存 `onepagerMd = draft.one_pager_md ?? baseline.one_pager_md ?? null`；工具条（`.rev-toolbar`）加「一页纸」按钮（`onepagerMd` 非空才渲染，title 无则不显示）；点击切换 `view`，onepager 视图下文档区渲染 `<OnePager :doc="parseOnePager(onepagerMd)" @jump="onepagerJump" />`（DocPaper 隐藏、批注栏保留只读态可简化为隐藏批注交互），提供返回按钮切回。

- [ ] **Step 2: 跳章实现**

`onepagerJump` 按 Interfaces 定义实现；章定位复用 DocPaper jump 的既有滚动函数。

- [ ] **Step 3: 真机验收**

`cd server && uv run uvicorn app.main:app --port 8000` + `cd web && QUOS_API=http://127.0.0.1:8000 npx vite`（绕代理）。POST import `docs/reqdoc-multimodal.md` + `--one-pager docs/reqdoc-multimodal-onepager.md` 到测试项目 → 验收：①入口出现且渲染完整（对照原型 R3）；②点「结构化抽取与发布」卡 → 切回正文并滚到对应章；③伪造 `〔正文 99〕` 重导 → 点卡不跳不报错；④finalize 后基线态入口仍可用；⑤不带 one-pager 重导 → 入口消失。

- [ ] **Step 4: Commit**

```bash
git add web/src/api.ts web/src/views/ReviewView.vue
git commit -m "feat：评审页一页纸入口——draft/baseline 任一带 one_pager_md 即显示,文档区双视图切换,点卡按〔正文 N〕跳转对应章(未命中禁跳)"
```
