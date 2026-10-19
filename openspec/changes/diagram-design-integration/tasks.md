# diagram-design 单轨图源集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** QuOS 图源从 mermaid 单轨切换为 diagram-design 自包含 HTML——agent 交付「md（只含图引用）+ figures/ 图文件集」，导入时图收进 diagram 块，前端 sandbox 渲染，mermaid 全链路退役。

**Architecture:** 产出层分离、存储层内嵌：md 的整行 `![意图](figures/x.html)` 引用解析为 diagram 块（text=HTML 全文），payload JSON 快照冻结图版本。校验硬软分流：HTML 形态结构非法 422，非 HTML 形态（存量 mermaid）软警告放行。前端 iframe sandbox（无 allow-scripts）渲染。

**Tech Stack:** Python FastAPI（multipart UploadFile）· Vue3 + vitest · vendor 自 skill 的 self_check（纯 stdlib）

**Spec:** `openspec/changes/diagram-design-integration/design.md` + 同目录 `proposal.md`、`specs/doc-pipeline/spec.md`、`specs/web-workbench/spec.md`（执行者需同读）

## Global Constraints

- 围栏语言仅识别现状 `mermaid`（照旧入 diagram 块）；**不新增任何围栏分支**（四反引号方案已作废）。
- 图引用唯一合法形态：独立整行 `![alt](figures/<kebab-slug>.html)`，前后仅空白；其余位置出现 `.html` 图片引用一律硬错误。
- HTML 形态判别：text 含 `<svg` 或 `<!DOCTYPE html`（大小写不敏感）。
- 硬项（422）：引用文件缺失、引用位置非法、ASCII 盒子图（维持）、HTML 图缺 title/desc、含 `<script`、含 `on\w+=` 事件属性、含外链资源（豁免 fonts.googleapis.com / fonts.gstatic.com 的 `<link>`）、内容越界 viewBox。
- 软项（不阻塞）：diagram 块非 HTML 形态（存量 mermaid）、提交了未被引用的图文件。
- 错误码族：`FORMAT_CONTRACT`（沿用）、`DIAGRAM_CHECK`（新，HTML 结构非法）；软警告文案统一「图源已单轨为 diagram-design，请重画」。
- Google Fonts `<link>` 是合法图内容的一部分，不得被外链检查误杀。
- mermaid_check.py 与 web 的 mermaid 依赖最终必须删除（不留死代码）。
- Commit 格式 `<type>：<描述>`；不修改无关代码；接口文档同一次改动同步（api.md / quos-agent-api.md / cli.py）。

## Review Focus

- md 引用出现在表格单元格 `| ![x](figures/y.html) |` → 422 带位置，而非静默丢图（Task 2 测试）。
- md 引用文件缺失 → 422，而非 diagram 块空 text 入库（Task 2/3 测试）。
- 存量 mermaid 图的旧基线重提（draft 直传）→ 软警告放行可迭代，而非硬拒收锁死项目（Task 3 测试）。
- 图 HTML 带 Google Fonts link → 通过外链检查（Task 1 测试）。
- iframe 渲染的图源含 `<script>` → 校验层已拒收（双保险的校验侧被测过）（Task 1/3 测试）。

---

### Task 1: diagram_check 服务（vendor + 适配）

**Files:**
- Create: `server/app/services/diagram_check.py`
- Test: `server/tests/test_diagram_check.py`

**Interfaces:**
- Consumes: 无（纯函数；基于 skill 的 `~/.agents/skills/diagram-design/scripts/self_check.py` 算法改写，不 import）
- Produces:
  - `is_html_form(text: str) -> bool`
  - `check_diagram(text: str) -> list[str]` — 空列表=通过；每条为错误明细字符串（含失败项名）

- [ ] **Step 1: 写失败测试**

```python
from app.services.diagram_check import check_diagram, is_html_form

MINIMAL = '''<!DOCTYPE html><html><body><svg viewBox="0 0 100 50" role="img"
 aria-labelledby="t-title t-desc"><title id="t-title">T</title><desc id="t-desc">D</desc>
<rect width="100" height="50" fill="#f5f5f5"/></svg></body></html>'''

def test_is_html_form():
    assert is_html_form(MINIMAL)
    assert is_html_form('<svg viewBox="0 0 1 1"><title>t</title></svg>')
    assert not is_html_form('flowchart TD\nA-->B')
    assert not is_html_form('')

def test_minimal_passes():
    assert check_diagram(MINIMAL) == []

def test_missing_title_desc():
    bad = MINIMAL.replace('<title id="t-title">T</title><desc id="t-desc">D</desc>', '')
    errs = check_diagram(bad)
    assert any('title' in e or 'desc' in e for e in errs)

def test_script_rejected():
    errs = check_diagram(MINIMAL.replace('</svg>', '<script>alert(1)</script></svg>'))
    assert any('script' in e for e in errs)

def test_event_attr_rejected():
    errs = check_diagram(MINIMAL.replace('<rect ', '<rect onload="x()" '))
    assert any('on*' in e or '事件' in e for e in errs)

def test_google_fonts_link_allowed_but_other_external_rejected():
    ok = MINIMAL.replace('<body>', '<head><link href="https://fonts.googleapis.com/css2?family=Geist" rel="stylesheet"></head><body>')
    assert check_diagram(ok) == []
    bad = ok.replace('fonts.googleapis.com/css2?family=Geist', 'evil.example.com/x.css')
    assert any('外链' in e for e in check_diagram(bad))

def test_bare_title_id_rejected():
    errs = check_diagram(MINIMAL.replace('id="t-title"', 'id="title"'))
    assert errs  # 裸 title/desc id 违反可访问契约
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_diagram_check.py -v`
Expected: FAIL（ModuleNotFoundError / ImportError）

- [ ] **Step 3: 实现 `diagram_check.py`**

参考 skill self_check.py 的检查算法（title/desc 契约、viewBox 越界），字符串接口重写，纯 stdlib（re + html.parser 或 ET）。检查顺序：`<script` 标签 → `on\w+=` 事件属性 → 外链资源（`(?:src|href)="https?://..."` 豁免 fonts.googleapis.com/fonts.gstatic.com）→ `<title>`/`<desc>` 存在且 id 非裸 `title`/`desc` → viewBox 越界（元素坐标超出 viewBox 声明范围）。头部注释注明改写自 skill（MIT, cathrynlavery/diagram-design）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_diagram_check.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/services/diagram_check.py server/tests/test_diagram_check.py
git commit -m "feat：diagram_check HTML 图结构校验服务（vendor 自 diagram-design self_check）"
```

---

### Task 2: md_import 图引用解析与闭合校验

**Files:**
- Modify: `server/app/services/md_import.py`（md_to_payload 主循环 L154-231、detect_format_issues L245-270）
- Test: `server/tests/test_md_import.py`（扩展）

**Interfaces:**
- Consumes: 无（Task 1 的 is_html_form 此处不用——分流在 Task 3 的端点层）
- Produces:
  - `md_to_payload(md, materials, rules_meta=None, figures: dict[str, str] | None = None) -> tuple[DocPayload, list[dict]]`（figures key 为引用路径如 `figures/main-flow.html`）
  - `detect_format_issues(md: str, figures: set[str] | None = None) -> list[str]`（返回硬错误；新增图引用类）
  - `detect_format_soft(md: str, figures: set[str] | None = None) -> list[str]`（返回软警告；未引用文件）

- [ ] **Step 1: 写失败测试**（追加到 test_md_import.py；复用现有测试的 payload 构造方式）

```python
FIG = '<!DOCTYPE html><html><body><svg viewBox="0 0 4 4"><title id="a-title">a</title></svg></body></html>'

def test_standalone_figure_ref_becomes_diagram_block():
    md = '## 1 章节\n\n正文段。\n\n![主链路](figures/main-flow.html)\n'
    payload, _ = md_to_payload(md, {}, figures={'figures/main-flow.html': FIG})
    blocks = payload.chapters[0].blocks
    assert blocks[-1].type == 'diagram' and blocks[-1].text == FIG

def test_missing_figure_file_is_hard_error():
    md = '![主链路](figures/absent.html)\n'
    assert any('absent' in w for w in detect_format_issues(md, figures=set()))

def test_inline_ref_position_is_hard_error():
    for md in ['见下图：![x](figures/a.html)\n', '- ![x](figures/a.html)\n',
               '| a | ![x](figures/a.html) |\n|---|---|\n', '> ![x](figures/a.html)\n']:
        assert any('独立成行' in w for w in detect_format_issues(md, figures={'figures/a.html'})), md

def test_unreferenced_figure_is_soft_warning():
    assert detect_format_soft('无引用正文', figures={'figures/orphan.html'}) != []
    assert detect_format_soft('![x](figures/used.html)', figures={'figures/used.html'}) == []

def test_ref_inside_fence_not_scanned():
    md = '```text\n![x](figures/a.html)\n```\n'
    assert detect_format_issues(md, figures=set()) == []

def test_mermaid_fence_still_diagram_block():
    payload, _ = md_to_payload('## 1 章\n```mermaid\nflowchart TD\nA-->B\n```\n', {})
    assert payload.chapters[0].blocks[-1].type == 'diagram'
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_md_import.py -v -k figure`
Expected: FAIL（figures 参数不存在 / 引用进 para）

- [ ] **Step 3: 实现**

md_to_payload 主循环：在列表分支（L224）之前加整行图引用判定（regex `^\s*!\[[^\]]*\]\(figures/[\w.-]+\.html\)\s*$`）→ `flush_para(); flush_table()` 后 `cur['blocks'].append({"type": "diagram", "text": figures.get(路径, '')})`。detect_format_issues：非围栏行若含 `!\[[^\]]*\]\(figures/[\w.-]+\.html\)` 且不匹配整行 regex → 硬错误（带行号与「图引用须独立成行」）；收集整行引用集与 figures 参数比对 → 缺失硬错误。detect_format_soft：figures 中未被引用的文件 → 软警告。detect_format_issues 删除 mermaid 括号规则（L256-260）；ASCII 盒子图条目（L261-262）维持。

- [ ] **Step 4: 跑测试确认通过（含存量回归）**

Run: `cd server && uv run pytest tests/test_md_import.py -v`
Expected: 全 PASS（存量用例不回归）

- [ ] **Step 5: Commit**

```bash
git add server/app/services/md_import.py server/tests/test_md_import.py
git commit -m "feat：md 图引用解析入 diagram 块+引用闭合与位置硬校验+未引用软警告"
```

---

### Task 3: 导入端点 multipart 与校验硬软分流

**Files:**
- Modify: `server/app/api/doc.py:81-147`（ImportBody 与 import_draft）、`server/app/services/validators.py:146`（diagram 块校验）、`server/app/models.py:141`（块类型注释：diagram 语义改自包含 HTML）
- Delete: `server/app/services/mermaid_check.py`
- Test: `server/tests/test_doc_api.py`、`server/tests/test_validators.py`

**Interfaces:**
- Consumes: Task 1 `is_html_form/check_diagram`；Task 2 `figures` 参数、`detect_format_soft`
- Produces: `POST /api/v1/projects/{pid}/doc/draft/import` multipart 契约——`md: file`、`figures: file[]`（可选，part 名 figures，filename 为 basename，服务端映射为 `figures/<filename>` 与 md 引用路径对齐）、`rules_meta: form(str JSON, 可选)`、`one_pager_md: form(str, 可选)`；`check_draft` 对 diagram 块：HTML 形态过 check_diagram（错→hard `DIAGRAM_CHECK`），非 HTML 形态→soft

- [ ] **Step 1: 写失败测试**

test_doc_api.py 追加（multipart 客户端方式参照现有测试基建 conftest）：

```python
def test_import_with_figures_renders_diagram(client, proj):  # 现有 fixture 风格
    files = [('figures', ('main-flow.html', b'<svg viewBox="0 0 4 4"><title id="a-title">a</title></svg>', 'text/html'))]
    r = client.post(f'/api/v1/projects/{proj.id}/doc/draft/import',
        data={'md': '## 1 章\n\n![主链路](figures/main-flow.html)\n'},
        files=files)
    assert r.status_code == 200

def test_import_missing_figure_422(client, proj):
    r = client.post(..., data={'md': '![x](figures/none.html)\n'}, files=[])
    assert r.status_code == 422 and any('none.html' in e['detail'] for e in r.json()['detail']['hard_errors'])

def test_import_legacy_mermaid_soft_not_hard(client, proj):
    r = client.post(..., data={'md': '## 1 章\n```mermaid\nflowchart TD\nA-->B\n```\n'}, files=[])
    assert r.status_code == 200
    assert any('diagram-design' in w for w in r.json()['report']['soft_warnings'])  # 键名按现有响应结构对齐
```

test_validators.py 追加：check_draft 对 diagram 块 HTML 形态含 script → hard `DIAGRAM_CHECK`；非 HTML 形态 → soft 含「重画」。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_doc_api.py tests/test_validators.py -v -k "import or diagram"`
Expected: FAIL（422 缺 figures 字段 / 校验不分流）

- [ ] **Step 3: 实现**

doc.py：ImportBody 删除，import_draft 改 `async def`，参数 `md: UploadFile = File(...), figures: list[UploadFile] = File(default=[]), rules_meta: str | None = Form(None), one_pager_md: str | None = Form(None)`；读文件集 `{f'figures/{f.filename}': f.file.read().decode() for f in figures}`；调用 `md_to_payload(md_text, materials, json.loads(rules_meta) if rules_meta else None, figures_map)`；hard 组装：`detect_format_issues(md_text, set(figures_map))` + 逐 diagram 块 `is_html_form` 时 `check_diagram` 错→`DIAGRAM_CHECK`；软：`detect_format_soft(...)` 与非 HTML 形态块 → 并入 `out` 的报告 soft_warnings（按现有响应结构对齐键名）。validators.py L146 diagram 校验：非空 + HTML 形态过 check_diagram（hard）/ 非 HTML 形态 soft。models.py L141 注释改为 `diagram(自包含 HTML 图源,diagram-design 产物,前端 sandbox 渲染)`。删 `from app.services.mermaid_check import check_mermaid` 与 `mermaid_check.py` 文件。

- [ ] **Step 4: 跑测试确认通过（含存量回归）**

Run: `cd server && uv run pytest tests/test_doc_api.py tests/test_validators.py tests/test_md_import.py tests/test_questions.py tests/test_finalize.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add -A server/app server/tests
git commit -m "feat：import 端点 multipart 化+图校验硬软分流+mermaid_check 退役"
```

---

### Task 4: CLI --figures 与接口文档同步

**Files:**
- Modify: `server/app/cli.py:82-84`（import-draft 子命令）、`docs/api.md`（import-draft 条目）、`docs/quos-agent-api.md`（CLI 表 import-draft 行）
- Test: `server/tests/test_cli.py`

**Interfaces:**
- Consumes: Task 3 的 multipart 端点
- Produces: `quos import-draft PID --md FILE [--figures DIR] [--meta FILE] [--one-pager FILE]`——DIR 内全部 .html 以 basename 为 `figures/<name>` key 上传

- [ ] **Step 1: 写失败测试**

test_cli.py 追加：`--figures` 指向含一个 .html 的临时目录 → 请求 multipart 含 figures part（按现有 test_cli 的请求桩方式断言 payload）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_cli.py -v -k figures`
Expected: FAIL（unrecognized argument）

- [ ] **Step 3: 实现**

cli.py 加 `--figures`（path，可选）；请求组装从 JSON body 改 multipart（httpx files/data），`--meta`/`--one-pager` 转 form 字段。同步 api.md（multipart 字段表、图引用契约、DIAGRAM_/FORMAT_ 422 明细、软警告项）与 quos-agent-api.md 命令表。

- [ ] **Step 4: 跑测试确认通过 + 真机 CLI 冒烟**

Run: `cd server && uv run pytest tests/test_cli.py -v && uv run python -m app.cli import-draft --help`
Expected: 测试全 PASS；help 显示 --figures

- [ ] **Step 5: Commit**

```bash
git add server/app/cli.py server/tests/test_cli.py docs/api.md docs/quos-agent-api.md
git commit -m "feat：CLI import-draft --figures+api.md/quos-agent-api.md multipart 契约同步"
```

---

### Task 5: 前端 sandbox 渲染与 mermaid 退役

**Files:**
- Modify: `web/src/components/rev/DiagramView.vue`（重写 script 与 template）、`web/package.json`
- Test: `web/tests/diagram.test.ts`（改写）

**Interfaces:**
- Consumes: DocPaper.vue 传入的 `source?: string`（text=HTML 或存量 mermaid）与 `flows?: string[]`（不变）
- Produces: 同名组件同 props——HTML 源 iframe 渲染；存量 mermaid 源码降级+重画提示；flows 流程条主路径

- [ ] **Step 1: 改写 diagram.test.ts 为失败测试**

断言：`source` 为 HTML（含 `<svg`）→ 渲染 iframe（`sandbox` 属性不含 `allow-scripts`、srcdoc 含源码）；`source` 为 mermaid 文本 → 显示「重画」提示与源码 pre；`flows` → 流程条节点渲染。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npm test -- diagram`
Expected: FAIL（现实现走 mermaid.render）

- [ ] **Step 3: 重写 DiagramView.vue**

`isHtml = computed(() => /<svg|<!DOCTYPE html/i.test(props.source ?? ''))`；HTML 分支：`<iframe :srcdoc="source" sandbox="allow-same-origin" style="width:100%;border:0" @load="自适应高(contentDocument.body.scrollHeight, clamp 上限 2000px)">`；mermaid 分支：mmd-degraded 提示（文案「存量 mermaid 图，待迭代重画为 diagram-design」）+ pre 源码；flows：现有 flowbox 为主路径。删除 mermaid import/initialize/render/竞态守卫/残留清理。`npm uninstall mermaid`。

- [ ] **Step 4: 跑测试确认通过 + 真机验收**

Run: `cd web && npm test && npm run build`
Expected: 全 PASS、构建通过。真机：起 5175 dev，导入带图草案（用 Task 3 测试同款 md+figure），评审页图 iframe 渲染正确、存量项目旧 mermaid 图降级显示源码+提示（浏览器强刷）。

- [ ] **Step 5: Commit**

```bash
git add web/src/components/rev/DiagramView.vue web/tests/diagram.test.ts web/package.json web/package-lock.json
git commit -m "feat：DiagramView sandbox iframe 渲染 HTML 图+存量降级+mermaid 依赖退役"
```

---

### Task 6: req-organize / req-review skill 改写

**Files:**
- Modify: `.agents/skills/req-organize/SKILL.md`（L49-51、L62-63 图纪律段+配套对接节）、`.agents/skills/req-review/SKILL.md`（R 组图判据段）

**Interfaces:**
- Consumes: design.md §6 的意图级三条约定
- Produces: 无代码接口；验收对照清单

- [ ] **Step 1: 改写 req-organize**

图纪律段替换为：主链路必须落图（`![图意图](figures/<kebab-slug>.html)` 整行引用）、引用约定（figures/ 目录、独立成行、只引 .html、违反会被平台 422）、产出物形态（md + figures/ 一并提交）；删除全部 mermaid 纪律（括号/保留字/两种图形态）。配套对接节加 diagram-design 依赖（安装命令）、调用方式（意图描述→skill 产 HTML→存 figures/）、无 skill 降级（线性链路）、皮肤与字体一句带过（默认皮肤、font link 追加 Noto Sans SC/Serif SC）。

- [ ] **Step 2: 改写 req-review**

R 组图判据：mermaid 语法类判据删除；新增「图引用未独立成行/引用文件缺失（平台会拒收，评审兜底提示）」「存量 mermaid 图→标记建议重画」。

- [ ] **Step 3: 验收对照**

grep 检查两文件无 `mermaid` 残留纪律（历史对照说明除外）；三条约定与 design.md §6 一致。

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/req-organize/SKILL.md .agents/skills/req-review/SKILL.md
git commit -m "docs：req-organize 图纪律收敛为意图级引用+req-review 图判据同步单轨"
```

---

### Task 7: 全链路验证与全量回归

**Files:**
- 无新增（验证任务）

**Interfaces:**
- Consumes: Task 1-6 全部产物
- Produces: 验证记录（附到本文件末尾）

- [ ] **Step 1: server 全量测试**

Run: `cd server && uv run pytest -q`
Expected: 全 PASS（原 98 项 + 新增）

- [ ] **Step 2: web 全量测试**

Run: `cd web && npm test`
Expected: 全 PASS

- [ ] **Step 3: 演示项目全链路重画**

起 8000+5175；用 diagram-design skill 重画演示项目（5175 项目 5）主链路图 → 组织 md（整行引用+figures/）→ CLI `import-draft --md --figures` → 校验过 → 评审页 iframe 真图渲染；再验证一版「引用缺失」被 422 的往返。

- [ ] **Step 4: Commit（如有验证期修正）**

```bash
git commit -m "fix：全链路验证修正（如有）"
```
