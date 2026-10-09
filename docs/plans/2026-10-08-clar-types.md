# 问人池问题类型化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 待确认池按答案形态分四类（confirm 确认 / choose 取舍 / supply 补全 / custom 自定义），各类配对作答形式与联动分流，修掉「任何答案都核过规则」缺陷，并补上 AI 代答的触发入口（重检投递条）。

**Architecture:** 后端在 `Clarification` 上加 `type` 字段（存量按 ref 前缀惰性推断），三个问人入口落对应类型；`resolve_clarification` 的规则联动按 type×答案三分支（核过 / 改写+黄标 / 不动）；supply 答复自动入材料池（source=clar）；AI 重检只送非 confirm 题。前端 ClarModal 卡头四态徽章、confirm 选「不符」展开必填文本框、done 卡按类型反馈、顶部新增「✦ AI 重检」投递条（reviewClars + job 轮询）。

**Tech Stack:** FastAPI + Pydantic（server，uv 运行）；Vue 3 `<script setup>` + vitest + vue-tsc（web）。

**Spec:** `reports/clar-type-preview/DESIGN.md`（已获用户确认；原型 `reports/clar-type-preview/prototype.html`）

## Global Constraints

- 行数上限：前端组件/后端模块 500 行；router.py 已 850+ 行（已登记债务）——新增逻辑控制在既有函数内小幅改写，不新增大段。
- **不创建 commit**：用户明确要求时才 commit（项目 Git 纪律）。
- 后端测试命令：`cd server && uv run pytest <target> -q`；前端：`cd web && npx vitest run <target>`、`npx vue-tsc --noEmit`。
- 不新增依赖；注释中文、风格与现库一致（函数头一句话说明约束）。
- 服务运行在 127.0.0.1:8000（`server` 目录下 `set -a && . ../.env && set +a && uv run uvicorn app.main:app`），LLM 走本地网关（SSE 流式已就绪，本计划不动 runner）。
- 存量数据兼容：clarifications.json 旧行无 `type` 字段，读取时推断、答后写回归档，不做一次性迁移脚本。

## Review Focus

1. **存量无 type 的 clarifications.json**（所有旧项目）→ 读取不崩、推断正确、答后落档 —— Task 1 测试 `test_legacy_type_inferred_from_ref` 钉住。
2. **confirm 选「不符」但 extra 为空白字符**（前端绕过/直接 API 调用）→ 后端 422 拒绝，不得落半截答案 —— Task 1 `test_confirm_mismatch_requires_extra` 用 `"  "` 空格串钉住 strip 校验。
3. **AI 重检不得收到确认题**（代答噪声回归）→ review 请求的 questions 文本里不含 confirm 题 —— Task 5 `test_review_skips_confirm_questions` 钉住。
4. **supply 入材料池失败**（磁盘/路径异常）→ 答案本身已落盘，接口 500 由前端 toast 呈现，重提交幂等（answer 可重复覆写）—— Task 4 计划说明，不额外写失败注入测试。
5. **旧数据已带 ai 的 confirm 题被 adopt**（收窄前存量）→ 联动按答案文本分流：「确认一致」才核过；「与实际不符」无 extra 不改写 —— Task 3 `test_confirm_linkage_covers_ai_answer_texts` 钉住。
6. **choose 题答案与 opts 不逐字一致**（AI 代答未命中被 `_apply_review` 丢弃后人工答）→ 人工路径 answer 恒为选项原文，冲突裁决块沿用现状 —— 既有 test_clar_material.py 已覆盖，不在本计划重复。

---

### Task 1: 模型与存储——type 字段、extra 校验、惰性推断

**Files:**
- Modify: `server/app/core/models.py`（Clarification / ClarAnswer）
- Modify: `server/app/storage/clarifications.py`（`_load` 推断、`add()` 传 type、`answer()` 校验 extra）
- Modify: `server/app/api/router.py:62-67`（ClarIn 加 extra）+ `resolve_clarification` 的 answer 分支透传 extra
- Test: `server/tests/test_clar_types.py`（新建）

**Interfaces:**
- Produces: `Clarification.type: str`（confirm|choose|supply|custom，读侧恒非空）；`ClarAnswer.extra: str`；`clarifications.add(root, q, opts, ref=None, kind=None, type="")`；`clarifications.answer(root, no, idx=None, text=None, ev_ids=None, extra=None)`（不符缺 extra 抛 ValueError）。后续任务依赖这些签名。

- [ ] **Step 1: 写失败测试**

```python
# server/tests/test_clar_types.py —— 问人池类型化：type 字段 / 惰性推断 / extra 校验
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.storage import clarifications
from app.storage.project import ensure_root

BASE = "/api/projects/类型项目"
PROJ = "类型项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _seed_legacy(root):
    """旧数据无 type 字段：手写落盘（模拟存量项目）"""
    rows = [
        {"no": 1, "q": "推测1一致吗？", "opts": ["确认一致", "与实际不符", "不清楚"], "kind": "choice",
         "st": "wait", "answer": None, "ref": "R1", "ai": None, "ans": None},
        {"no": 2, "q": "重试几次？", "opts": ["a文", "b文"], "kind": "choice",
         "st": "wait", "answer": None, "ref": "C1", "ai": None, "ans": None},
        {"no": 3, "q": "未说明幂等键？", "opts": [], "kind": "open",
         "st": "wait", "answer": None, "ref": "G1", "ai": None, "ans": None},
        {"no": 4, "q": "自己问的", "opts": [], "kind": "open",
         "st": "wait", "answer": None, "ref": None, "ai": None, "ans": None},
    ]
    (root / "clarifications.json").write_text(json.dumps(rows, ensure_ascii=False), "utf-8")


async def test_legacy_type_inferred_from_ref(client):
    root = ensure_root(PROJ)
    _seed_legacy(root)
    rows = await clarifications.list_all(root)
    assert [c.type for c in rows] == ["confirm", "choose", "supply", "custom"]


async def test_confirm_mismatch_requires_extra(client):
    root = ensure_root(PROJ)
    await clarifications.add(root, "推测一致吗？", ["确认一致", "与实际不符", "不清楚"],
                             ref="R1", type="confirm")
    r = await client.post(f"{BASE}/clarifications", json={"no": 1, "action": "answer", "idx": 1})
    assert r.status_code == 422 and "实际行为" in r.json()["detail"]
    r = await client.post(f"{BASE}/clarifications",
                          json={"no": 1, "action": "answer", "idx": 1, "extra": "   "})
    assert r.status_code == 422  # 空白串同样拒绝
    r = await client.post(f"{BASE}/clarifications",
                          json={"no": 1, "action": "answer", "idx": 1, "extra": "实际是静默跳过"})
    assert r.status_code == 200
    assert r.json()["ans"]["extra"] == "实际是静默跳过"
    assert r.json()["answer"] == "与实际不符"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_clar_types.py -q`
Expected: FAIL（`Clarification` 无 type 字段 / add 不收 type kwarg → TypeError）

- [ ] **Step 3: 最小实现**

`server/app/core/models.py`：

```python
class ClarAnswer(BaseModel):
    kind: str  # 'opt' | 'text' | 'material'
    text: str
    ev_ids: list[str] = []
    extra: str = ""  # confirm 选「与实际不符」时补充的实际行为


class Clarification(BaseModel):
    no: int
    q: str
    opts: list[str] = []
    kind: str = "choice"  # choice | open（opts 为空即 open；旧数据默认 choice）
    type: str = ""  # confirm 确认 | choose 取舍 | supply 补全 | custom 自定义；空=旧数据（读取时按 ref 推断）
    st: str = "wait"  # wait | answered | verified
    answer: Optional[str] = None
    ref: Optional[str] = None
    ai: AiReview | None = None
    ans: ClarAnswer | None = None
```

`server/app/storage/clarifications.py`——`_load` 尾部加推断、`add` 加 type 参数、`answer` 加 extra 校验：

```python
def _infer_type(ref) -> str:
    """旧数据无 type：按 ref 前缀推断（R=规则确认题、C=矛盾取舍题、G=缺口补全题；无 ref=自定义）"""
    if not ref:
        return "custom"
    return {"R": "confirm", "C": "choose", "G": "supply"}.get(ref[:1], "custom")
```

`_load` 在 `return json.loads(...)` 处改为：

```python
    rows = json.loads(p.read_text("utf-8"))
    for r in rows:
        if not r.get("type"):
            r["type"] = _infer_type(r.get("ref"))
    return rows
```

`add`：

```python
async def add(root, q: str, opts: list[str], ref: str | None = None, kind: str | None = None,
              type: str = "") -> Clarification:
    rows = _load(root)
    row = {"no": max((r.get("no", 0) for r in rows), default=0) + 1,
           "q": q, "opts": list(opts),
           "kind": kind or ("open" if not opts else "choice"), "type": type,
           "st": "wait", "answer": None, "ref": ref, "ai": None, "ans": None}
```

`answer` 的 choice 分支（替换原 `ans = {"kind": "opt", ...}` 两行）：

```python
        opt = row["opts"][idx]
        extra = (extra or "").strip()
        if row.get("type") == "confirm" and opt == "与实际不符" and not extra:
            raise ValueError("选「与实际不符」必须补充实际行为 extra")
        ans = {"kind": "opt", "text": opt, "ev_ids": [], "extra": extra}
```

（函数签名同步加 `extra: str | None = None`。）

`server/app/api/router.py`——`ClarIn` 加字段、answer 分支透传：

```python
class ClarIn(BaseModel):
    no: int
    action: str  # answer | adopt | ignore | verify
    idx: Optional[int] = None
    text: Optional[str] = None
    ev_ids: Optional[list[str]] = None
    extra: Optional[str] = None  # confirm 选「与实际不符」的实际行为补充
```

```python
        if body.action == "answer":
            cl = await clarifications.answer(root, body.no, idx=body.idx, text=body.text,
                                             ev_ids=body.ev_ids or [], extra=body.extra)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_clar_types.py tests/test_clar_material.py tests/test_api.py -q`
Expected: 全 PASS（test_clar_material / test_api 回归确认未破坏既有 answer 行为）

---

### Task 2: 三个问人入口落 type

**Files:**
- Modify: `server/app/api/router.py`（ask_rule ~398-411、adjudicate_conflict ~457、adjudicate_gap ~511）
- Test: `server/tests/test_clar_types.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `add(..., type=)`。
- Produces: 入口产出的题目带 type——confirm（opts 三连）/ choose（opts=两侧规则文本）/ supply（opts 空、open）/ custom（opts 空、open）。

- [ ] **Step 1: 写失败测试**（追加到 test_clar_types.py）

```python
async def test_entries_create_typed_questions(client):
    from app.core.models import Conflict, Gap, Rule
    from app.storage import findings, rules as rule_store
    root = ensure_root(PROJ)
    rule_store.save(root, [
        Rule(id="R1", text="当文档为空时系统应拒绝并提示", src="a.md", conf="推测"),
        Rule(id="R2", text="重试 3 次", src="b.py:1", conf="实证"),
        Rule(id="R3", text="重试 5 次", src="b.md#2", conf="文档"),
    ])
    findings.save_conflicts(root, [Conflict(id="C1", a="R2", b="R3", q="重试几次？")])
    findings.save_gaps(root, [Gap(id="G1", dim="状态", text="未说明幂等行为", node="")])

    await client.post(f"{BASE}/rules/R1/ask")  # 默认问法 → confirm
    await client.post(f"{BASE}/rules/R2/ask", json={"q": "压缩包加密实际怎么处理？"})  # 自定义 → custom 开放
    await client.post(f"{BASE}/conflicts", json={"id": "C1", "action": "clar"})  # → choose
    await client.post(f"{BASE}/gaps", json={"id": "G1", "action": "clar"})  # → supply 开放

    rows = await clarifications.list_all(root)
    by_type = {c.type: c for c in rows}
    assert by_type["confirm"].opts == ["确认一致", "与实际不符", "不清楚"]
    assert by_type["confirm"].q.endswith("该推测与实际系统一致吗？")
    assert by_type["custom"].opts == [] and by_type["custom"].kind == "open"
    assert by_type["choose"].opts == ["重试 3 次", "重试 5 次"]
    assert by_type["supply"].opts == [] and by_type["supply"].kind == "open"
    # 规则占用联动：R1/R2 的 clar 指向各自题号
    assert {a.id: a.clar for a in rule_store.load(root)}["R1"] == by_type["confirm"].no
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_clar_types.py::test_entries_create_typed_questions -q`
Expected: FAIL（type 均为推断值/自定义问法仍是三连选项）

- [ ] **Step 3: 最小实现**

`ask_rule`（router.py）替换出题段：

```python
    custom = (body.q.strip() if body else "") or ""
    if custom:  # 自定义问法：问的是具体事实 → 开放题（type=custom），不再套三连选项
        c = await clarifications.add(root, custom, [], ref=a.id, type="custom")
    else:
        q = a.text + "——该推测与实际系统一致吗？"
        c = await clarifications.add(root, q, ["确认一致", "与实际不符", "不清楚"], ref=a.id, type="confirm")
    a.clar = c.no
```

`adjudicate_conflict` clar 分支：`await clarifications.add(root, c.q, opts, ref=c.id, type="choose")`

`adjudicate_gap` clar 分支：`await clarifications.add(root, g.text + "？", [], ref=g.id, type="supply")`（去掉 `["支持/是", "不支持/否", "不清楚"]`）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_clar_types.py tests/test_api.py -q`
Expected: 全 PASS（test_api 的问人链用例若断言旧三连选项，按新语义更新断言——gap 转 clar 后 opts 为空）

---

### Task 3: 联动按 type×答案分流（修「任何答案都核过」）

**Files:**
- Modify: `server/app/api/router.py`（`resolve_clarification` 规则联动块 ~818-822）
- Test: `server/tests/test_clar_types.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `cl.type` / `cl.ans.extra`。
- Produces: 规则联动语义——confirm·一致→核过；confirm·不符+extra→text←extra、suspect=True、verified=True；confirm·不清楚 / custom→仅解除 clar 占用（可重新转问）；choose/supply 不走规则联动（choose 走既有矛盾裁决块，保持不动）。

- [ ] **Step 1: 写失败测试**（追加）

```python
async def _seed_rule(root, rid, text):
    from app.core.models import Rule
    from app.storage import rules as rule_store
    items = [a for a in rule_store.load(root) if a.id != rid]
    items.append(Rule(id=rid, text=text, src="a.md", conf="推测"))
    rule_store.save(root, items)


async def _ask(root, rid, no, qtype="confirm"):
    await clarifications.add(root, f"{rid} 的推测一致吗？", ["确认一致", "与实际不符", "不清楚"],
                             ref=rid, type=qtype)


async def test_confirm_answer_linkage_branches(client):
    root = ensure_root(PROJ)
    from app.storage import rules as rule_store

    await _seed_rule(root, "R1", "原推测1")
    await _ask(root, "R1", 1)
    await client.post(f"{BASE}/clarifications", json={"no": 1, "action": "answer", "idx": 0})
    a1 = next(a for a in rule_store.load(root) if a.id == "R1")
    assert a1.verified is True and a1.clar is None  # 一致 → 核过

    await _seed_rule(root, "R2", "原推测2")
    await _ask(root, "R2", 2)
    await client.post(f"{BASE}/clarifications",
                      json={"no": 2, "action": "answer", "idx": 1, "extra": "实际是生成失败 Run 可重试"})
    a2 = next(a for a in rule_store.load(root) if a.id == "R2")
    assert a2.text == "实际是生成失败 Run 可重试"  # 改写
    assert a2.suspect is True and a2.verified is True and a2.nb == ""  # 黄标修正 + 核过

    await _seed_rule(root, "R3", "原推测3")
    await _ask(root, "R3", 3)
    await client.post(f"{BASE}/clarifications", json={"no": 3, "action": "answer", "idx": 2})
    a3 = next(a for a in rule_store.load(root) if a.id == "R3")
    assert a3.verified is False and a3.text == "原推测3" and a3.clar is None  # 不清楚 → 不动但解除占用

    await _seed_rule(root, "R4", "原推测4")
    await _ask(root, "R4", 4, qtype="custom")
    await client.post(f"{BASE}/clarifications", json={"no": 4, "action": "answer", "text": "问过了，差不多"})
    a4 = next(a for a in rule_store.load(root) if a.id == "R4")
    assert a4.verified is False and a4.text == "原推测4" and a4.clar is None  # custom → 无联动仅解除占用


async def test_confirm_linkage_covers_ai_answer_texts(client):
    """收窄前存量的 confirm+ai 被 adopt：答案文本分流，不符无 extra 不改写"""
    root = ensure_root(PROJ)
    from app.storage import rules as rule_store
    await _seed_rule(root, "R1", "原推测1")
    rows = [{"no": 1, "q": "q", "opts": ["确认一致", "与实际不符", "不清楚"], "kind": "choice",
             "type": "confirm", "st": "wait", "answer": None, "ref": "R1",
             "ai": {"answer": "与实际不符", "quote": "x", "ev_ids": [], "conf": "low", "quote_ok": False},
             "ans": None}]
    (root / "clarifications.json").write_text(json.dumps(rows, ensure_ascii=False), "utf-8")
    await client.post(f"{BASE}/clarifications", json={"no": 1, "action": "adopt"})
    a1 = next(a for a in rule_store.load(root) if a.id == "R1")
    assert a1.verified is False and a1.text == "原推测1"  # 不符且无 extra：不改写不核过
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_clar_types.py -q -k linkage`
Expected: FAIL（现联动无条件 `verified=True`）

- [ ] **Step 3: 最小实现**

`resolve_clarification` 中替换原「闭环联动」块（`rmap = _rule_map(root)` 起的 5 行）：

```python
    # 闭环联动：按题型×答案分流——只有 confirm 动规则；choose 走下方矛盾裁决块
    rmap = _rule_map(root)
    a = rmap.get(cl.ref)
    if a is not None:
        extra = (cl.ans.extra if cl.ans else "").strip()
        if cl.type == "confirm" and cl.answer == "与实际不符" and extra:
            a.text, a.suspect, a.verified, a.nb, a.clar = extra, True, True, "", None
        elif cl.type == "confirm" and cl.answer == "确认一致":
            a.verified, a.nb, a.clar = True, "", None
        else:
            a.clar = None  # 不清楚 / custom：不核过不改动，仅解除转问占用（可重新转问）
        rule_store.save(root, list(rmap.values()))
```

（下方 choose→矛盾裁决块原样保留。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_clar_types.py tests/test_clar_material.py tests/test_api.py -q`
Expected: 全 PASS（既有「答案确认后自动核过」用例若基于一致语义则不变；若有依赖「不符也核过」的断言按新语义修正）

---

### Task 4: supply 答复自动入材料池

**Files:**
- Modify: `server/app/api/router.py`（`resolve_clarification` 矛盾裁决块之后追加）
- Test: `server/tests/test_clar_types.py`（追加）

**Interfaces:**
- Consumes: `classify_text`（router.py 已导入）、`evidence.add`。
- Produces: supply 题 answer/adopt 后，答复文本成为一条 `source="clar"` 的证据（可走受影响重生成）。失败（磁盘等）时答案已落盘、接口 500、重提交幂等——不静默吞。

- [ ] **Step 1: 写失败测试**（追加）

```python
async def test_supply_answer_saved_as_clar_evidence(client):
    root = ensure_root(PROJ)
    from app.storage import evidence
    await clarifications.add(root, "未说明幂等键？", [], ref="G1", type="supply")
    await clarifications.add(root, "自己问的", [], ref="R1", type="custom")
    r = await client.post(f"{BASE}/clarifications",
                          json={"no": 1, "action": "answer", "text": "幂等键为受理单号+文档指纹", "ev_ids": []})
    assert r.status_code == 200
    evs = await evidence.list_all(root)
    assert len(evs) == 1 and evs[0].source == "clar"
    await client.post(f"{BASE}/clarifications", json={"no": 2, "action": "answer", "text": "口头答案"})
    evs = await evidence.list_all(root)
    assert len(evs) == 1  # custom 不入池
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_clar_types.py::test_supply_answer_saved_as_clar_evidence -q`
Expected: FAIL（evs 为空）

- [ ] **Step 3: 最小实现**

`resolve_clarification` 末尾（return 之前、矛盾裁决块之后）追加：

```python
    # supply 答复自动入材料池（source=clar）：补全的事实进证据链，可走受影响重生成；
    # 入池失败不吞（答案已落盘，重提交幂等）
    if body.action in ("answer", "adopt") and cl.type == "supply" and cl.answer:
        payload = classify_text(cl.answer)
        payload["source"] = "clar"
        await evidence.add(root, payload, content=cl.answer.encode("utf-8"))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_clar_types.py -q`
Expected: PASS

---

### Task 5: AI 代答收窄——重检不送确认题

**Files:**
- Modify: `server/app/api/router.py`（`review_clarifications` 的 waits 过滤 ~874）
- Modify: `server/app/api/generate.py`（`_rescan_waits` 的 waits 过滤 ~173）
- Test: `server/tests/test_clar_types.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `c.type`。
- Produces: 重检/重扫只处理 `type != "confirm"` 的 wait 题；全部剩余 wait 均为 confirm 时返回带说明的 422。

- [ ] **Step 1: 写失败测试**（追加）

```python
async def test_review_skips_confirm_questions(client, monkeypatch):
    from app.ai import tasks
    root = ensure_root(PROJ)
    await client.post(f"{BASE}/evidence", json={"raw": "材料：相似度阈值 0.85 时进入人工复核。"})
    await clarifications.add(root, "推测一致吗？", ["确认一致", "与实际不符", "不清楚"], ref="R1", type="confirm")
    await clarifications.add(root, "阈值边界行为是什么？", [], ref="G1", type="supply")

    seen = {}

    async def mock_review(qs, materials, images=None):
        seen["qs"] = qs
        from app.core.models import AiReview  # noqa: F401（构造见 _apply_review 契约）
        return type("R", (), {"results": [{"no": 2, "answered": True, "answer": "阈值取等号判为命中",
                                           "quote": "", "conf": "med"}]})()

    monkeypatch.setattr(tasks, "clar_review", mock_review)
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": ["文档xxxx"]})
    assert r.status_code == 200
    for _ in range(100):  # 等 job 收尾
        jobs = (await client.get(f"{BASE}/jobs")).json()
        if next(j for j in jobs if j["id"] == r.json()["job_id"])["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert "阈值边界" in seen["qs"] and "推测一致吗" not in seen["qs"]


async def test_review_all_confirm_returns_explanatory_422(client):
    root = ensure_root(PROJ)
    await client.post(f"{BASE}/evidence", json={"raw": "材料"})
    await clarifications.add(root, "推测一致吗？", ["确认一致", "与实际不符", "不清楚"], ref="R1", type="confirm")
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": ["文档xxxx"]})
    assert r.status_code == 422 and "确认题" in r.json()["detail"]
```

（文件头补 `import asyncio`；`文档xxxx` 换成实际返回的 ev id——用 `(await evidence.list_all(root))[0].id` 取。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_clar_types.py -q -k review`
Expected: FAIL（confirm 题混进了 questions 文本）

- [ ] **Step 3: 最小实现**

`review_clarifications`（router.py）替换 waits 两行：

```python
    all_wait = [c for c in await clarifications.list_all(root) if c.st == "wait"]
    waits = [c for c in all_wait if c.type != "confirm"]  # 确认题不送 AI：材料证不了「实际系统」
    if not waits:
        detail = "没有可代答的问题（确认题不送 AI——待人工拍板）" if all_wait else "没有待问问题，无需重检"
        raise HTTPException(422, detail)
```

`_rescan_waits`（generate.py）替换 waits 行：

```python
    waits = [c for c in await clarifications.list_all(root) if c.st == "wait" and c.type != "confirm"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_clar_types.py tests/test_clar_material.py tests/test_regen.py tests/test_generate.py -q`
Expected: 全 PASS

---

### Task 6: 前端 API 层——类型与 extra 透传

**Files:**
- Modify: `web/src/api.ts`（Clarification / ClarAnswer 类型、answerClar 加 extra）
- Test: `web/src/api.test.ts`（若有 answerClar 用例则扩展；无则跳过新用例，仅类型改动由 tsc 钉住）

**Interfaces:**
- Produces: `Clarification.type: string`、`ClarAnswer.extra?: string`、`answerClar(no, idx, extra = '')`（Task 7/8 依赖）。

- [ ] **Step 1: 改类型与签名**

`api.ts`：

```ts
export interface ClarAnswer {
  kind: string
  text: string
  ev_ids: string[]
  /** confirm 选「与实际不符」时补充的实际行为 */
  extra?: string
}
```

`Clarification` 接口在 `kind: string` 下加：

```ts
  /** confirm 确认 | choose 取舍 | supply 补全 | custom 自定义（后端读侧恒非空） */
  type: string
```

`answerClar` 改为：

```ts
export const answerClar = (no: number, idx: number, extra = '') =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'answer', idx, extra }))
```

- [ ] **Step 2: 类型检查 + 现有测试**

Run: `cd web && npx vue-tsc --noEmit && npx vitest run src/api.test.ts`
Expected: tsc 无错；api.test.ts PASS（若有用例断言 answerClar 的 body 无 extra，更新断言为含 `extra: ''`）

---

### Task 7: ClarModal 四态卡 + confirm 扩展交互 + done 按类型反馈

**Files:**
- Modify: `web/src/components/ClarModal.vue`
- Test: `web/src/components/__tests__/ClarModal.spec.ts`

**Interfaces:**
- Consumes: Task 6 的 `type` / `answerClar(no, idx, extra)`。
- Produces: 四态徽章、不符展开必填框、done 反馈文案（Task 8 复用 `doneFb`）。

- [ ] **Step 1: 写失败测试**（追加/更新 ClarModal.spec.ts；现有「已自动核过」联动说明断言改为按类型断言）

```ts
const TYPE_CLARS = [
  { no: 1, q: '推测与实际一致吗？', opts: ['确认一致', '与实际不符', '不清楚'], kind: 'choice', type: 'confirm',
    st: 'wait', answer: null, ref: 'R12', ai: null, ans: null },
  { no: 2, q: '重试几次？', opts: ['重试 3 次', '重试 5 次'], kind: 'choice', type: 'choose',
    st: 'wait', answer: null, ref: 'C1', ai: null, ans: null },
]

it('确认题：选「不符」展开必填框，提交带 extra；答后 done 卡显示改写反馈', async () => {
  api.getClarifications.mockResolvedValue(TYPE_CLARS)
  const w = mount(ClarModal, { props: { open: true, evidence: [] }, global: { provide: { toast: vi.fn() } } })
  await flushPromises()
  expect(w.text()).toContain('确认题')  // 四态徽章
  const opts = w.findAll('.opt')
  await opts[1].trigger('click')  // 与实际不符
  const ta = w.find('textarea[data-test="confirm-extra"]')
  expect(ta.exists()).toBe(true)
  expect(w.findAll('button').some(b => b.text() === '记下答复' && (b.element as HTMLButtonElement).disabled)).toBe(true)
  await ta.setValue('实际是静默跳过')
  api.getClarifications.mockResolvedValue([{ ...TYPE_CLARS[0], st: 'answered', answer: '与实际不符',
    ans: { kind: 'opt', text: '与实际不符', ev_ids: [], extra: '实际是静默跳过' } }])
  api.answerClar.mockResolvedValue(TYPE_CLARS[0])
  await w.findAll('button').find(b => b.text() === '记下答复')!.trigger('click')
  await flushPromises()
  expect(api.answerClar).toHaveBeenCalledWith(1, 1, '实际是静默跳过')
})

it('done 卡按类型反馈：confirm 不符=改写黄标 / choose=另一侧作废 / supply=入材料池', async () => {
  api.getClarifications.mockResolvedValue([
    { ...TYPE_CLARS[0], st: 'answered', answer: '与实际不符',
      ans: { kind: 'opt', text: '与实际不符', ev_ids: [], extra: '实际是静默跳过' } },
    { ...TYPE_CLARS[1], st: 'answered', answer: '重试 3 次', ans: { kind: 'opt', text: '重试 3 次', ev_ids: [], extra: '' } },
    { no: 3, q: '未说明幂等键', opts: [], kind: 'open', type: 'supply', st: 'answered',
      answer: '受理单号+指纹', ref: 'G1', ai: null, ans: { kind: 'text', text: '受理单号+指纹', ev_ids: [] } },
  ])
  const w = mount(ClarModal, { props: { open: true, evidence: [] }, global: { provide: { toast: vi.fn() } } })
  await flushPromises()
  const dones = w.findAll('.q-card.done')
  expect(dones[0].text()).toContain('已按答复改写并标黄')
  expect(dones[0].text()).toContain('实际是静默跳过')
  expect(dones[1].text()).toContain('另一侧作废')
  expect(dones[2].text()).toContain('答复已存为材料池')
})
```

（`data-test="confirm-extra"` 为测试锚点，实现时给 textarea 加该属性。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/components/__tests__/ClarModal.spec.ts`
Expected: FAIL（无「确认题」徽章 / 无 extra textarea / done 文案为旧「已自动核过」）

- [ ] **Step 3: 最小实现**（ClarModal.vue）

script 增加：

```ts
// 四态类型徽章：确认(蓝)/取舍(紫)/补全(橙)/自定义(灰)；旧数据 type 空 → 按来源兜底
const TYPE_BADGE: Record<string, [string, string]> = {
  confirm: ['b-blue', '确认题'], choose: ['b-purple', '取舍题'],
  supply: ['b-open', '补全题'], custom: ['b-gray', '自定义题'],
}
const typeOf = (c: Clarification) => c.type || (c.ref?.startsWith('R') ? 'confirm' : 'custom')

// confirm 选「不符」的必填补充
const extra = ref<Record<number, string>>({})

/** done 卡联动反馈：按题型×答案分流（与后端 resolve_clarification 同口径） */
function doneFb(c: Clarification): string {
  if (typeOf(c) === 'confirm') {
    if (c.answer === '确认一致') return `✓ 关联条目 ${c.ref} 已核过`
    if (c.answer === '与实际不符') return `✓ 条目 ${c.ref} 已按答复改写并标黄（修正态）`
    return '条目未动（未核过）——可重新转问'
  }
  if (typeOf(c) === 'choose') return '✓ 已按所选侧裁决，另一侧作废'
  if (typeOf(c) === 'supply') return '✓ 答复已存为材料池（来源=待确认），可走受影响重生成'
  return '已记录；无自动联动'
}
```

`answerChoice` 改为带 extra：

```ts
async function answerChoice(c: Clarification) {
  const idx = pick.value[c.no]
  if (idx === undefined) return
  const ex = (extra.value[c.no] ?? '').trim()
  if (typeOf(c) === 'confirm' && idx === 1 && !ex) return  // 不符必填，前端先拦
  try {
    await answerClar(c.no, idx, ex)
    toast(`${c.no} 已记录${idx === 1 && typeOf(c) === 'confirm' ? '（条目将按答复改写并标黄）' : ''}`)
    await reload()
  } catch (e) { failToast(e, '记录') }
}
```

template：卡头徽章 `c.kind === 'open' ? ...` 两态替换为四态：

```html
<span class="badge" :class="TYPE_BADGE[typeOf(c)]?.[0] ?? 'b-gray'">{{ TYPE_BADGE[typeOf(c)]?.[1] ?? '自定义题' }}</span>
```

choice 选项块下方（`.qc-opts` 与 `.qc-foot` 之间）插入：

```html
<div v-if="typeOf(c) === 'confirm' && pick[c.no] === 1" class="qc-extra">
  <div class="xlabel">实际行为是什么（必填）</div>
  <textarea v-model="extra[c.no]" data-test="confirm-extra" rows="2"
            placeholder="例：文档为空时静默跳过，不报错也不生成 Run……" />
  <div class="xhint">提交后条目文本按此答复改写并标黄（修正态），不再以原推测进画像</div>
</div>
```

提交按钮 disabled 条件改为 `pick[c.no] === undefined || (typeOf(c) === 'confirm' && pick[c.no] === 1 && !(extra[c.no] ?? '').trim())`；提示 hint 文案随选中项切换（一致→核过 / 不符→必填 / 不清楚→不核过）。

done 卡：`答：{{ c.answer }}` 后追加 extra 展示，`qc-link` 行替换为 `{{ doneFb(c) }}`：

```html
<div class="qc-ans">答：{{ c.answer }}<template v-if="c.ans?.extra"> —— 实际行为：{{ c.ans.extra }}</template></div>
<p v-if="c.ref" class="qc-link" :class="{ ok: doneFb(c).startsWith('✓') }">{{ doneFb(c) }}</p>
```

样式（scoped，同原型）：

```css
.b-purple { background: #f3e8ff; color: #7e22ce; }
.qc-extra { margin-top: 8px; border: 1px solid #f5c98a; background: #fffbeb; border-radius: 8px; padding: 9px 11px; }
.qc-extra .xlabel { font-size: 11.5px; font-weight: 700; color: var(--warn); margin-bottom: 5px; }
.qc-extra textarea { width: 100%; border: 1px solid var(--border2); border-radius: 6px; padding: 8px 10px; font-family: inherit; font-size: 12.5px; resize: vertical; }
.qc-extra .xhint { font-size: 11px; color: var(--muted-fg); margin-top: 5px; }
.qc-link.ok { color: #166534; }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/components/__tests__/ClarModal.spec.ts && npx vue-tsc --noEmit`
Expected: 全 PASS（含既有用例——旧断言「已自动核过」按新文案更新）

---

### Task 8: ClarModal「✦ AI 重检」投递条

**Files:**
- Modify: `web/src/components/ClarModal.vue`
- Test: `web/src/components/__tests__/ClarModal.spec.ts`（追加）

**Interfaces:**
- Consumes: `reviewClars(evIds)` / `listJobs()`（api.ts 既有）；Task 7 的 `typeOf`。
- Produces: 投递条（材料多选 → reviewClars → 轮询 job → 重拉列表 + 跳过说明）。

- [ ] **Step 1: 写失败测试**（追加）

```ts
it('AI 重检：选材料 → reviewClars + 轮询 job → 重拉列表并显示跳过说明', async () => {
  api.getClarifications.mockResolvedValue([
    { no: 1, q: '推测一致吗？', opts: ['确认一致', '与实际不符', '不清楚'], kind: 'choice', type: 'confirm',
      st: 'wait', answer: null, ref: 'R1', ai: null, ans: null },
    { no: 2, q: '阈值边界行为？', opts: [], kind: 'open', type: 'supply',
      st: 'wait', answer: null, ref: 'G1', ai: null, ans: null },
  ])
  api.reviewClars.mockResolvedValue({ job_id: 'J9', total: 1, questions: 1 })
  api.listJobs.mockReturnValue([{ id: 'J9', status: 'done' } as never])
  api.getClarifications.mockResolvedValueOnce([]) // 初始
  const w = mount(ClarModal, { props: { open: true, evidence: [EV] }, global: { provide: { toast: vi.fn() } } })
  await flushPromises()
  await w.find('select[data-test="rb-evs"]').setValue(EV.id)
  await w.find('button[data-test="rb-btn"]').trigger('click')
  await flushPromises()
  await new Promise(r => setTimeout(r, 700)) // 轮询间隔 500ms
  await flushPromises()
  expect(api.reviewClars).toHaveBeenCalledWith([EV.id])
  expect(w.text()).toContain('本次跳过：1 个确认题')
})
```

（`EV` 为既有 spec 里的 EvidenceItem fixture；`listJobs` 加入 vi.hoisted mock。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/components/__tests__/ClarModal.spec.ts -t "AI 重检"`
Expected: FAIL（找不到 select/button）

- [ ] **Step 3: 最小实现**

script 增加（`listJobs`, `reviewClars` 补进 import）：

```ts
const rbEvs = ref<string[]>([])
const rbBusy = ref(false)
const rbSkip = ref('')
const RB_POLL = 500 // 测试可接受的最短间隔

async function runReview() {
  if (!rbEvs.value.length) { toast('先选择要投递的材料', 'warn'); return }
  rbBusy.value = true
  rbSkip.value = ''
  try {
    const r = await reviewClars(rbEvs.value)
    for (let i = 0; i < 600; i++) {  // 最长 5 分钟，与 job 超时对齐
      await new Promise(res => setTimeout(res, RB_POLL))
      const j = (await listJobs().catch(() => [])).find(x => x.id === r.job_id)
      if (j && j.status !== 'running') break
    }
    await load()
    const skipped = waiting.value.filter(c => typeOf(c) === 'confirm').length
    rbSkip.value = skipped ? `本次跳过：${skipped} 个确认题（材料证不了「实际系统」）——待人工拍板` : ''
    toast('AI 重检完成，代答待采纳', 'ok')
  } catch (e) { failToast(e, 'AI 重检') } finally { rbBusy.value = false }
}
```

template：`.seg` 分段条上方插入投递条：

```html
<div class="review-bar">
  <div class="rb-hd">✦ AI 重检 <span class="r">投材料 × 待答问题 → 后台分批代答（待采纳）；确认题不送</span></div>
  <div class="rb-row">
    <select v-model="rbEvs" data-test="rb-evs" multiple>
      <option v-for="e in evidence.filter(x => x.type !== '压缩包')" :key="e.id" :value="e.id">{{ e.name }}</option>
    </select>
    <button class="rb-btn" data-test="rb-btn" type="button" :disabled="rbBusy" @click="runReview">
      {{ rbBusy ? '代答中…' : '✦ 从材料找答案' }}</button>
  </div>
  <p v-if="rbSkip" class="rb-skip">{{ rbSkip }}</p>
</div>
```

样式（scoped）：

```css
.review-bar { border: 1px solid var(--blue-bg); background: #f8faff; border-radius: 10px; padding: 10px 12px; margin-bottom: 10px; }
.review-bar .rb-hd { display: flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 700; color: var(--primary); flex-wrap: wrap; }
.review-bar .rb-hd .r { font-weight: 400; font-size: 11.5px; color: var(--muted-fg); }
.review-bar .rb-row { display: flex; gap: 8px; margin-top: 8px; align-items: center; }
.review-bar select { flex: 1; border: 1px solid var(--border2); border-radius: 8px; padding: 6px 9px; font-size: 12.5px; min-height: 56px; background: #fff; }
.review-bar .rb-btn { background: var(--primary); color: #fff; font-weight: 600; padding: 7px 14px; white-space: nowrap; }
.review-bar .rb-btn:disabled { opacity: .5; cursor: not-allowed; }
.review-bar .rb-skip { font-size: 11px; color: var(--muted-fg); margin: 6px 0 0; }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/components/__tests__/ClarModal.spec.ts && npx vue-tsc --noEmit`
Expected: 全 PASS

---

### Task 9: 构建、部署、真机 smoke

**Files:** 无新文件（构建产物 + 服务重启）

- [ ] **Step 1: 全量定向测试**

Run: `cd server && uv run pytest tests/ -q`（本次改动收尾跑全量后端）；`cd web && npx vitest run && npx vue-tsc --noEmit`
Expected: 后端全绿（此前基线 120 passed + 2 skipped，允许因新用例增加）；前端全绿

- [ ] **Step 2: 构建前端**

Run: `cd web && npm run build`
Expected: 构建成功

- [ ] **Step 3: 重启服务**（替换现有 8000 进程）

```bash
pkill -f "uvicorn app.main:app" ; sleep 2
cd server && set -a && . ../.env && set +a && nohup uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/quos-server.log 2>&1 &
```

- [ ] **Step 4: 真机 smoke**

```bash
curl -s --noproxy '*' http://127.0.0.1:8000/api/health
# 存量项目读侧不崩（惰性推断生效）：
curl -s --noproxy '*' "http://127.0.0.1:8000/api/projects/<slug>/clarifications" | python3 -m json.tool | head -20
```

浏览器（Playwright，`--noproxy` 环境已配）打开 `http://127.0.0.1:8000/#/p/<slug>` → 顶栏「待确认」→ 核对：四态徽章、确认题选「不符」出必填框、投递条可见；有存量题的项目确认旧题已被推断类型。截图留档 `reports/clar-type-preview/live-*.png`。

- [ ] **Step 5: 汇报**

按用户 Git 纪律**不 commit**；汇报改动清单、测试结果、真机验证截图，并提示：旧缺口题（supply 推断）已无三连选项、答复将自动入材料池。

---

## Self-Review 记录

- Spec 覆盖：四类 type（Task 1/2）、作答形式与 extra（Task 1/6/7）、联动分流（Task 3）、supply 入池（Task 4）、AI 收窄+入口（Task 5/8）、存量惰性迁移（Task 1）、ClarModal 四态/投递条（Task 7/8）、部署验证（Task 9）——DESIGN.md 各节均有对应任务。
- 类型一致性：`clarifications.add(..., type="")` / `answer(..., extra=None)` / `answerClar(no, idx, extra)` / `typeOf(c)` / `doneFb(c)` / `runReview()` 前后任务一致；`ClarIn.extra` 与存储层签名对齐。
- 占位符扫描：无 TBD/「适当处理」类步骤；所有代码步骤带完整代码。
- Review Focus 五条均有对应测试钉住（Task 1×2、Task 3×1、Task 5×2）。
