# 澄清池材料级回答（P1）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 澄清池支持材料级回答——补材料（文本/图片/pdf/docx）入证据池后自动 AI 重检全部待问问题，代答人工采纳后落账并联动规则核过。

**Architecture:** 材料即证据（带 `source:'clar'` 标记），澄清重检是新的后台 job（`clar-review`），复用现有 jobs 轮询与澄清池规则核过联动；runner 升级多模态（text+image parts），PDF 走 pypdf、图片走 Pillow 压缩后多模态直读。前端 AskDrawerV2 由 mock 转正式（V1 与预览开关移除）。

**Tech Stack:** FastAPI + Pydantic（server，uv 管理）、Vue3 + vitest（web）、DeepSeek V4.1-Flash（OpenAI 兼容多模态）、新依赖 pypdf + Pillow。

**Spec:** docs/specs/2026-09-29-clar-material-design.md（术语已统一：断言=规则、卡片=用户画像）

## Global Constraints

- 数据兼容：旧 `clarifications.json` 无新字段必须零迁移可加载（Pydantic 默认值兜底）；`st` 取值 `wait | answered | verified`
- 术语：代码/注释/UI 一律「规则」「用户画像」，不新出现「断言」「卡片」
- 依赖：仅新增 `pypdf`、`Pillow`（server，uv add）；web 零新依赖
- 护栏：附件 ≤10MB/份（前端拦）；重检单次图片 ≤5 张（422）、文本总量 ≤30k 字（截断并在 job label 注明）
- AI 产出=推测级：代答只写 `clar.ai` 待采纳，`st` 保持 `wait`；采纳才写 `ans`/`answer` 并触发规则核过联动
- 后端测试 `uv run pytest tests/ -q`（server 目录）；前端 `npx vitest run`（web 目录）；行数上限：组件/模块 500 行
- Commit 格式 `feat：`/`fix：` 等，技术名词保留英文（用户全局规则）

## 对 spec 的三处实现细化（已在 spec 语义内）

1. **`POST /clarifications/materials` 简化为前端组合**：复用既有 `POST /evidence`（raw body + X-Filename，加 `?source=clar`）逐份上传，再调新端点 `POST /clarifications/review {ev_ids}` 触发重检——避免为 multipart 引入 `python-multipart` 依赖，且天然覆盖 P2 的「池内既有材料重检」（review 端点不区分材料新旧）。
2. **`AiReview` 增加 `quote_ok: bool`**：服务端 quote substring 校验结果，前端据此标注「图片摘录·未校验」。
3. **图片统一压缩转 JPEG**（长边 1600px、quality 85），mime 恒 `image/jpeg`，简化 parts 构造。

## Review Focus

1. 旧 `clarifications.json` 无 `kind/ai/ans` 字段 → 加载默认 `choice/None/None` 不炸 → 测试在 Task 1
2. 扫描 PDF 提不出文本 → 提取 422 提示「转图片入池」而非静默乱码 → Task 3
3. choice 题代答不在 `opts` 内 → 视为未答出、不落 `ai` → Task 5
4. 代答 quote 非材料文本 substring → `conf` 降 `low` 且 `quote_ok=false`（图片材料免校验 `quote_ok=false`） → Task 5
5. open 题带 `idx` / choice 题缺 `idx` 或 `text` → 422 明确报错 → Task 6
6. 重检图片 >5 张 → 422；重检与批量任务互斥 → 409 → Task 5
7. 重检完成但全部题未答出 → job 正常结束、`ai` 全空、UI 不出现代答卡 → Task 5/9

---

### Task 1: 数据模型扩展（Evidence.source / Clarification.kind·ai·ans）

**Files:**
- Modify: `server/app/core/models.py`
- Modify: `server/app/storage/clarifications.py`
- Test: `server/tests/test_clar_material.py`（新建，本计划全部后端澄清测试集中于此）

**Interfaces:**
- Consumes: 现有 `Clarification`（no/q/opts/st/answer/ref）、`Evidence`
- Produces: `AiReview(answer,quote,ev_ids,conf,quote_ok)`、`ClarAnswer(kind,text,ev_ids)`、`Clarification.kind='choice'|'open'`、`Evidence.source`；存储层 `add(root, q, opts, ref=None, kind=None)`（opts 空 → kind 默认 'open'，否则 'choice'）、`set_ai(root, no, ai: dict|None)`

- [ ] **Step 1: 写失败测试**

```python
# server/tests/test_clar_material.py
import json
import pytest
from app.core.models import AiReview, ClarAnswer, Clarification, Evidence


def test_clarification_defaults_for_old_rows():
    """旧 JSON 行缺新字段：kind 兜底 choice，ai/ans 兜底 None"""
    c = Clarification(no=1, q="重试上限？", opts=["3次", "5次"], st="wait")
    assert c.kind == "choice" and c.ai is None and c.ans is None
    assert c.st == "wait"


def test_evidence_source_default_empty():
    e = Evidence(id="文本1", name="n", type="文本", reg="2026-09-29", path="")
    assert e.source == ""


@pytest.mark.asyncio
async def test_add_open_kind_when_opts_empty(tmp_path):
    from app.storage import clarifications as cl
    c = await cl.add(tmp_path, "退款审批阈值未说明，请补充", [], ref=None)
    assert c.kind == "open" and c.opts == []
    c2 = await cl.add(tmp_path, "冷却期多久？", ["7天", "30天"])
    assert c2.kind == "choice"


@pytest.mark.asyncio
async def test_set_ai_roundtrip(tmp_path):
    from app.storage import clarifications as cl
    await cl.add(tmp_path, "q", [])
    ai = {"answer": "答", "quote": "材料原文", "ev_ids": ["文本ABCD"], "conf": "high", "quote_ok": True}
    c = await cl.set_ai(tmp_path, 1, ai)
    assert c.ai == ai
    rows = json.loads((tmp_path / "clarifications.json").read_text("utf-8"))
    assert rows[0]["ai"]["quote"] == "材料原文"
    await cl.set_ai(tmp_path, 1, None)  # 忽略/采纳后清空
    assert (await cl.list_all(tmp_path))[0].ai is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_clar_material.py -q`
Expected: FAIL（`AiReview` ImportError / `set_ai` 不存在）

- [ ] **Step 3: 最小实现**

```python
# server/app/core/models.py 追加/修改
class Evidence(BaseModel):
    # ...既有字段不动...
    source: str = ""  # 'clar' = 澄清池补料入口；空 = 证据池入口


class AiReview(BaseModel):
    answer: str
    quote: str
    ev_ids: list[str] = []
    conf: str  # high | med | low
    quote_ok: bool = True


class ClarAnswer(BaseModel):
    kind: str  # 'opt' | 'text' | 'material'
    text: str
    ev_ids: list[str] = []


class Clarification(BaseModel):
    no: int
    q: str
    opts: list[str] = []
    kind: str = "choice"  # choice | open（opts 为空即 open；旧数据默认 choice）
    st: str = "wait"  # wait | answered | verified
    answer: str | None = None
    ref: str | None = None
    ai: AiReview | None = None
    ans: ClarAnswer | None = None
```

```python
# server/app/storage/clarifications.py：add 签名与 set_ai
async def add(root, q: str, opts: list[str], ref: str | None = None, kind: str | None = None) -> Clarification:
    rows = _load(root)
    row = {"no": max((r.get("no", 0) for r in rows), default=0) + 1,
           "q": q, "opts": list(opts),
           "kind": kind or ("open" if not opts else "choice"),
           "st": "wait", "answer": None, "ref": ref, "ai": None, "ans": None}
    rows.append(row)
    _save(root, rows)
    return Clarification(**row)


async def set_ai(root, no: int, ai: dict | None) -> Clarification:
    rows = _load(root)
    row = _find(rows, no)
    row["ai"] = ai
    _save(root, rows)
    return Clarification(**row)
```

注意：`_load` 现有构造 `Clarification(**r)`，旧行缺字段由 Pydantic 默认值兜底，零迁移。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_clar_material.py -q`
Expected: PASS（4 个）

- [ ] **Step 5: 回归 + commit**

Run: `uv run pytest tests/ -q`（全量，确认旧套件不受默认值改动影响——`models.py` 旧 `st: str = "open"` 默认值被改为 `"wait"`，若有测试依赖 "open" 需同步）
```bash
git add server/app/core/models.py server/app/storage/clarifications.py server/tests/test_clar_material.py
git commit -m "feat：澄清池数据模型扩展——kind/open 题型、AiReview 待采纳代答、ClarAnswer 结构化答案、Evidence.source 来源标记"
```

---

### Task 2: runner 多模态 + 新依赖（pypdf/Pillow）

**Files:**
- Modify: `server/app/ai/runner.py`
- Modify: `server/pyproject.toml`（uv add 生成）
- Test: `server/tests/test_runner.py`（追加）

**Interfaces:**
- Produces: `complete(task, variables, schema, images: list[bytes] | None = None)`——images 为 JPEG 字节列表；`_call(prompt, images)` 构造 `content: [{type:'text'},{type:'image_url',url:'data:image/jpeg;base64,…'}]`；无 images 时请求体与现状逐字节一致

- [ ] **Step 1: 写失败测试（追加到 test_runner.py）**

```python
async def test_call_with_images_builds_content_parts(monkeypatch):
    """带图片时 content 为 parts 数组：text part 在前，图片 base64 data URL 在后"""
    from app.ai import runner
    captured = {}

    async def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"rules": []}'}}]})

    monkeypatch.setattr(runner, "_transport", lambda: _Transport(handler))
    img = b"\xff\xd8fakejpeg"
    await runner._call("提示词", [img])
    content = captured["payload"]["messages"][0]["content"]
    assert isinstance(content, list) and content[0] == {"type": "text", "text": "提示词"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_call_without_images_keeps_plain_string(monkeypatch):
    from app.ai import runner
    captured = {}

    async def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"rules": []}'}}]})

    monkeypatch.setattr(runner, "_transport", lambda: _Transport(handler))
    await runner._call("纯文本")
    assert captured["payload"]["messages"][0]["content"] == "纯文本"
```

（`_Transport`/`httpx`/`json` 沿用该文件顶部既有 import 与测试基建；若该文件尚无 `_Transport` helper，按既有 mock transport 模式补一个 `httpx.MockTransport` 包装。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_runner.py -q`
Expected: FAIL（`_call() takes 1 positional argument but 2 given`）

- [ ] **Step 3: 实现**

```python
# server/app/ai/runner.py
import base64

async def _call(prompt: str, images: list[bytes] | None = None) -> str:
    content: list | str = [{"type": "text", "text": prompt}]
    if images:
        for b in images:
            url = f"data:image/jpeg;base64,{base64.b64encode(b).decode()}"
            content.append({"type": "image_url", "image_url": {"url": url}})
    else:
        content = prompt  # 纯文本任务保持原样（现状不变）
    # ...请求体中 "messages": [{"role": "user", "content": content}]...


async def complete(task: str, variables: dict, schema: type[BaseModel],
                   images: list[bytes] | None = None) -> BaseModel:
    prompt = (PROMPTS / f"{task}.md").read_text("utf-8").format(**variables)
    for attempt in (1, 2):
        try:
            return schema.model_validate_json(_strip_fence(await _call(prompt, images)))
        except Exception as e:
            if attempt == 2:
                raise AITaskError(task, f"输出校验失败: {str(e)[:200]}")
```

```bash
cd server && uv add pypdf Pillow
```

- [ ] **Step 4: 跑测试确认通过 + commit**

Run: `uv run pytest tests/test_runner.py tests/ -q`（全绿）
```bash
git add server/app/ai/runner.py server/pyproject.toml server/uv.lock server/tests/test_runner.py
git commit -m "feat：LLM runner 多模态——content parts（text+image_url），新增 pypdf/Pillow 依赖"
```

---

### Task 3: 材料取文升级（_evidence_parts + PDF + 截图解除限制）

**Files:**
- Modify: `server/app/api/router.py`（`_evidence_text` → `_evidence_parts`，extract/verify/scaffold 消费方切换）
- Create: `server/app/core/parse.py`（`pdf_text`/`shrink_image`，独立可测）
- Test: `server/tests/test_clar_material.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `complete(..., images=...)`（经 tasks 层透传）
- Produces: `parse.pdf_text(f: Path) -> str`（扫描件返回 `""`）、`parse.shrink_image(f: Path) -> bytes`（长边 ≤1600 JPEG）；router `_evidence_parts(root, ev) -> tuple[str, list[tuple[str, bytes]]]`——`(文本, [(mime, 字节)])`；`_evidence_text(root, evs) -> str` 保留为多证据拼接纯文本（verify 用，图片跳过文本侧）

- [ ] **Step 1: 写失败测试**

```python
# test_clar_material.py 追加
import io
from pathlib import Path


def test_pdf_text_roundtrip(tmp_path):
    from app.core import parse
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)  # 空白页：无文本
    f = tmp_path / "scan.pdf"
    f.write_bytes(io.BytesIO() .getvalue() if False else _pdf_bytes(w))
    assert parse.pdf_text(f) == ""  # 扫描件/无文本 → 空


def _pdf_bytes(w) -> bytes:
    import io
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_shrink_image_resizes_and_jpeg(tmp_path):
    from PIL import Image
    from app.core import parse
    f = tmp_path / "big.png"
    Image.new("RGB", (3200, 100), "red").save(f)
    out = parse.shrink_image(f)
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and img.width <= 1600 and img.height <= 1600
```

（pypdf 无文本 PDF 生成即验证「扫描件 → 空」路径；可再加一个带文本页的用例：`PdfWriter` + `PageObject` 文本注入较繁琐，允许用 `pdf_text` 对空串/异常路径的行为测试替代——最低要求：损坏 PDF 抛 `RuntimeError` 带中文提示而非裸异常。）

```python
def test_pdf_text_corrupt_raises_chinese(tmp_path):
    from app.core import parse
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"not a pdf")
    with pytest.raises(RuntimeError, match="PDF 解析失败"):
        parse.pdf_text(f)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_clar_material.py -q`
Expected: FAIL（`app.core.parse` 不存在）

- [ ] **Step 3: 实现**

```python
# server/app/core/parse.py
from io import BytesIO
from pathlib import Path

MAX_EDGE = 1600


def pdf_text(f: Path) -> str:
    """PDF 文本提取；无文本（扫描件）返回空串，损坏文件抛中文 RuntimeError"""
    try:
        from pypdf import PdfReader
        pages = [p.extract_text() or "" for p in PdfReader(str(f)).pages]
    except Exception as e:
        raise RuntimeError(f"PDF 解析失败: {e}") from e
    return "\n".join(t.strip() for t in pages if t.strip())


def shrink_image(f: Path) -> bytes:
    """图片压缩为长边 ≤1600 的 JPEG 字节（控多模态 token）"""
    from PIL import Image
    img = Image.open(f)
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_EDGE:
        r = MAX_EDGE / max(w, h)
        img = img.resize((int(w * r), int(h * r)))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()
```

router.py（替换 `_evidence_text` 单证据版本，消费方三处：extract / verify(拼接) / scaffold）：

```python
from app.core.parse import pdf_text, shrink_image

_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _evidence_parts(root, ev) -> tuple[str, list[tuple[str, bytes]]]:
    """(文本, [(mime, 图片字节)])；文本类只出文本，图片只出图，仓库/压缩包退回名称"""
    if ev.path:
        f = Path(root) / ev.path
        if f.exists():
            suf = f.suffix.lower()
            if suf == ".docx":
                return _docx_text(f), []
            if suf == ".pdf":
                return pdf_text(f), []
            if suf in _IMG_EXT:
                return "", [("image/jpeg", shrink_image(f))]
            return f.read_text("utf-8", errors="replace"), []
    return ev.name, []


async def _evidence_texts(root, evs=None) -> list[tuple[str, list[tuple[str, bytes]]]]:
    evs = evs if evs is not None else await evidence.list_all(root)
    return [_evidence_parts(root, e) for e in evs]
```

- extract 端点：删除 `if ev.type in ("截图", "压缩包")` 中截图的 422（保留压缩包 422）；`text, images = _evidence_parts(root, ev)`；`text` 为空且 `images` 为空 → 422 `"该材料没有可提取文本（扫描件请转图片入池）"`；调 `_ai_extract_one` 时把 images 透传进 `tasks.extract`（见 Task 4 签名）。
- verify（单点与 `_run_verify` 批处理）：材料文本拼接改为 `"\n\n".join(t for t, _ in parts)`（图片不参与文本侧——核验是文本比对，图片走提取产生的规则，不直接进核验材料，与 spec §4 一致）。
- scaffold：`texts = [t for e in ... for (t, imgs) in [_evidence_parts(root, e)] if t]` 且过滤 `e.type != "压缩包"`（截图不再排除）。

- [ ] **Step 4: 跑测试确认通过（含全量回归）**

Run: `uv run pytest tests/ -q`
Expected: 全绿（旧 test_api 对截图 422 的断言若存在需同步为「压缩包仍 422、截图走 parts」——grep `截图` 定位）

- [ ] **Step 5: commit**

```bash
git add server/app/core/parse.py server/app/api/router.py server/tests/test_clar_material.py
git commit -m "feat：材料取文升级——pypdf 提文、图片 Pillow 压缩、_evidence_parts 多模态部件、解除截图提取限制"
```

---

### Task 4: clar-review AI 任务（tasks + prompt + fake）

**Files:**
- Modify: `server/app/ai/tasks.py`、`server/app/ai/fake.py`
- Create: `server/app/ai/prompts/clar-review.md`
- Test: `server/tests/test_clar_material.py`（追加）

**Interfaces:**
- Consumes: Task 2 `complete(..., images)`
- Produces: `ClarReviewOut {results: list[ClarReviewItem]}`、`ClarReviewItem {no: int, answered: bool, answer: str = "", quote: str = "", conf: str = "med"}`；
  `async def clar_review(questions_text: str, materials_text: str, images: list[bytes] | None = None) -> ClarReviewOut`；
  `tasks.extract` 签名扩展为 `extract(evidence_content, evidence_type, tree_text, images=None)`（Task 3 消费方透传）

- [ ] **Step 1: 写失败测试**

```python
# test_clar_material.py 追加
@pytest.mark.asyncio
async def test_clar_review_task_parses(monkeypatch):
    from app.ai import tasks
    fake = tasks.ClarReviewOut(results=[
        {"no": 1, "answered": True, "answer": "7 天", "quote": "冷却期为7天", "conf": "high"},
        {"no": 2, "answered": False},
    ])

    async def mock(task, variables, schema, images=None):
        assert "冷却期" in variables["questions"] and "制度原文" in variables["materials"]
        assert images == [b"jpeg"]
        return fake

    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.clar_review("1. 冷却期多久？", "制度原文：冷却期为7天", [b"jpeg"])
    assert out.results[0].no == 1 and out.results[1].answered is False


@pytest.mark.asyncio
async def test_fake_clar_review_installed():
    from app.ai import fake, tasks
    fake.install()
    out = await tasks.clar_review("1. q", "材料", None)
    assert len(out.results) == 1 and out.results[0].answered is True
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/test_clar_material.py -q` → FAIL（`ClarReviewOut` 不存在）

- [ ] **Step 3: 实现**

```python
# tasks.py 追加
class ClarReviewItem(BaseModel):
    no: int
    answered: bool
    answer: str = ""
    quote: str = ""
    conf: str = "med"


class ClarReviewOut(BaseModel):
    results: list[ClarReviewItem]


async def clar_review(questions_text: str, materials_text: str,
                      images: list[bytes] | None = None) -> ClarReviewOut:
    return await complete(
        "clar-review",
        {"questions": questions_text, "materials": materials_text},
        ClarReviewOut,
        images=images,
    )
```

extract 透传图片：`async def extract(evidence_content, evidence_type, tree_text, images=None)` → `complete("extract", {...}, ExtractOut, images=images)`。

```markdown
<!-- server/app/ai/prompts/clar-review.md -->
你是一名需求澄清助手。下面是需求整理过程中攒下的待澄清问题，以及新补充的材料（文本与可能的图片）。请逐题判断材料是否直接回答了该问题。

## 待澄清问题

{questions}

## 补充材料

{materials}

## 判定要求

1. 只判定「材料是否直接回答」：能从材料原文找到明确依据才算 answered=true；材料没提到、需要推断、或答非所问一律 answered=false。
2. answered=true 时：answer 给出回答内容——选择题必须抄录选项原文（不能改写）；开放题用一句话归纳，不改事实。
3. quote 必须摘录材料中支撑该答案的原文片段（连续片段，逐字摘录，不超过 120 字）。图片材料摘录图中关键文字。
4. conf：high=原文明确写明；med=原文可推定但需组合两处；low=仅有间接线索。
5. 不臆造：材料没写的不要答。宁可全 false，不可编 quote。

## 输出

只输出一个 JSON 对象：

{{"results": [{{"no": 1, "answered": true, "answer": "…", "quote": "…", "conf": "high"}}, {{"no": 2, "answered": false}}]}}
```

```python
# fake.py 追加（并挂到 install()）
async def fake_clar_review(questions_text, materials_text, images=None):
    return tasks.ClarReviewOut(results=[{"no": 1, "answered": True, "answer": "假答案", "quote": "材料原文", "conf": "high"}])
```

- [ ] **Step 4: 过测 + commit**

Run: `uv run pytest tests/ -q`
```bash
git add server/app/ai/tasks.py server/app/ai/fake.py server/app/ai/prompts/clar-review.md server/tests/test_clar_material.py
git commit -m "feat：clar-review AI 任务——待问题×材料代答（answer/quote/conf），prompt 防臆造约束"
```

---

### Task 5: 澄清重检服务（review 端点 + job 编排 + 防幻觉校验）

**Files:**
- Modify: `server/app/api/router.py`
- Test: `server/tests/test_clar_material.py`（追加）

**Interfaces:**
- Consumes: Task 1 `set_ai`、Task 3 `_evidence_parts`、Task 4 `tasks.clar_review`；jobs 既有 `create/update/finish/running`
- Produces: `POST /clarifications/review` body `{"ev_ids": [...]}` → `{"job_id", "total"}`；kind=`clar-review` job；内部 `_apply_review(results, waits, text, ev_ids) -> int`（落库数，供测试）

- [ ] **Step 1: 写失败测试**

```python
# test_clar_material.py 追加（client/ensure_root/BASE 沿用 tests/test_api.py 的 fixture 模式，若本文件尚无则从 test_api.py 复制同名基建）
@pytest.mark.asyncio
async def test_review_validates_and_persists(tmp_path, monkeypatch):
    from app.api import router as R
    from app.core.models import Clarification
    from app.ai.tasks import ClarReviewItem
    waits = [Clarification(no=1, q="冷却期多久？", opts=["7天", "30天"], kind="choice"),
             Clarification(no=2, q="退款阈值？", opts=[], kind="open"),
             Clarification(no=3, q="未涉问题", opts=["a"])]
    results = [ClarReviewItem(no=1, answered=True, answer="90 天", quote="冷却期为7天", conf="high"),  # 选项不命中→丢弃
               ClarReviewItem(no=2, answered=True, answer="1万以下主管审批", quote="不在材料里的原文", conf="high"),  # quote 不命中→quote_ok False+conf low
               ClarReviewItem(no=99, answered=True, answer="x", quote="材料原文", conf="high")]  # 未知 no→丢弃
    n = R._apply_review(results, waits, "制度原文：冷却期为7天", ["E1"])
    assert n == 2  # no=1 被选项校验丢弃后仍落 2 条？否——期望 1 落库？见下方精确语义
```

精确语义（以此为准，测试按此写）：`_apply_review` 返回成功落库条数；no=1 因选项不命中改写为 `answered=False` **不落库**；no=2 quote 校验失败 → 落库但 `quote_ok=False, conf="low"`；no=99 丢弃。故断言：

```python
    assert n == 1
    ai = next(w for w in waits if w.no == 2).ai
    assert ai.quote_ok is False and ai.conf == "low"
    assert next(w for w in waits if w.no == 1).ai is None
```

端点级测试：

```python
@pytest.mark.asyncio
async def test_review_endpoint_creates_job(client, monkeypatch):
    """入池 1 份文本（source=clar）→ 发起重检 → job 建立、代答落 ai、st 仍 wait"""
    r = await client.post(f"{BASE}/evidence?source=clar", json={"raw": "制度原文：授信冷却期为7天"})
    ev_id = r.json()["id"]
    await client.post(f"{BASE}/rules/R1/ask") if False else None
    # 直接造一条 wait 题：通过既有 ask 链路太重，走 storage
    root = ensure_root("演示项目")
    from app.storage import clarifications as cl
    from app.core.models import Rule
    from app.storage import rules as rule_store
    rule_store.save(root, [Rule(id="R1", text="冷却期推测", src="s", conf="推测", verified=False)])
    c = await cl.add(root, "冷却期多久？", ["7天", "30天"], ref="R1")

    from app.ai.tasks import ClarReviewOut
    async def mock(qs, ms, images=None):
        return ClarReviewOut(results=[{"no": c.no, "answered": True, "answer": "7天", "quote": "授信冷却期为7天", "conf": "high"}])
    monkeypatch.setattr("app.ai.tasks.clar_review", mock)

    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": [ev_id]})
    assert r.status_code == 200 and "job_id" in r.json()
    import asyncio; await asyncio.sleep(0.1)  # create_task 事务让子弹飞
    rows = await cl.list_all(root)
    assert rows[0].ai is not None and rows[0].st == "wait"  # 待采纳：st 不动


@pytest.mark.asyncio
async def test_review_guards(client):
    """无待问→422；ev 不存在→404；运行中任务→409"""
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": ["NOPE"]})
    assert r.status_code == 404
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/test_clar_material.py -q` → FAIL（`_apply_review`/端点不存在）

- [ ] **Step 3: 实现（router.py 追加）**

```python
CLAR_BATCH = 20
REVIEW_TEXT_CAP = 30000
REVIEW_IMG_CAP = 5


class ReviewIn(BaseModel):
    ev_ids: list[str]


def _apply_review(results, waits, materials_text: str, ev_ids: list[str], has_image: bool) -> int:
    """防幻觉校验并落库：choice 未命中→丢弃；quote 非 substring→quote_ok=False+conf=low；no 未知→丢弃。返回落库数"""
    by_no = {w.no: w for w in waits}
    root_map = {}  # no -> Clarification 已在 by_no
    n = 0
    for r in results:
        w = by_no.get(r.no)
        if w is None or not r.answered:
            continue
        if w.kind == "choice" and r.answer not in w.opts:
            continue  # 选择题答案必须逐字命中选项
        quote_ok = bool(r.quote) and r.quote in materials_text if not has_image else False
        conf = r.conf if quote_ok else "low"
        w.ai = type(w).model_fields["ai"].annotation(answer=r.answer, quote=r.quote,
                                                      ev_ids=list(ev_ids), conf=conf, quote_ok=quote_ok)
        n += 1
    return n
```

（`AiReview` 直接 import 构造更清晰：`from app.core.models import AiReview` → `w.ai = AiReview(...)`——实现取后者。）

```python
@api_router.post("/clarifications/review")
async def review_clarifications(proj: str, body: ReviewIn):
    """澄清重检：选定材料 × 全部 wait 题 → AI 代答落 clar.ai（待人工采纳），进度走 GET /jobs"""
    root = _root(proj)
    if jobs.running():
        r = jobs.running()
        raise HTTPException(status_code=409, detail=f"已有任务进行中（{r['label']}，{r['cur']}/{r['total']}）")
    waits = [c for c in await clarifications.list_all(root) if c.st == "wait"]
    if not waits:
        raise HTTPException(status_code=422, detail="没有待问问题，无需重检")
    evs = []
    for eid in body.ev_ids:
        ev = await evidence.get(root, eid)
        if ev is None:
            raise HTTPException(status_code=404, detail=f"证据不存在: {eid}")
        evs.append(ev)
    parts = [_evidence_parts(root, e) for e in evs]
    images = [b for _, imgs in parts for (_, b) in imgs]
    if len(images) > REVIEW_IMG_CAP:
        raise HTTPException(status_code=422, detail=f"单次重检图片最多 {REVIEW_IMG_CAP} 张（收到 {len(images)}）")
    text = "\n\n".join(t for t, _ in parts if t)
    truncated = len(text) > REVIEW_TEXT_CAP
    text = text[:REVIEW_TEXT_CAP]
    total = (len(waits) + CLAR_BATCH - 1) // CLAR_BATCH
    jid = jobs.create("clar-review", "澄清重检" + ("（材料超长已截断）" if truncated else ""), total)
    asyncio.create_task(_run_review(proj, jid, root, waits, text, images, body.ev_ids))
    return {"job_id": jid, "total": total, "questions": len(waits)}


async def _run_review(proj, jid, root, waits, text, images, ev_ids):
    has_image = bool(images)
    answered = 0
    for i in range(0, len(waits), CLAR_BATCH):
        batch = waits[i:i + CLAR_BATCH]
        jobs.update(jid, cur=i // CLAR_BATCH + 1,
                    label=f"澄清重检 · 第 {i + 1}-{min(i + CLAR_BATCH, len(waits))}/{len(waits)} 题")
        try:
            qs = "\n".join(
                f"{w.no}. [{'选择题：' + ' / '.join(w.opts) if w.kind == 'choice' else '开放题：需补充材料'}] {w.q}"
                for w in batch)
            out = await _ai(tasks.clar_review, qs, text, images=images)
            answered += _apply_review(out.results, batch, text, ev_ids, has_image)
            for w in batch:  # 每批落盘一次
                await clarifications.set_ai(root, w.no, w.ai.model_dump() if w.ai else None)
        except Exception:
            jobs.update(jid, failed=jobs.get(jid).get("failed", 0) + len(batch))
    jobs.update(jid, ok=answered)
    jobs.finish(jid)
```

jobs.py：`create` 的初始 dict 加 `"failed": 0` 已有；无需改。注意 `jobs.get(jid)` 现返回 dict 或 None——沿用 `_run_verify` 的取值模式。

- [ ] **Step 4: 过测 + 全量回归 + commit**

Run: `uv run pytest tests/ -q`
```bash
git add server/app/api/router.py server/tests/test_clar_material.py
git commit -m "feat：澄清重检——POST /clarifications/review 后台 job（分批 AI 代答+防幻觉校验：选项命中/quote substring/conf 降级）"
```

---

### Task 6: 澄清答案升级（answer text/ev_ids + adopt/ignore + 联动）

**Files:**
- Modify: `server/app/storage/clarifications.py`、`server/app/api/router.py`（ClarIn + resolve_clarification）
- Test: `server/tests/test_clar_material.py`（追加）

**Interfaces:**
- Consumes: Task 1 模型；既有 ref→规则核过联动（resolve_clarification 尾部）
- Produces: 存储 `answer(root, no, idx=None, text=None, ev_ids=[]) -> Clarification`（choice 题必须 idx、open 题必须 text，落 `ans`）；`clar_adopt(root, no)`、`clar_ignore(root, no)`；
  ClarIn `{no, action: answer|adopt|ignore|verify, idx?, text?, ev_ids?}`

- [ ] **Step 1: 写失败测试**

```python
# test_clar_material.py 追加
@pytest.mark.asyncio
async def test_answer_text_for_open(tmp_path):
    from app.storage import clarifications as cl
    await cl.add(tmp_path, "退款阈值？", [])
    c = await cl.answer(tmp_path, 1, text="1万以下主管审批", ev_ids=["E1"])
    assert c.st == "answered" and c.ans.kind == "material" and c.ans.ev_ids == ["E1"]
    with pytest.raises(ValueError):
        await cl.answer(tmp_path, 1, idx=0)  # open 题不接受 idx


@pytest.mark.asyncio
async def test_answer_choice_requires_idx(tmp_path):
    from app.storage import clarifications as cl
    await cl.add(tmp_path, "冷却期？", ["7天"])
    with pytest.raises(ValueError):
        await cl.answer(tmp_path, 1, text="文字")  # choice 题不接受 text
    c = await cl.answer(tmp_path, 1, idx=0)
    assert c.ans.kind == "opt" and c.answer == "7天"


@pytest.mark.asyncio
async def test_adopt_and_ignore(tmp_path):
    from app.storage import clarifications as cl
    await cl.add(tmp_path, "开放题", [])
    await cl.set_ai(tmp_path, 1, {"answer": "代答", "quote": "q", "ev_ids": ["E1"], "conf": "high", "quote_ok": True})
    c = await cl.clar_adopt(tmp_path, 1)
    assert c.st == "answered" and c.ans.kind == "material" and c.ans.text == "代答" and c.ai is None
    await cl.set_ai(tmp_path, 1, {"answer": "再检", "quote": "q", "ev_ids": [], "conf": "med", "quote_ok": True})
    c2 = await cl.clar_ignore(tmp_path, 1)
    assert c2.ai is None  # 待问 tab 不再出现代答卡
```

端点级（规则核过联动，fake AI 或直接 storage 造规则）：

```python
@pytest.mark.asyncio
async def test_adopt_triggers_rule_verify(client, monkeypatch):
    root = ensure_root("演示项目")
    from app.storage import rules as rule_store, clarifications as cl
    from app.core.models import Rule
    rule_store.save(root, [Rule(id="R1", text="推测规则", src="s", conf="推测")])
    c = await cl.add(root, "该推测与实际一致吗？", ["确认一致"], ref="R1")
    await cl.set_ai(root, c.no, {"answer": "确认一致", "quote": "原文", "ev_ids": [], "conf": "high", "quote_ok": True})
    r = await client.post(f"{BASE}/clarifications", json={"no": c.no, "action": "adopt"})
    assert r.status_code == 200
    assert rule_store.load(root)[0].verified is True  # 既有联动：采纳=人工确认
    assert rule_store.load(root)[0].clar is None
```

- [ ] **Step 2: 确认失败 → Step 3: 实现**

```python
# clarifications.py：answer 重写 + 两个新函数
async def answer(root, no: int, idx: int | None = None, text: str | None = None,
                 ev_ids: list[str] | None = None) -> Clarification:
    rows = _load(root)
    row = _find(rows, no)
    kind = row.get("kind") or ("open" if not row.get("opts") else "choice")
    if kind == "choice":
        if idx is None or text is not None:
            raise ValueError("选择题必须回选项序号 idx")
        if not 0 <= idx < len(row["opts"]):
            raise ValueError(f"选项越界: {idx}")
        ans = {"kind": "opt", "text": row["opts"][idx], "ev_ids": []}
    else:
        if text is None or not text.strip() or idx is not None:
            raise ValueError("开放题必须回文本 text")
        ans = {"kind": "material" if ev_ids else "text", "text": text.strip(), "ev_ids": ev_ids or []}
    row.update(answer=ans["text"], ans=ans, st="answered")
    _save(root, rows)
    return Clarification(**row)


async def clar_adopt(root, no: int) -> Clarification:
    rows = _load(root)
    row = _find(rows, no)
    ai = row.get("ai")
    if not ai:
        raise ValueError(f"没有待采纳的代答: {no}")
    kind = row.get("kind") or ("open" if not row.get("opts") else "choice")
    row.update(answer=ai["answer"], st="answered", ai=None,
               ans={"kind": "opt" if kind == "choice" else "material",
                    "text": ai["answer"], "ev_ids": ai.get("ev_ids", [])})
    _save(root, rows)
    return Clarification(**row)


async def clar_ignore(root, no: int) -> Clarification:
    rows = _load(root)
    _find(rows, no)["ai"] = None
    _save(root, rows)
    return Clarification(**_find(rows, no))
```

router ClarIn 与分发：

```python
class ClarIn(BaseModel):
    no: int
    action: str
    idx: Optional[int] = None
    text: Optional[str] = None
    ev_ids: Optional[list[str]] = None
```

`resolve_clarification` 分支：`answer` → `clarifications.answer(root, no, idx=body.idx, text=body.text, ev_ids=body.ev_ids or [])`；新增 `adopt`/`ignore` 两分支；`ValueError` 已有 422 包装；尾部规则核过联动对 answer/adopt/verify 均生效（现状对任何成功路径生效，保持不动即覆盖 adopt）。

- [ ] **Step 4: 过测 + 全量回归（旧 answer 用例 idx 传参路径不变）+ commit**

```bash
git add server/app/storage/clarifications.py server/app/api/router.py server/tests/test_clar_material.py
git commit -m "feat：澄清答案升级——open 题文本/材料作答、AI 代答 adopt/ignore，采纳触发规则核过联动"
```

---

### Task 7: 前端 API 层扩展

**Files:**
- Modify: `web/src/api.ts`
- Test: `web/src/api.test.ts`（追加）

**Interfaces:**
- Produces: `AiReview/ClarAnswer/Clarification` 新字段类型；`reviewClars(evIds: string[])`、`adoptClar(no)`、`ignoreClar(no)`、`answerClarOpen(no, text, evIds?)`、`addEvidenceFile(file, source?)`、`addEvidence(raw, source?)`

- [ ] **Step 1: 写失败测试（按 api.test.ts 既有 fetch mock 模式）**

```typescript
// api.test.ts 追加（沿用该文件现有的 fetch stub 方式）
it('reviewClars POST /clarifications/review', async () => {
  await setProjectSlug('p1')  // 按现有 helper
  await reviewClars(['E1', 'E2'])
  expect(fetchMock.last()?.url).toMatch(/\/clarifications\/review$/)
  expect(JSON.parse(fetchMock.last()?.body as string)).toEqual({ ev_ids: ['E1', 'E2'] })
})

it('adoptClar posts action adopt', async () => {
  await adoptClar(3)
  expect(JSON.parse(fetchMock.last()?.body as string)).toEqual({ no: 3, action: 'adopt' })
})

it('addEvidenceFile passes source=clar', async () => {
  await addEvidenceFile(new File(['x'], 'a.png'), 'clar')
  expect(fetchMock.last()?.url).toMatch(/\/evidence\?source=clar$/)
})
```

- [ ] **Step 2: 失败 → Step 3: 实现**

```typescript
// api.ts
export interface AiReview { answer: string; quote: string; ev_ids: string[]; conf: string; quote_ok: boolean }
export interface ClarAnswer { kind: 'opt' | 'text' | 'material'; text: string; ev_ids: string[] }
export interface Clarification {
  no: number; q: string; kind?: 'choice' | 'open'; opts: string[]; st: string
  answer: string | null; ref: string | null; ai?: AiReview | null; ans?: ClarAnswer | null
}

/** 澄清补料入池：source 标记来源（证据池里显示「澄清补料」徽章） */
export const addEvidenceFile = (file: File, source?: string) =>
  req<EvidenceItem>(`/evidence${source ? `?source=${source}` : ''}`, { /* 现有 raw body + X-Filename 不变 */ })

/** 澄清重检：材料 × 全部待问 → AI 代答（待采纳），返回 job 进度走 /jobs */
export const reviewClars = (evIds: string[]) =>
  req<{ job_id: string; total: number; questions: number }>('/clarifications/review', json('POST', { ev_ids: evIds }))

export const adoptClar = (no: number) =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'adopt' }))

export const ignoreClar = (no: number) =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'ignore' }))

/** open 题文本作答，可关联材料（人工看图作答场景） */
export const answerClarOpen = (no: number, text: string, evIds: string[] = []) =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'answer', text, ev_ids: evIds }))
```

- [ ] **Step 4: 过测（`npx vitest run`）+ commit**

```bash
git add web/src/api.ts web/src/api.test.ts
git commit -m "feat：前端 API 层——澄清重检/采纳/忽略/open 文本作答/补料入池 source"
```

---

### Task 8: AskDrawerV2 正式化基础（真实数据 + 移除 V1 与开关）

**Files:**
- Modify: `web/src/components/AskDrawerV2.vue`（去 mock 接 API）
- Modify: `web/src/components/AskDrawer.vue` → 大幅缩为纯容器或直接删除、`web/src/App.vue` 挂 V2
- Test: `web/src/components/__tests__/AskDrawerV2.spec.ts`（新建）

**Interfaces:**
- Consumes: Task 7 api 函数；`startJobPolling`（投递进度在 Task 9）
- Produces: `AskDrawerV2` props `{open}`，emits `close/changed`；行为：open 时 `getClarifications()` 拉真实数据；choice 点选→`answerClar(no, idx)`；open 文本→`answerClarOpen`；`changed` 在任何落账后 emit（App 重算角标）

- [ ] **Step 1: 写失败测试**

```typescript
// AskDrawerV2.spec.ts（mock ../api，模式沿 views.spec.ts 的 vi.mock）
vi.mock('../../api', () => ({
  getClarifications: vi.fn().mockResolvedValue([
    { no: 1, q: '冷却期多久？', kind: 'choice', opts: ['7天', '30天'], st: 'wait', answer: null, ref: 'R1' },
    { no: 2, q: '退款阈值？', kind: 'open', opts: [], st: 'wait', answer: null, ref: null },
    { no: 3, q: '已答题', kind: 'choice', opts: ['a'], st: 'answered', answer: 'a', ref: null,
      ans: { kind: 'opt', text: 'a', ev_ids: [] } },
  ]),
  answerClar: vi.fn().mockResolvedValue({}),
  answerClarOpen: vi.fn().mockResolvedValue({}),
}))

it('渲染待问 choice/open 卡与已答折叠行', async () => {
  const w = mount(AskDrawerV2, { props: { open: true } })
  await flushPromises()
  expect(w.text()).toContain('冷却期多久？')
  expect(w.text()).toContain('补材料')      // open 题题型徽章
  expect(w.findAll('.qc-row').length).toBeGreaterThanOrEqual(1)  // 已答折叠
})

it('choice 点选记录调 answerClar 并 emit changed', async () => {
  const w = mount(AskDrawerV2, { props: { open: true } })
  await flushPromises()
  await w.findAll('.opt')[1].trigger('click')          // 选中 B
  await w.find('button.btn:has-text("记录答案")').trigger('click')  // 或按 text 查找按钮
  await flushPromises()
  expect(answerClar).toHaveBeenCalledWith(1, 1)
  expect(w.emitted('changed')).toBeTruthy()
})
```

- [ ] **Step 2: 失败 → Step 3: 实现**

AskDrawerV2.vue 改造要点（保持现卡片流模板不动，只换数据源）：
- 删 `MOCK` 与本地模拟函数；`items = ref<Clarification[]>([])`；`watch(() => props.open)` 拉 `getClarifications()`（沿用原 AskDrawer 的错误处理与 `err` 展示）
- `answerChoice` → `await answerClar(c.no, idx)` → `load()` → `emit('changed')` → toast（沿用原文案）
- `answerOpen` → `await answerClarOpen(c.no, text)`（附件关联 Task 10）
- `kind` 判定兜底：`c.kind ?? (c.opts.length ? 'choice' : 'open')`（旧数据）
- `verify` → `verifyClar`；导出文本：choice 段沿用，open 段 `kind==='open'` 题列出
- AskDrawer.vue 删除 `previewV2` 开关与 V1 表格模板，成为薄容器（或直接让 App.vue 挂 AskDrawerV2，删除 AskDrawer.vue——**取后者**，同步改 App.vue import 与测试引用；views.spec.ts 中 AskDrawer 旧用例迁移指向新组件）

- [ ] **Step 4: 过测 + 全量（`npx vitest run`，views.spec.ts 旧 AskDrawer describe 需同步迁移）+ commit**

```bash
git add web/src/components/AskDrawerV2.vue web/src/components/AskDrawer.vue web/src/App.vue web/src/components/__tests__/AskDrawerV2.spec.ts web/src/views/__tests__/views.spec.ts
git commit -m "feat：澄清池 V2 正式化——卡片流接真实 API，移除 V1 表格与预览开关"
```

---

### Task 9: 补材料投递条 + AI 代答卡 + 采纳/忽略

**Files:**
- Create: `web/src/components/MaterialDrop.vue`（投递条：多文件选择/拖拽/粘贴）
- Create: `web/src/components/ClarCard.vue`（单题卡：choice/open/代答/折叠详情，从 AskDrawerV2 抽出——AskDrawerV2 保持 <500 行）
- Modify: `web/src/components/AskDrawerV2.vue`、`web/src/jobs.ts`（summary 加 clar-review 分支）
- Test: `web/src/components/__tests__/AskDrawerV2.spec.ts`（追加）

**Interfaces:**
- Consumes: Task 7 `reviewClars/adoptClar/ignoreClar/addEvidenceFile`、`startJobPolling(jobId, toast)`、完成后 `getClarifications()` 重拉
- Produces: `MaterialDrop` emits `submitted(evIds: string[])`（内部逐份上传 + 10MB 拦截 + 调 reviewClars + startJobPolling）；`ClarCard` props `{c: Clarification}` emits `answered/adopted/ignored/verified`

- [ ] **Step 1: 写失败测试**

```typescript
it('代答卡渲染 quote/材料 chip/conf 并采纳调 adoptClar', async () => {
  getClarifications.mockResolvedValueOnce([{
    no: 2, q: '退款阈值？', kind: 'open', opts: [], st: 'wait', answer: null, ref: null,
    ai: { answer: '1万以下主管审批', quote: '制度原文：1万以下客服主管审批', ev_ids: ['E1'], conf: 'high', quote_ok: true },
  }])
  adoptClar.mockResolvedValueOnce({})
  const w = mount(AskDrawerV2, { props: { open: true }, global: { provide: { toast: () => {} } } })
  await flushPromises()
  expect(w.text()).toContain('制度原文：1万以下客服主管审批')
  expect(w.text()).toContain('高置信')            // conf 徽章（high）
  await w.find('button:has-text("采纳")').trigger('click')
  expect(adoptClar).toHaveBeenCalledWith(2)
  expect(w.emitted('changed')).toBeTruthy()
})

it('quote_ok=false 标注「摘录未校验」', async () => { /* 同上，quote_ok:false → 文案出现「摘录未校验」 */ })

it('忽略清代答卡', async () => { /* ignoreClar 调用 + 卡片回归普通 open 题 */ })
```

- [ ] **Step 2: 失败 → Step 3: 实现要点**

`MaterialDrop.vue`（列表顶部投递条）：
- `<input type="file" multiple>` + `dragover/drop` + `paste`（文件类粘贴）三通道；>10MB 的文件 toast 拒绝
- 提交流：`for (file of files) evs.push(await addEvidenceFile(file, 'clar'))` → `const { job_id } = await reviewClars(evs.map(e => e.id))` → `startJobPolling(job_id, toast)` → emits `submitted`
- jobs.ts `summary()` 加分支：`if (j.kind === 'clar-review') return \`澄清重检完成：材料代答 ${j.ok ?? 0} 题待采纳\``（`ok` 字段存落库代答数，Task 5 已写）；job 完成后 AskDrawerV2 需重拉列表——`startJobPolling` 的完成回调只有 toast，**在 AskDrawerV2 内 submitted 后轮询 watch jobRunning 变 false 再 load()**（简单 `watch(jobRunning, ...)` 一次性）

`ClarCard.vue`：从 V2 抽出题卡模板，新增 `ai` 区块（v-if="c.ai"）：
```
┌ AI 代答（待采纳）  [高置信/中置信/低置信] ┐
│ 答案：{ai.answer}                        │
│ 摘录："{ai.quote}" {!ai.quote_ok && ·摘录未校验} │
│ 来源：{ai.ev_ids.length} 份材料           │
│                 [采纳] [忽略]             │
└──────────────────────────────────────────┘
```
conf 徽章映射 high→b-green/med→b-blue/low→b-amber；采纳/忽略按钮分别调 API → emit → 父层 load+changed。

- [ ] **Step 4: 过测 + 全量 + commit**

```bash
git add web/src/components/MaterialDrop.vue web/src/components/ClarCard.vue web/src/components/AskDrawerV2.vue web/src/jobs.ts web/src/components/__tests__/AskDrawerV2.spec.ts
git commit -m "feat：澄清池补材料投递条+AI 代答卡（quote/conf/来源展示、采纳/忽略、job 进度轮询）"
```

---

### Task 10: 单题附件 + 证据池「澄清补料」徽章

**Files:**
- Modify: `web/src/components/ClarCard.vue`（open 题「+附件」）
- Modify: `web/src/views/Pool.vue`（source='clar' 徽章；解除截图提取按钮禁用）
- Test: AskDrawerV2.spec.ts / views.spec.ts（追加）

**Interfaces:**
- Consumes: `addEvidenceFile(file, 'clar')`、`answerClarOpen(no, text, evIds)`
- Produces: open 题答案区可选挂多份附件（先入池得 evIds，提交时随 text 一起 `answerClarOpen`）；Pool 材料行 `source==='clar'` 显示 `b-amber`「澄清补料」徽章

- [ ] **Step 1: 写失败测试**

```typescript
it('open 题挂附件：入池后随文本一起提交', async () => {
  addEvidenceFile.mockResolvedValueOnce({ id: 'E9', /* ...EvidenceItem 字段 */ } as any)
  answerClarOpen.mockResolvedValueOnce({} as any)
  const w = mount(AskDrawerV2, { props: { open: true }, global: { provide: { toast: () => {} } } })
  await flushPromises()
  // 模拟文件选择（@vue/test-utils 的 trigger('change') + 文件桩）
  await w.find('input[type="file"]').setValue/* 或 element.files 赋值 */()
  await w.find('textarea').setValue('看图作答：阈值 1 万')
  await w.find('button:has-text("提交补充")').trigger('click')
  expect(answerClarOpen).toHaveBeenCalledWith(2, '看图作答：阈值 1 万', ['E9'])
})
```

```typescript
// views.spec.ts Pool 用例
it('澄清补料来源显示徽章', async () => {
  getEvidence.mockResolvedValueOnce([{ ...EV, source: 'clar' } as any])
  /* 断言 .badge 文本含「澄清补料」 */
})
```

- [ ] **Step 2: 失败 → Step 3: 实现**（ClarCard open 区块加 `+附件` 按钮与已选文件 chip 列表；Pool 行模板加 `v-if="e.source === 'clar'"` 徽章；后端 `GET /evidence` 已随 Evidence.source 自动透出，另需 `POST /evidence` 接 `?source=clar` query——router add_evidence 里 `source = request.query_params.get("source")`，仅 `'clar'` 合法、写入 payload，否则忽略。此 3 行后端改动并入本任务）

- [ ] **Step 4: 过测（前后端）+ commit**

```bash
git add web/src/components/ClarCard.vue web/src/views/Pool.vue web/src/api.ts server/app/api/router.py web/src/components/__tests__/AskDrawerV2.spec.ts web/src/views/__tests__/views.spec.ts
git commit -m "feat：open 题附件作答 + 证据池澄清补料来源徽章 + /evidence?source=clar"
```

---

### Task 11: 端到端冒烟（QUOS_FAKE_AI）+ 收尾

**Files:**
- Modify: `docs/specs/2026-09-29-clar-material-design.md`（状态行改「已实现 P1」）
- Test: 手动冒烟脚本（不新增自动化）

- [ ] **Step 1: 冒烟（fake AI 全链）**

```bash
cd /Users/wangk/Documents/Git/QuOS && QUOS_FAKE_AI=1 QUOS_PORT=8000 ./start.sh --build
```
浏览器走查（项目可新建 `冒烟-澄清`）：
1. 证据池入文本材料 → 提取 → 规则出现（R 前缀）
2. 规则转问人 → 澄清池出现待问题
3. 澄清池补材料投递条传 1 份文本 → 重检进度条出现 → 完成后题卡出现「AI 代答」（fake：答「假答案」quote「材料原文」——注意 fake quote 非 substring 时 quote_ok=false 属预期，正好验证标注）
4. 采纳 → 题变已答、关联规则核过（若 ref 是规则）
5. open 题手输文本+附件 → 已答·待实证
6. 证据池显示「澄清补料」徽章
7. `杀掉 uvicorn，重启后 GET /jobs` 空态正常（任务态丢失不炸）

- [ ] **Step 2: 全量测试（双侧）**

Run: `cd server && uv run pytest tests/ -q` → 全绿；`cd web && npx vitest run` → 全绿

- [ ] **Step 3: spec 状态更新 + commit**

```bash
git add docs/specs/2026-09-29-clar-material-design.md
git commit -m "docs：澄清池材料级回答 spec 状态更新为 P1 已实现"
```

---

## Self-Review 记录

- **Spec 覆盖**：§3 模型→T1；§4 解析（pdf/图片/多模态/截图解除）→T2/T3；§5 重检+采纳→T4/T5/T6；§2 入口（source 标记）→T7/T10；§7 前端（V2 正式化/投递条/代答卡/附件/徽章）→T8/T9/T10；§11 测试要点逐条落各任务。P2（pipeline 编排、批量采纳、池内勾选重检 UI——注意 review 端点本身在 T5 已具备，P2 只差 UI 入口）不在本计划。
- **类型一致性**：`AiReview.quote_ok` 在 T1 定义、T5 校验写入、T9 前端消费；`clar_review(questions, materials, images)` T4 定义 T5 调用；`answer(idx|text, ev_ids)` T6 存储、T7 `answerClarOpen` 对应。
- **已知偏差**：三处已在头部「实现细化」声明（materials 端点合并进 review、quote_ok 字段、JPEG 统一）。
