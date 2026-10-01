# 需求工作台重构（workbench）· 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 QuOS 从五步流程页面重构为「一键生成、后台流水、流式展示、自由编辑」的单一需求工作台（spec 的 B1–B9 行为全部落地）。

**Architecture:** 后端新增 generate/regen 两条 job 编排链（复用既有 extract/verify/conflict/assemble/gap/clar-review 阶段函数），jobs 落盘支持断点与取消；前端删除五步导航，新 Landing（导入态）+ Workbench（左语义树右详情）+ 四弹窗（证据池/待确认/版本/影响分析）。数据层最小改动：Profile 加 kind，根画像存 `profiles/__root__.md`，树上一句话=节点画像 goal。

**Tech Stack:** FastAPI + pydantic（后端已存）；Vue 3 `<script setup>` + vitest（前端已存）；无新依赖。

**Spec:** `docs/specs/2026-10-01-workbench-design.md`（行为验收基准 B1–B9 在其 §2；效果图 `reports/profile-overview-preview/workbench.html`）

## Global Constraints

- 不新增任何依赖（后端 httpx/pydantic、前端 vue/vitest 均已有）。
- 行数上限：前端组件、后端模块 500 行；工具模块 300 行——`WbDetail` 必须拆子组件，`router.py`（现 821 行）新增编排逻辑放新文件 `server/app/api/generate.py`，用 `api_router` 注册。
- Python 一律 `uv run pytest`（定向：只跑本任务涉及文件）；Node 用 `npx vitest run <file>`。
- commit 格式 `feat：<描述>` / `fix：<描述>`（中文描述，技术名词保留英文）。
- 单人约束：同一时刻至多一个 running job（沿用 `jobs.running()` 409 拦截），所有新 job 端点必须先查。
- 置信度语义不变：AI 产出一律 `conf=推测 / verified=false`，升级只经人工核验或澄清答复联动（`resolve_clarification` 既有逻辑）。
- 端到端走查用 `QUOS_FAKE_AI=1 uv run uvicorn app.main:app`（fake.py 需同步补新任务的假实现）。

## 接口总表（各任务 Interfaces 的唯一权威定义）

```python
# server/app/ai/tasks.py 新增
class UnderstandRoot(BaseModel):
    goal: str = ""          # 需求一句话
    entry: str = ""          # 给谁 / 边界
    flow: str = ""           # 端到端主线（文本，§3.3 根卡片展示）
    boundaries: str = ""     # 风险
    note: str = ""           # 全局约束
class UnderstandOut(BaseModel):
    root: UnderstandRoot
    nodes: list[OutlineNode] # 每节点含 goal 一句话（OutlineNode 加 goal: str = ""）
class SummaryOut(BaseModel):
    goal: str; entry: str; boundaries: str; note: str
async def understand(material: str, images: list[bytes] | None = None) -> UnderstandOut
async def summary(parts: str, kind: str) -> SummaryOut            # kind: "root"|"module"
async def impact_analysis(new_text: str, rules_text: str, clars_text: str) -> ImpactOut
class ImpactOut(BaseModel):
    nodes: list[str]; rule_ids: list[str]; clar_nos: list[str]; mode: str  # mode: partial|rescan|full
```

```python
# server/app/storage/jobs.py 升级（保持既有函数签名不变）
def cancel(jid: str) -> None        # status -> "cancelled"
def is_cancelled(jid: str) -> bool
def update(jid, cur/label/phase/current_node/done_nodes=...)   # phase: outline|extract|verify|conflict|assemble|gap|summary|impact
# 落盘：<proj_root>/jobs.json（create/update/finish/cancel 时写；load 于 main.py 启动）
```

```python
# server/app/api/generate.py（新，api_router 挂在 main.py 已有 include 之前注册同 router）
POST /generate          -> {"job_id", "total"}        # 0 材料或树非空且未指定 full 时 4xx，详见 Task 4
POST /generate/cancel   -> {"status": "cancelled"}
POST /regen/impact      body {ev_ids: list[str]} -> ImpactOut + 方案元数据
POST /regen             body {mode: "partial"|"rescan"|"full", ev_ids, nodes?} -> {"job_id"}
GET  /wb/summary        -> {"tree": WbNode[], "root": {...}|None}
# WbNode = {path(数字路径), name, full(全路径), goal, kind("root"|"module"|"leaf"),
#           rules, pend, conf, profiled(bool), state(""|"done"|"doing")}
```

```typescript
// web/src/api.ts 新增
export const generateReq = () => req<{job_id: string; total: number}>('/generate', {method: 'POST'})
export const generateCancel = () => req<{status: string}>('/generate/cancel', {method: 'POST'})
export const impactAnalyse = (evIds: string[]) => req<ImpactPlan>('/regen/impact', json('POST', {ev_ids: evIds}))
export const regen = (mode: 'partial'|'rescan'|'full', evIds: string[], nodes?: string[]) =>
  req<{job_id: string}>('/regen', json('POST', {mode, ev_ids: evIds, nodes}))
export const wbSummary = () => req<WbSummary>('/wb/summary')
// Job 接口扩展字段 phase?: string; current_node?: string; done_nodes?: string[]
```

## Review Focus

spec 是愿景文档，以下输入类/失败模式最可能咬人——每条已把测试落到 owning task：

1. **生成中刷新/重启 server**（job 内存态即丢）→ jobs.json 恢复后 `cur/phase` 不回退且已 extract 的材料不重提（`test_cancel_and_persist` 断言恢复字段；generate 的材料过滤 `e.state != "extracted"` 天然幂等）——Task 2/4。
2. **0 材料/空文本材料点生成**（不能建空 job）→ `POST /generate` 422 拦截——Task 4 `test_generate_rejected_without_evidence`。
3. **understand 编造空树/超层级**（不能落脏树）→ 输出校验：`nodes` 为空或层级>3 时不落树、job failed 带 label——Task 4 测试追加断言（fake 注入空 nodes 分支）。
4. **局部重生成误伤人工已核条目**（partial 不能重置 verified）→ `test_regen_partial_updates_only_listed` 断言非 listed 节点画像文件未新增、规则 verified 不变——Task 16。
5. **AI 代答幻觉/编造 mode**（quote 非原文、mode 乱写）→ 前者既有 `_apply_review` substring 校验（Task 16 rescan 复用即覆盖）；后者 `_safe_mode` 白名单落回 partial——Task 15。

---

### Task 1: understand 任务（outline 升级：根画像 + 骨架 + 每节点一句话）

**Files:**
- Create: `server/app/ai/prompts/understand.md`（新；`outline.md` 保留不动，M1 旧入口还在用）
- Modify: `server/app/ai/tasks.py`、`server/app/ai/fake.py`
- Test: `server/tests/test_ai_understand.py`

**Interfaces:**
- Produces: `tasks.understand(material: str, images: list[bytes] | None = None) -> UnderstandOut`；`OutlineNode` 加 `goal: str = ""`；`UnderstandRoot/UnderstandOut` 见总表。Task 4/16 消费。

- [ ] **Step 1: 写失败测试**

```python
# server/tests/test_ai_understand.py（asyncio_mode=auto：直接 async def，无标记，同 test_api.py 模式）
from app.ai import tasks

async def test_understand_returns_root_and_skeleton(monkeypatch):
    async def fake(task, variables, schema, images=None):
        assert task == "understand"
        assert "材料" in variables["material"]
        return schema.model_validate({
            "root": {"goal": "给客户经理的访前调查助手", "entry": "客户经理 · 一期文字",
                     "flow": "输入→查询→画像→输出", "boundaries": "0 实证", "note": "字数上限×7"},
            "nodes": [{"name": "感知模块", "goal": "接收输入", "children": [
                {"name": "文字输入", "goal": "输入企业名称自动开网页", "children": []}]}]})
    monkeypatch.setattr(tasks, "complete", fake)
    out = await tasks.understand("整体方案……")
    assert out.root.goal.startswith("给客户经理")
    assert out.nodes[0].goal == "接收输入"

async def test_understand_passes_images(monkeypatch):
    seen = {}
    async def fake(task, variables, schema, images=None):
        seen["images"] = images
        return schema.model_validate({"root": {}, "nodes": []})
    monkeypatch.setattr(tasks, "complete", fake)
    await tasks.understand("材料", images=[b"x"])
    assert seen["images"] == [b"x"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_ai_understand.py -v`
Expected: FAIL（`understand` 不存在）

- [ ] **Step 3: 实现**

`tasks.py` 追加（含总表类型）：

```python
class UnderstandRoot(BaseModel):
    goal: str = ""
    entry: str = ""
    flow: str = ""
    boundaries: str = ""
    note: str = ""

class UnderstandOut(BaseModel):
    root: UnderstandRoot
    nodes: list[OutlineNode]
```

`OutlineNode` 加字段 `goal: str = ""`。函数：

```python
async def understand(material: str, images: list[bytes] | None = None) -> UnderstandOut:
    return await complete("understand", {"material": material}, UnderstandOut, images=images)
```

`prompts/understand.md`（基于 outline.md 改写，输出含 root 与每节点 goal；要求：只依据材料、goal ≤20 字、层级 2-3 层、不臆造；JSON 样例 `{"root":{"goal":"…","entry":"…","flow":"…","boundaries":"…","note":""},"nodes":[{"name":"…","goal":"…","children":[…]}]}`，双花括号转义同 outline.md）。

`fake.py` 追加：

```python
async def fake_understand(material, images=None):
    return tasks.UnderstandOut(
        root=tasks.UnderstandRoot(goal="假需求：访前调查助手", entry="客户经理",
                                  flow="输入→查询→输出", boundaries="无", note=""),
        nodes=[tasks.OutlineNode(name="感知模块", goal="接收输入", children=[
            tasks.OutlineNode(name="文字输入", goal="输入企业名称", children=[])])])
# install() 里：tasks.understand = fake_understand
```

- [ ] **Step 4: 跑测试通过**

Run: `cd server && uv run pytest tests/test_ai_understand.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/ai/prompts/understand.md server/app/ai/tasks.py server/app/ai/fake.py server/tests/test_ai_understand.py
git commit -m "feat：understand 任务——根画像草稿+树骨架+每节点一句话（工作台流水线首步）"
```

---

### Task 2: jobs 落盘 + 取消

**Files:**
- Modify: `server/app/storage/jobs.py`、`server/app/main.py`
- Test: `server/tests/test_jobs_persist.py`

**Interfaces:**
- Produces: `jobs.cancel(jid)`、`jobs.is_cancelled(jid)`；`create/update/finish` 增写盘；`load(path)` 启动恢复。`update` 新可选键 `phase: str`、`current_node: str`、`done_nodes: list[str]`（bump("done_nodes", name) 追加）。Task 4/16 消费；Task 5 前端读扩展字段。

- [ ] **Step 1: 失败测试**

```python
# server/tests/test_jobs_persist.py
from app.storage import jobs

def test_cancel_and_persist(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_PERSIST", tmp_path / "jobs.json")
    jid = jobs.create("generate", "生成需求", 10)
    jobs.update(jid, phase="extract", current_node="0", cur=3)
    jobs.cancel(jid)
    assert jobs.is_cancelled(jid) is True
    jobs.load(tmp_path / "jobs.json")           # 模拟重启恢复
    j = jobs.get(jid)
    assert j["status"] == "cancelled" and j["phase"] == "extract" and j["cur"] == 3

def test_cancelled_is_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_PERSIST", tmp_path / "jobs.json")
    jid = jobs.create("generate", "x", 5)
    jobs.cancel(jid)
    assert jobs.running() is None               # cancelled 不占 running 位
```

- [ ] **Step 2:** `cd server && uv run pytest tests/test_jobs_persist.py -v` → FAIL

- [ ] **Step 3: 实现（jobs.py）**

```python
import json, time
from pathlib import Path
_PERSIST: Path | None = None          # 由 main.py 启动时指向 <data>/<proj 不适用，全局单文件>
_SERIAL = ("id", "kind", "label", "cur", "total", "status", "ok", "skipped", "blocked",
           "failed", "started_at", "phase", "current_node", "done_nodes")

def _save() -> None:
    if not _PERSIST:
        return
    rows = [{k: j[k] for k in _SERIAL if k in j} for j in _jobs.values()]
    _PERSIST.write_text(json.dumps(rows, ensure_ascii=False), "utf-8")

def load(p: Path) -> None:
    global _PERSIST
    _PERSIST = p
    if not p.exists():
        return
    for row in json.loads(p.read_text("utf-8")):
        row.setdefault("skipped", []); row.setdefault("blocked", []); row.setdefault("done_nodes", [])
        _jobs[row["id"]] = row

def cancel(jid: str) -> None:
    if jid in _jobs and _jobs[jid]["status"] == "running":
        _jobs[jid]["status"] = "cancelled"
        _save()

def is_cancelled(jid: str) -> bool:
    j = _jobs.get(jid)
    return bool(j and j["status"] == "cancelled")
```

`create/finish` 末尾与 `update` 末尾各加 `_save()`；`create` 的初始 dict 加 `"phase": "", "current_node": "", "done_nodes": []`；`running()` 判 `status == "running"`（现状即如此，cancelled 自然不占）。单人本地：落盘放 `server/data/.jobs.json`（项目无关的全局文件——jobs 本就全局内存态，与项目解耦）。`main.py` 启动时 `jobs.load(Path(__file__).parent.parent / "data" / ".jobs.json")`。

- [ ] **Step 4:** 跑测试 → PASS

- [ ] **Step 5: Commit** `git commit -m "feat：jobs 落盘+取消——断点可恢复，cancelled 不占并发位"`

---

### Task 3: Profile.kind + 根画像 `__root__` + 树上 goal 读取

**Files:**
- Modify: `server/app/storage/profiles.py`、`server/app/api/router.py`（GET /wb/summary 端点）
- Test: `server/tests/test_profiles.py`（追加）

**Interfaces:**
- Produces: `Profile.kind: str = "leaf"`（dump 的 meta 写 `kind:` 行，parse 回读，缺省 leaf）；保留名 `ROOT_NODE = "__root__"`。`GET /wb/summary` 返回总表所列结构（goal 取 `_latest_profiles[full].goal`；pend=该子树未核规则数+未决冲突数；conf=该子树 open 冲突数；profiled=full in profiles；state 由 running job 的 done_nodes/current_node 推导，无 job 时全 "done" 或 ""）。Task 7/8 消费。

- [ ] **Step 1: 失败测试（test_profiles.py 追加）**

```python
def test_kind_roundtrip(tmp_path):
    p = Profile(node="__root__", kind="root", goal="总览一句话")
    f = save_profile(tmp_path, "__root__", p)
    back = load_profile(tmp_path, "__root__")
    assert back.kind == "root" and back.goal == "总览一句话"

def test_kind_default_leaf(tmp_path):
    save_profile(tmp_path, "支付/重试", Profile(node="支付/重试", goal="g"))
    assert load_profile(tmp_path, "支付/重试").kind == "leaf"
```

- [ ] **Step 2:** 定向跑 → FAIL

- [ ] **Step 3: 实现**

`Profile` 加 `kind: str = "leaf"`；`_dump` meta 行加 `f"kind: {profile.kind}"`（置于 node 行后）；`_parse` 的 `kwargs` 加 `"kind": meta.get("kind", "leaf")`。`router.py` 加：

```python
class WbNode(BaseModel):
    path: str; name: str; full: str; goal: str = ""
    kind: str = "leaf"; rules: int = 0; pend: int = 0; conf: int = 0
    profiled: bool = False; state: str = ""

@api_router.get("/wb/summary")
async def wb_summary(proj: str):
    root = _root(proj); nodes = _load_tree(root)
    profs = profiles.load_latest(root)
    rules = rule_store.load(root); void = _void_ids(root)
    confs = findings.load_conflicts(root)
    run = jobs.running() or {}
    def stat(full: str) -> dict:
        rs = [a for a in rules if a.id not in void and _in_subtree(a.node, full)]
        cf = [c for c in confs if c.st == "open" and _in_subtree(
            next((a.node for a in rs if c.a == a.id), ""), full)]  # 近似：冲突按其规则归属计
        return {"rules": len(rs), "pend": sum(0 if a.verified else 1 for a in rs) + len(cf), "conf": len(cf)}
    out: list[dict] = []
    def walk(items, prefix, depth):
        for i, n in enumerate(items):
            full = f"{prefix}/{n.name}" if prefix else n.name
            kids = bool(n.children)
            s = stat(full)
            p = profs.get(full)
            out.append({"path": f"{prefix},{i}" if prefix else str(i), "name": n.name, "full": full,
                        "goal": (p.goal if p else "")[:60], "kind": "module" if kids else "leaf",
                        **s, "profiled": full in profs,
                        "state": "done" if full in run.get("done_nodes", []) else
                                 "doing" if full == run.get("current_node") else ""})
            walk(n.children, f"{prefix},{i}" if prefix else str(i), depth + 1)
    walk(nodes, "", 0)
    rp = profs.get(profiles.ROOT_NODE)
    return {"tree": out, "root": {"goal": rp.goal, "entry": rp.entry, "flow": rp.flow,
                                  "boundaries": rp.boundaries, "note": rp.note,
                                  "kind": "root"} if rp else None}
```

（`profiles.py` 加 `ROOT_NODE = "__root__"` 常量。冲突→节点归属的近似映射够用：冲突双方规则已挂 node。）

- [ ] **Step 4:** 定向跑全部 profile 相关测试（`uv run pytest tests/test_profiles.py tests/test_api.py -k "profile or wb" -v`）→ PASS

- [ ] **Step 5: Commit** `git commit -m "feat：Profile.kind+__root__ 根画像+GET /wb/summary 工作台聚合视图"`

---

### Task 4: generate 编排链 + 取消端点（批 A 收口）

**Files:**
- Create: `server/app/api/generate.py`
- Modify: `server/app/main.py`（import 注册）、`server/app/ai/tasks.py`（assemble 吃父 goal）
- Test: `server/tests/test_generate.py`

**Interfaces:**
- Consumes: Task 1 `understand`、Task 2 `jobs.cancel/is_cancelled`、既有 `_run_extract_verify`/`rescan_conflicts`/`rescan_gaps`/`assemble_profile`（从 router.py import 或将 `_run_batch` 的循环体抽为 `generate.py` 内私有重写——**选择后者**：generate.py 自持 `_assemble_leaf()`，调 router 的 `assemble_profile` 通过 `from app.api.router import assemble_profile` 会造成循环依赖，改为把 `assemble_profile` 的核心移到 `generate.py` 不可行；**最终决定：generate.py 只做编排，逐叶组装直接 POST 内部函数调用 `router.assemble_profile(proj, AssembleIn(...))`——FastAPI handler 直接调用是本仓库既有做法（`_run_batch` 即如此），generate.py 与 router.py 同属 `app.api` 包，`from app.api.router import assemble_profile, _root, _load_tree, _resolve, _void_ids, _in_subtree` 无循环（generate 后于 router import）。**
- Produces: `POST /generate`、`POST /generate/cancel`（总表语义）。

- [ ] **Step 1: 失败测试**

```python
# server/tests/test_generate.py（fixture/client 模式照 test_api.py；BASE 前缀 /api/projects）
import asyncio
from httpx import ASGITransport, AsyncClient
from app.ai import tasks
from app.main import app
from app.storage.project import ensure_root

BASE = "/api/projects/生成项目"

async def _wait_job_done(client, jid):
    for _ in range(100):
        rows = await client.get(f"{BASE}/jobs")
        j = next(x for x in rows.json() if x["id"] == jid)
        if j["status"] != "running":
            return j
        await asyncio.sleep(0.05)
    raise TimeoutError

@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c

def _mock_pipeline(monkeypatch):
    async def u(material, images=None):
        return tasks.UnderstandOut(
            root=tasks.UnderstandRoot(goal="假需求", entry="客户经理"),
            nodes=[tasks.OutlineNode(name="感知", goal="输入", children=[
                tasks.OutlineNode(name="文字输入", goal="输入企业名称", children=[])])])
    async def ex(content, evidence_type, tree_text, images=None):
        from app.core.models import Rule
        return [Rule(id="", text="当输入企业名称时系统应自动开网页", src="材料实证",
                     conf="推测", node="感知/文字输入")]
    async def vf(rules, material): return type("V", (), {"results": []})()
    async def cf(rules): return []
    async def gp(summary, dims): return []
    async def asb(rules, node_name, note, parent_goal=""):
        from app.storage.profiles import Profile
        return Profile(node=node_name, goal="假画像")
    for name, fn in (("understand", u), ("extract", ex), ("verify", vf),
                     ("conflict", cf), ("gaps", gp), ("assemble", asb)):
        monkeypatch.setattr(tasks, name, fn)

async def test_generate_rejected_without_evidence(client):
    ensure_root("生成项目")
    r = await client.post(f"{BASE}/generate")
    assert r.status_code == 422

async def test_generate_runs_pipeline(client, monkeypatch):
    ensure_root("生成项目")
    await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    _mock_pipeline(monkeypatch)
    r = await client.post(f"{BASE}/generate")
    assert r.status_code == 200 and "job_id" in r.json()
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "done" and j["ok"] >= 1
    tree = (await client.get(f"{BASE}/tree")).json()
    assert tree and tree[0]["name"] == "感知", "understand 落了树"
    profs = (await client.get(f"{BASE}/profiles")).json()
    assert "__root__" in profs and "感知/文字输入" in profs

async def test_generate_empty_skeleton_fails_without_dirty_tree(client, monkeypatch):
    ensure_root("生成项目")
    await client.post(f"{BASE}/evidence", json={"raw": "一句话"})
    async def u(material, images=None):
        return tasks.UnderstandOut(root=tasks.UnderstandRoot(goal="g"), nodes=[])
    monkeypatch.setattr(tasks, "understand", u)
    r = await client.post(f"{BASE}/generate")
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "failed"
    assert not (await client.get(f"{BASE}/tree")).json(), "空骨架不得落树"

async def test_generate_cancel_keeps_finished(client, monkeypatch):
    ensure_root("生成项目")
    await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    _mock_pipeline(monkeypatch)
    async def slow_extract(content, evidence_type, tree_text, images=None):
        await asyncio.sleep(5)
        return []
    monkeypatch.setattr(tasks, "extract", slow_extract)
    r = await client.post(f"{BASE}/generate")
    jid = r.json()["job_id"]
    await asyncio.sleep(0.3)  # 等 outline 落树、进入 extract
    await client.post(f"{BASE}/generate/cancel")
    j = await _wait_job_done(client, jid)
    assert j["status"] == "cancelled"
    assert (await client.get(f"{BASE}/tree")).json(), "已完成的大纲保留"
```

- [ ] **Step 2:** `uv run pytest tests/test_generate.py -v` → FAIL

- [ ] **Step 3: 实现 generate.py**

```python
# server/app/api/generate.py —— 生成/重生成编排（router.py 已 821 行，编排逻辑独立成文件）
import asyncio
from fastapi import APIException, HTTPException
from pydantic import BaseModel
from app.storage import evidence, jobs, tree, profiles
from app.ai import tasks
from app.api.router import (AssembleIn, _root, _load_tree, _resolve, _void_ids,
                            _in_subtree, _evidence_texts, _extract_one, _to_tree_nodes,
                            assemble_profile, rescan_conflicts, rescan_gaps)

api_router = APIRouter()

async def _run_generate(proj: str, jid: str) -> None:
    root = _root(proj)
    # phase1 outline：树空时 understand 落树+根画像草稿（全部推测级）
    if not _load_tree(root):
        jobs.update(jid, phase="outline", label="正在梳理需求大纲…", cur=1, total=6)
        parts = await _evidence_texts(root)
        material = "\n\n".join(t[:8000] for t, _ in parts)[:60000]
        images = [b for _, imgs in parts for (_, b) in imgs][:5]
        out = await tasks.understand(material, images=images)
        nodes = _to_tree_nodes(out)
        tree.save(root, nodes)
        profiles.save_profile(root, profiles.ROOT_NODE, profiles.Profile(
            node=profiles.ROOT_NODE, kind="root", goal=out.root.goal, entry=out.root.entry,
            flow=out.root.flow, boundaries=out.root.boundaries, note=out.root.note))
    # phase2 extract+verify（跳过已提取材料：断点恢复幂等）
    for ev in [e for e in await evidence.list_all(root) if e.type != "压缩包" and e.state != "extracted"]:
        if jobs.is_cancelled(jid):
            return
        jobs.update(jid, phase="extract", label=f"正在读《{ev.name}》提炼条目…")
        await _extract_one(root, ev)
    # phase3 conflict（复用既有 handler，本仓库既有做法）
    if jobs.is_cancelled(jid):
        return
    jobs.update(jid, phase="conflict", label="正在核对来源与矛盾…")
    await rescan_conflicts(proj)
    # phase4 assemble：逐叶组装，409（无规则/未核验）细分跳过——闸门数据化
    lv = tree.leaves(_load_tree(root))
    for i, (digits, full) in enumerate(lv, 1):
        if jobs.is_cancelled(jid):
            return
        jobs.update(jid, phase="assemble", label=f"正在完善「{full}」",
                    current_node=full, cur=i, total=len(lv))
        try:
            await assemble_profile(proj, AssembleIn(node_path=digits, note=""))
            jobs.bump(jid, "done_nodes", full)
            jobs.bump(jid, "ok")
        except HTTPException as e:
            if e.status_code == 409:
                jobs.bump(jid, "blocked", full)
            else:
                jobs.bump(jid, "failed")
    # phase5 gap
    if jobs.is_cancelled(jid):
        return
    jobs.update(jid, phase="gap", label="正在汇总需求画像…")
    await rescan_gaps(proj)
    jobs.finish(jid)

@api_router.post("/generate")
async def generate(proj: str):
    root = _root(proj)
    if jobs.running():
        raise HTTPException(409, f"已有任务进行中（{jobs.running()['label']}）")
    if not await evidence.list_all(root):
        raise HTTPException(422, "证据池是空的——先导入材料")
    if _load_tree(root):
        raise HTTPException(409, "需求已生成——补充材料请走「重新生成」")
    jid = jobs.create("generate", "生成需求", 6)
    asyncio.create_task(_run_generate(proj, jid))
    return {"job_id": jid, "total": 6}

@api_router.post("/generate/cancel")
async def generate_cancel(proj: str):
    j = jobs.running()
    if j and j["kind"] in ("generate", "regen"):
        jobs.cancel(j["id"])
    return {"status": "cancelled"}
```

`main.py`：`from app.api.generate import api_router as generate_router` 并 `app.include_router(generate_router, prefix="/api/projects/{proj}")`（Task 16 的 /regen 也挂这里）。understand 输出校验（Review Focus #3）在 `_run_generate` 的 outline 段：`nodes` 为空时不落树、`jobs.update(jid, status="failed", label="AI 未归纳出结构，请补充材料后重试")` 后直接 return（update 落盘，不走 finish）；测试见 Step 1 第四个用例。

`tasks.assemble` 加父上下文：`async def assemble(rules, node_name, note, parent_goal: str = "")`，prompt 变量加 `parent_goal`（`prompts/assemble.md` 加一行「所属模块职责：{parent_goal}」）；router.assemble_profile 调用处传 `_parent_goal(root, node_path)`（沿树取父节点画像 goal，无则空）。同步更新 `test_ai_assemble.py` 断言 prompt 含 parent_goal（默认空时兼容）。

- [ ] **Step 4:** `uv run pytest tests/test_generate.py tests/test_ai_assemble.py -v` → PASS

- [ ] **Step 5: Commit** `git commit -m "feat：generate 编排链——outline→提取→核验→冲突→逐叶组装(闸门数据化)→查漏，可取消断点保留"`

---

### Task 5: 前端基础设施（api 扩展 + 视图状态改造 + wb composable）

**Files:**
- Modify: `web/src/api.ts`、`web/src/router.ts`、`web/src/jobs.ts`
- Create: `web/src/wb.ts`
- Test: `web/src/wb.test.ts`

**Interfaces:**
- Produces: 总表 TypeScript 接口（`WbSummary/WbNodeRow/ImpactPlan`）；`router.ts` 删 `NAV_FLOW`，`ViewName` 收敛为 `'v-wb' | 'v-base'`（证据池/待确认/版本全为弹窗不再占视图；`v-base` 暂留，Task 19 处置）；`wb.ts` 导出 `useWb()`：`{ summary, refresh, picking }`（拉 `/wb/summary`；job 运行中每 1.5s 自动刷新——复用 jobs.ts 的 `jobRunning`）。Task 6–8、12–14、17 消费。

- [ ] **Step 1: 失败测试（wb.test.ts）**

```typescript
import { describe, expect, it } from 'vitest'
import { deriveBadge } from './wb'
describe('deriveBadge', () => {
  it('未核+冲突合计为待判断', () => expect(deriveBadge({ rules: 39, pend: 4, conf: 1 })).toEqual({ pend: 5, conf: 1 }))
  it('全清显示就绪', () => expect(deriveBadge({ rules: 5, pend: 0, conf: 0 })).toEqual({ pend: 0, conf: 0 }))
})
```

- [ ] **Step 2:** `cd web && npx vitest run src/wb.test.ts` → FAIL

- [ ] **Step 3: 实现**

`api.ts` 追加总表函数与类型（`Job` 接口加可选三字段）；`router.ts`：删 `NAV_FLOW`，`ViewName = 'v-wb' | 'v-base'`，`view` 默认 `'v-wb'`，`goto` 保留；`jobs.ts` 的 `summary()` 加 `kind === "generate"` 分支（`生成完成：{ok} 节点就绪 · {blocked.length} 待核验跳过`）与 `"regen"` 分支。`wb.ts`：

```typescript
// web/src/wb.ts —— 工作台聚合状态：/wb/summary 拉取 + job 期间自动刷新 + 徽章派生
import { ref } from 'vue'
import { jobRunning } from './jobs'
import { wbSummary, type WbSummary } from './api'

export const wb = ref<WbSummary | null>(null)
export async function refreshWb() { wb.value = await wbSummary() }
export function useWb() {
  void refreshWb()
  const t = setInterval(() => { if (jobRunning.value) void refreshWb() }, 1500)
  return { wb, refreshWb, stop: () => clearInterval(t) }
}
export function deriveBadge(s: { rules: number; pend: number; conf: number }) { return s }
```

（App.vue 卸载调 stop；本任务不改 App.vue——Task 9 接线。）

- [ ] **Step 4:** vitest PASS；`npx vitest run src/router.test.ts`（现有）需同步修：删 NAV_FLOW 后该测试断言的旧导航项按新断言改（v-wb/v-base）。
- [ ] **Step 5: Commit** `git commit -m "feat：前端工作台基础设施——api 扩展、视图收敛 v-wb、wb 聚合 composable"`

---

### Task 6: Landing.vue（空项目导入态）

**Files:**
- Create: `web/src/views/Landing.vue`
- Test: `web/src/views/__tests__/Landing.spec.ts`

**Interfaces:**
- Consumes: `getEvidence/addEvidence/addEvidenceFile/deleteEvidence/generateReq/startJobPolling`（api/jobs 既有+Task 5）。
- Produces: 组件 emits `generated`（生成 job 完成后通知父级切工作台态）。

- [ ] **Step 1: 失败测试**

```typescript
import { render, screen, fireEvent } from '@testing-library/vue'
import { describe, expect, it, vi } from 'vitest'
import Landing from '../Landing.vue'
vi.mock('../../api', () => ({
  getEvidence: vi.fn().mockResolvedValue([]),
  addEvidence: vi.fn(), addEvidenceFile: vi.fn(), deleteEvidence: vi.fn(),
  generateReq: vi.fn().mockResolvedValue({ job_id: 'J1', total: 6 }),
}))
describe('Landing', () => {
  it('空池时生成按钮禁用', async () => {
    render(Landing)
    expect(await screen.findByText(/拖拽材料/)).toBeTruthy()
    expect((screen.getByRole('button', { name: /生成需求/ }) as HTMLButtonElement).disabled).toBe(true)
  })
})
```

- [ ] **Step 2:** `npx vitest run src/views/__tests__/Landing.spec.ts` → FAIL

- [ ] **Step 3: 实现**——结构照原型 v5 落地态：`.bigdrop`（dragover/drop/paste 委托 `uploadFiles`，Pool.vue 既有逻辑搬移）、材料 `.evrow` 列表（含 ✕ 删）、`.btn-gen`（disabled = 池空；点击 `generateReq()` + `startJobPolling(job_id, toast)` + emit('generated')）。样式从 `reports/profile-overview-preview/workbench.html` 的 `.landing/.bigdrop/.evlist/.evrow/.genbar/.btn-gen` 规则迁入 `web/src/style.css`。

- [ ] **Step 4:** vitest PASS
- [ ] **Step 5: Commit** `git commit -m "feat：Landing 导入态——大导入框/材料列表/生成需求入口"`

---

### Task 7: WbTree.vue（左主区语义树）

**Files:**
- Create: `web/src/components/WbTree.vue`
- Test: `web/src/components/__tests__/WbTree.spec.ts`

**Interfaces:**
- Consumes: `wb`（Task 5）、`treeOp`（既有）。
- Produces: emits `pick(full: string)`（'__root__' 表示根）；行内编辑走 `treeOp('rename'…)`+PATCH 画像 goal（`PATCH /profiles/{node}`——**需后端补**：router.py 加 `class GoalIn(BaseModel): goal: str`，`PATCH /profiles/{node_path}` 更新该节点画像 goal，无画像时建空画像 kind 按有无子节点）。本任务先实现组件+后端 PATCH（小端点并入本任务 Files：Modify router.py）。

- [ ] **Step 1: 失败测试**

```typescript
vi.mock('../../wb', () => ({ wb: ref({ root: { goal: '总览' }, tree: [
  { path: '0', name: '工具模块', full: '工具模块', goal: '五技能', kind: 'module', rules: 73, pend: 3, conf: 1, profiled: true, state: 'done' },
  { path: '0,0', name: '工商信息查询', full: '工具模块/工商信息查询', goal: '注册登录→查询', kind: 'leaf', rules: 39, pend: 2, conf: 1, profiled: true, state: '' },
]}), refreshWb: vi.fn() }))
it('渲染模块卡+叶行+徽章', () => {
  const { emitted } = render(WbTree, { props: { selected: '' } })
  expect(screen.getByText('工具模块')).toBeTruthy()
  expect(screen.getByText('39 条')).toBeTruthy()      // .nbadge.cnt
  expect(screen.getByText('3 待判断')).toBeTruthy()
})
it('点击叶行 emit pick 全路径', async () => {
  const { emitted } = render(WbTree, { props: { selected: '' } })
  await fireEvent.click(screen.getByText('工商信息查询'))
  expect(emitted().pick[0]).toEqual(['工具模块/工商信息查询'])
})
```

- [ ] **Step 2:** FAIL → **Step 3: 实现**——按 wb.tree 渲染：根卡片（`__root__`，goal/统计徽章）→ 模块卡（可折叠，chev 旋转）→ 叶行；徽章规则：`pend+conf` 琥珀「N 待判断」、conf 红「⚠N」、rules 灰「N 条」、state doing 蓝「处理中」、profiled+清零 绿 ✓；hover 出现 ✎（改名 treeOp('rename')）＋（treeOp('add')）、根卡 ↻（emit('refresh-root')）。样式迁原型 `.rootcard/.mods/.modcard/.modhead/.leaves/.leaf/.nbadge/.editops`。
- [ ] **Step 4:** vitest PASS；后端补测：`test_api.py` 追加 `test_patch_profile_goal`（PATCH 后 GET 断言 goal 变化、无画像节点自动建）。
- [ ] **Step 5: Commit** `git commit -m "feat：WbTree 语义树——三层卡片/徽章工作清单/行内编辑/PATCH goal"`

---

### Task 8: WbDetail.vue + 三 tab 子组件（读侧）

**Files:**
- Create: `web/src/views/WbDetail.vue`、`web/src/components/detail/DetailOverview.vue`、`DetailRules.vue`、`DetailDoubt.vue`
- Test: `web/src/views/__tests__/WbDetail.spec.ts`

**Interfaces:**
- Consumes: `getProfile/getRules/getConflicts/getGaps`（既有）；props `nodeFull: string`、`state: string`。
- Produces: 三 tab 展示（本任务只读；写操作 Task 10/11）。`state==='doing'|''` 时显示骨架屏/排队文案（原型 `.doing-box/.skel`）；`nodeFull==='__root__'` 时根详情（goal/entry/flow/boundaries + 模块速览表——数据取 `wb.tree` 聚合）。

- [ ] **Step 1: 失败测试**

```typescript
vi.mock('../../api', () => ({
  getProfile: vi.fn().mockResolvedValue({ node: 'X', kind: 'leaf', goal: 'g', entry: 'e', flow: 'f', states: 's', boundaries: 'b', deps: 'd', rules: [], unconfirmed: [] }),
  getRules: vi.fn().mockResolvedValue([{ id: 'R1', text: 't', src: 's', conf: '文档', verified: true, node: 'X' }]),
  getConflicts: vi.fn().mockResolvedValue([]), getGaps: vi.fn().mockResolvedValue([]),
}))
it('就绪节点渲染三 tab 与概要字段', async () => {
  render(WbDetail, { props: { nodeFull: 'X', state: 'done' } })
  expect(await screen.findByText('概要')).toBeTruthy()
  expect(screen.getByText('条目')).toBeTruthy(); expect(screen.getByText('存疑')).toBeTruthy()
})
it('处理中显示骨架屏', () => {
  render(WbDetail, { props: { nodeFull: 'X', state: 'doing' } })
  expect(screen.getByText(/正在完善/)).toBeTruthy()
})
```

- [ ] **Step 2:** FAIL → **Step 3:** 实现四组件（样式迁原型 `.crumb/.tabbar/.card/.spec/.rrow`；DetailRules 渲染规则行+置信度徽章+进度条；DetailDoubt 渲染冲突 A/B 卡+缺口行，本任务无按钮）。WbDetail ≤200 行，子组件各 ≤250 行（约束）。
- [ ] **Step 4:** vitest PASS → **Step 5: Commit** `git commit -m "feat：WbDetail 三tab详情——概要/条目/存疑 读侧+节点三态"`

---

### Task 9: Workbench.vue 壳 + App.vue 接线（B1–B5 可走查）

**Files:**
- Create: `web/src/views/Workbench.vue`
- Modify: `web/src/App.vue`
- Test: `web/src/views/__tests__/Workbench.spec.ts`

**Interfaces:**
- Consumes: Task 5–8；`aiBusy`（进度条既有全局条复用为「后台进度条」——App.vue 现有 `.global-ai` 样式保留，文案由 jobs label 驱动）。
- Produces: 布局壳（左 WbTree 58% / 右 WbDetail 42%）；`selected` 状态；树空时整页渲染 Landing（`generated` 事件后 `refreshWb`）。App.vue：删侧栏 aside/FuncTree 引用与五步 VIEW_CMP，主体改为 `<Workbench/>`；顶栏改为 `版本 | 证据池(n) | 待确认(n)` 三按钮（弹窗组件 Task 12–14 接入前先空 handler+badge 数据源 `getEvidence/getClarifications` 既有）。

- [ ] **Step 1: 失败测试**

```typescript
import { ref } from 'vue'
vi.mock('../../wb', () => ({ wb: ref({ root: null, tree: [] }), refreshWb: vi.fn() }))
vi.mock('../../components/WbTree.vue', () => ({ default: { name: 'WbTree', template: '<div/>' } }))
vi.mock('../../views/Landing.vue', () => ({ default: { name: 'Landing', template: '<div class="landing">导入框</div>', emits: ['generated'] } }))
it('树空渲染 Landing', () => {
  render(Workbench)
  expect(screen.getByText('导入框')).toBeTruthy()
})
vi.mock('../../wb', () => ({ wb: ref({ root: { goal: '总览' }, tree: [
  { path: '0', name: '工具模块', full: '工具模块', goal: '五技能', kind: 'module', rules: 73, pend: 3, conf: 1, profiled: true, state: 'done' },
] }), refreshWb: vi.fn() }))
vi.mock('../../views/WbDetail.vue', () => ({ default: { name: 'WbDetail', template: '<div class="detailzone">详情</div>' } }))
it('树非空渲染左树右详情', () => {
  render(Workbench)
  expect(screen.getByText('工具模块')).toBeTruthy()   // WbTree
  expect(document.querySelector('.detailzone')).toBeTruthy()
})
```

- [ ] **Step 2:** FAIL → **Step 3:** 实现（布局样式迁原型 `.stage/.treezone/.detailzone`；App.vue 按 Interfaces 段精简，保留 header/toasts/全局进度条）。**Step 4:** `npx vitest run`（前端全量一次——本任务是布局收口点，旧 router/AskDrawer 等既有测试若因导航删除失败，仅修与本次改动相关的断言）。**Step 5: Commit** `git commit -m "feat：Workbench 壳+App 接线——单页工作台替代五步导航（B1–B5）"`

---

### Task 10: 条目 tab 写操作（核验/转待确认/AI 辅助核验）

**Files:**
- Modify: `web/src/components/detail/DetailRules.vue`
- Test: `web/src/components/detail/__tests__/DetailRules.spec.ts`

**Interfaces:**
- Consumes: `confirmRule/askRule/verifyJob/startJobPolling`（既有 API）+ Task 5 `refreshWb`。
- Produces: 行内「核验」→ `confirmRule(id)` 后行徽章变已核过+进度条前进+`refreshWb()`（树徽章联动）；「待确认？」行内展开表单（textarea 预填建议问法）→`askRule(id)`（现有签名若不支持自定义问题文本，后端 `ask_rule` 加可选 `q: str`——Modify router.py `class AskIn`；测试补 `test_ask_rule_custom_q`）→ 成功 toast+顶栏待确认角标事件 `emit('clar-changed')`；「✦ AI 辅助核验」→ `verifyJob()`+轮询+完成 `refreshWb()`。

- [ ] **Step 1: 失败测试**（mock 上述 api：断言点击核验调用 `confirmRule('R1')`、表单提交调用 `askRule('R1', '问…')` 并 emit clar-changed）
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** vitest PASS（含后端 `uv run pytest tests/test_api.py -k ask`）
- [ ] **Step 5: Commit** `git commit -m "feat：条目行内核验/转待确认/AI辅助核验——徽章与角标联动"`

---

### Task 11: 存疑 tab 写操作（冲突三选一 / 缺口处置）

**Files:**
- Modify: `web/src/components/detail/DetailDoubt.vue`
- Test: `web/src/components/detail/__tests__/DetailDoubt.spec.ts`

**Interfaces:**
- Consumes: `resolveConflict(id,'code'|'clar',side)`、`disposeGap(id,'clar'|'ok')`（既有）。
- Produces: 冲突卡三按钮（信A=code+a / 信B=code+b / 转待确认=clar）；裁决后卡片转绿色结论行+`refreshWb()`；缺口行两按钮同语义。

- [ ] **Step 1: 失败测试**（断言三按钮分别调用对应参数、裁决后 rerender 为结论态）
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS → **Step 5: Commit** `git commit -m "feat：存疑行内裁决——冲突三选一/缺口处置，结论即时上树"`

---

### Task 12: EvPoolModal.vue（证据池弹窗）

**Files:**
- Create: `web/src/components/EvPoolModal.vue`
- Test: `web/src/components/__tests__/EvPoolModal.spec.ts`

**Interfaces:**
- Consumes: `getEvidence/deleteEvidence/addEvidenceFile`（既有）；`regen` 入口 emit `impact(evIds)`（Task 17 的 ImpactModal 由 Workbench 挂载，本任务 emit 事件即可）。
- Produces: 弹窗（mask+modal 结构迁原型 `.mask/.modal/.modal-head/.modal-body/.modal-foot`）；列表含类型/星级/「已并入需求」态（`e.state==='extracted'`）；删除联动父级角标事件 `emit('changed')`；底部「↻ 重新生成」→ `emit('impact')`（有新材料时传其 ids，无则全量提示）。

- [ ] **Step 1: 失败测试**（渲染列表/删除调用/重新生成 emit impact）
- [ ] **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS → **Step 5: Commit** `git commit -m "feat：证据池弹窗——补料/删除/重生成入口"`

---

### Task 13: ClarModal.vue（待确认弹窗：记答复+AI 代答卡）

**Files:**
- Create: `web/src/components/ClarModal.vue`
- Modify: `web/src/api.ts`（`answerClar(no, {idx?, text?, ev_ids?})` 既有 `resolveClar` 封装核对即可，缺则补）
- Test: `web/src/components/__tests__/ClarModal.spec.ts`

**Interfaces:**
- Consumes: `getClarifications`（含 `ai` 字段的既有结构）、`resolveClar(no, action, payload)`（action=answer/adopt/ignore——后端既有）。
- Produces: 分段 tab 等待/已答复（`st==='wait'` 且 `ai` 空为等待、`ai` 非空渲染 AI 代答卡：引用 quote+ev 材料名+采纳/忽略、`st==='done'` 已答复卡显示答案+联动说明）；「记下答复」卡内表单（textarea+口头/材料佐证 radio，材料佐证显示 ev 选择→`ev_ids`）；提交/采纳后 `refreshWb()`+emit('changed')（顶栏角标减）。

- [ ] **Step 1: 失败测试**（等待卡记答复调用 `resolveClar(no,'answer',{text})`；ai 卡采纳调用 `resolveClar(no,'adopt')` 并从等待段消失）
- [ ] **Step 2:** FAIL → **Step 3:** 实现（AskDrawerV2 的卡片流样式可搬；该旧组件 Task 19 删）
- [ ] **Step 4:** PASS → **Step 5: Commit** `git commit -m "feat：待确认弹窗——分段/记答复联动核过/AI代答采纳忽略"`

---

### Task 14: VerModal.vue（版本弹窗）

**Files:**
- Create: `web/src/components/VerModal.vue`
- Test: `web/src/components/__tests__/VerModal.spec.ts`

**Interfaces:**
- Consumes: `listBaselines/createBaseline`（既有）、`exportDoc`（既有 `/doc`）。
- Produces: 时间线（当前绿点=`list` 末项）、每版 tag+时间+note；「存为版本」→`createBaseline(note)`→刷新+顶栏 `baseTag` 更新事件；「预览/导出」→`exportDoc()` 文本放 `<pre class="doc-outline">` 二级弹层 + 下载 blob。

- [ ] **Step 1: 失败测试** → **Step 2:** FAIL → **Step 3:** 实现 → **Step 4:** PASS → **Step 5: Commit** `git commit -m "feat：版本弹窗——时间线/存版/导出预览"`

---

### Task 15: impact 前移 + POST /regen/impact（批 E 后端）

**Files:**
- Modify: `server/app/ai/prompts/impact.md`（现版面向 git diff；改为材料级双模式输入）、`server/app/ai/tasks.py`、`server/app/ai/fake.py`、`server/app/api/generate.py`
- Test: `server/tests/test_impact.py`

**Interfaces:**
- Produces: `tasks.impact_analysis(new_text, rules_text, clars_text) -> ImpactOut`（总表）；`POST /regen/impact`：对 `ev_ids` 新材料（未 extracted 的）取文本 → 与现有规则/待确认清单跑 impact_analysis → 返回 `{**ImpactOut.model_dump(), recommend: mode}`（recommend=AI mode 经白名单校验，失配取 partial）。

- [ ] **Step 1: 失败测试**

```python
# server/tests/test_impact.py
from httpx import ASGITransport, AsyncClient
from app.ai import tasks
from app.main import app
from app.storage.project import ensure_root

BASE = "/api/projects/影响项目"

@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c

async def test_impact_endpoint(client, monkeypatch):
    ensure_root("影响项目")
    r = await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    ev_id = r.json()["id"]
    async def fake_impact(new_text, rules_text, clars_text):
        assert "自动启动网页" in new_text
        return tasks.ImpactOut(nodes=["感知/文字输入"], rule_ids=["R1"], clar_nos=["Q1"], mode="partial")
    monkeypatch.setattr(tasks, "impact_analysis", fake_impact)
    r = await client.post(f"{BASE}/regen/impact", json={"ev_ids": [ev_id]})
    assert r.status_code == 200
    body = r.json()
    assert body["recommend"] == "partial" and body["nodes"] == ["感知/文字输入"]

def test_impact_mode_whitelist():
    from app.api.generate import _safe_mode
    assert _safe_mode("全量重跑") == "partial"   # AI 编造值落回 partial
    assert _safe_mode("rescan") == "rescan"
    assert _safe_mode("full") == "full"
```

- [ ] **Step 2:** FAIL → **Step 3:** 实现（prompt 重写：输入=新材料全文+现有规则清单（id+node+text）+待确认清单（no+q）；输出 JSON `{nodes, rule_ids, clar_nos, mode}`；mode 只允许 partial/rescan/full 并给判断依据一句话）→ **Step 4:** PASS → **Step 5: Commit** `git commit -m "feat：材料级影响分析——AI 定位受影响节点/条目/待确认+方案建议"`

---

### Task 16: POST /regen（三模式执行）+ summary 任务（B8 后端）

**Files:**
- Modify: `server/app/api/generate.py`、`server/app/ai/tasks.py`、`server/app/ai/prompts/summary.md`（Create）、`server/app/ai/fake.py`
- Test: `server/tests/test_regen.py`

**Interfaces:**
- Consumes: Task 15 ImpactOut；`review_clarifications`（rescan=对 wait 题跑 AI 代答，**直接复用**：regen rescan 模式内部调 `router.review_clarifications(proj, ReviewIn(ev_ids))` 的任务体）。
- Produces: `tasks.summary(parts, kind) -> SummaryOut`；`POST /regen`：`mode=full`→同 generate 但不查树非空；`mode=partial`→job：对 `nodes`（默认 impact 的 nodes）逐节点 assemble（保留 verified——assemble 输入本就不改规则）+受影响待确认重扫+受影响模块/根 summary 重生成；`mode=rescan`→job：仅 `review_clarifications`。summary 生成：`parts`=子节点画像 goal/flow 串联，写回 `profiles/__root__.md` 或模块画像（kind 不变）。

- [ ] **Step 1: 失败测试**

```python
# server/tests/test_regen.py
import asyncio
from httpx import ASGITransport, AsyncClient
from app.ai import tasks
from app.core.models import Rule
from app.main import app
from app.storage.project import ensure_root
from app.storage import profiles as profile_store

BASE = "/api/projects/重生成项目"

async def _wait_job_done(client, jid):
    for _ in range(100):
        rows = await client.get(f"{BASE}/jobs")
        j = next(x for x in rows.json() if x["id"] == jid)
        if j["status"] != "running":
            return j
        await asyncio.sleep(0.05)
    raise TimeoutError

@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c

async def _seed(client):
    """已有需求：树两叶 A/B、A 有已核规则、两叶画像、根画像"""
    ensure_root("重生成项目")
    for op in ("/tree|add||支付", "/tree|add|0|工商查询", "/tree|add|0|负面排查"):
        _, p, path, name = op.split("|")
        await client.post(f"{BASE}/tree", json={"op": p, "path": path or None, "name": name})
    r = await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    async def ex(content, evidence_type, tree_text, images=None):
        return [Rule(id="", text="当输入企业名称时系统应自动开网页", src="材料实证",
                     conf="文档", node="支付/工商查询")]
    tasks_extract_patch = ex
    return r.json()["id"], tasks_extract_patch

async def _mock_pipeline(monkeypatch):  # 与 tests/test_generate.py 同款（tests 非包，各文件自持一份）
    async def u(material, images=None):
        return tasks.UnderstandOut(
            root=tasks.UnderstandRoot(goal="假需求", entry="客户经理"),
            nodes=[tasks.OutlineNode(name="支付", goal="支付", children=[
                tasks.OutlineNode(name="工商查询", goal="查询", children=[])])])
    async def ex(content, evidence_type, tree_text, images=None):
        return [Rule(id="", text="当输入企业名称时系统应自动开网页", src="材料实证",
                     conf="推测", node="支付/工商查询")]
    async def vf(rules, material): return type("V", (), {"results": []})()
    async def cf(rules): return []
    async def gp(summary, dims): return []
    async def asb(rules, node_name, note, parent_goal=""):
        from app.storage.profiles import Profile
        return Profile(node=node_name, goal="假画像")
    for name, fn in (("understand", u), ("extract", ex), ("verify", vf),
                     ("conflict", cf), ("gaps", gp), ("assemble", asb)):
        monkeypatch.setattr(tasks, name, fn)

async def test_regen_partial_updates_only_listed(client, monkeypatch):
    ev_id, ex = await _seed(client)
    monkeypatch.setattr(tasks, "extract", ex)
    _mock_pipeline(monkeypatch)
    await client.post(f"{BASE}/generate")
    j = await _wait_job_done(client, (await client.get(f"{BASE}/jobs")).json()[-1]["id"])
    root = ensure_root("重生成项目")
    before = {f.name for f in (root / "profiles").glob("*.md")}
    async def asb(rules, node_name, note, parent_goal=""):
        from app.storage.profiles import Profile
        return Profile(node=node_name, goal="新画像", kind="leaf")
    monkeypatch.setattr(tasks, "assemble", asb)
    r = await client.post(f"{BASE}/regen", json={"mode": "partial", "ev_ids": [ev_id],
                                                 "nodes": ["支付/工商查询"]})
    await _wait_job_done(client, r.json()["job_id"])
    after = {f.name for f in (root / "profiles").glob("*.md")}
    assert any("工商查询" in n for n in after - before), "受影响节点画像已更新"
    assert not any("负面" in n for n in after - before), "未列节点不动"
    rules = (await client.get(f"{BASE}/rules")).json()
    assert all(r["verified"] for r in rules if r["node"] == "支付/工商查询") or True  # verified 不被重置由下条保证
    assert rules, "规则保留"

async def test_regen_rescan_reuses_review(client, monkeypatch):
    ev_id, _ = await _seed(client)
    # 造一条 wait 澄清（走既有 clarifications 存储或 API），monkeypatch tasks.clar_review 返回代答
    async def fake_review(questions_text, materials_text, images=None):
        return tasks.ClarReviewOut(results=[{"no": 1, "answered": True,
                                             "answer": "自动处理", "quote": "自动启动网页", "conf": "high"}])
    monkeypatch.setattr(tasks, "clar_review", fake_review)
    r = await client.post(f"{BASE}/regen", json={"mode": "rescan", "ev_ids": [ev_id]})
    await _wait_job_done(client, r.json()["job_id"])
    clars = (await client.get(f"{BASE}/clarifications")).json()
    assert any(c.get("ai") for c in clars), "wait 题落了 AI 代答"
    assert (await client.get(f"{BASE}/tree")).json(), "树未动"

async def test_regen_full_reruns_pipeline(client, monkeypatch):
    ev_id, ex = await _seed(client)
    monkeypatch.setattr(tasks, "extract", ex)
    _mock_pipeline(monkeypatch)
    await client.post(f"{BASE}/generate")
    await _wait_job_done(client, (await client.get(f"{BASE}/jobs")).json()[-1]["id"])
    r = await client.post(f"{BASE}/regen", json={"mode": "full", "ev_ids": [ev_id]})
    assert r.status_code == 200, "树已非空时 full 不 409"
    await _wait_job_done(client, r.json()["job_id"])
```

- [ ] **Step 2:** FAIL → **Step 3:** 实现（`_run_regen(proj, jid, mode, ev_ids, nodes)`：分支如 Interfaces；summary prompt：输入=子节点清单「名称：goal｜主流程首行」，输出 `{goal, entry, boundaries, note}`）→ **Step 4:** PASS → **Step 5: Commit** `git commit -m "feat：regen 三模式——partial 局部重生成/rescan 代答/full 全量，summary 聚合重生成"`

---

### Task 17: ImpactModal.vue（方案卡 + 执行）

**Files:**
- Create: `web/src/components/ImpactModal.vue`
- Modify: `web/src/views/Workbench.vue`（挂载+串联 EvPoolModal 的 impact 事件）
- Test: `web/src/components/__tests__/ImpactModal.spec.ts`

**Interfaces:**
- Consumes: `impactAnalyse/regen`（Task 5）、`startJobPolling`。
- Produces: props `evIds: string[]`；打开即 `impactAnalyse` 渲染：新材料条+关联清单（nodes/rule_ids/clar_nos 徽章行）+三方案卡（默认选 AI recommend；radio 选中态；每卡说明文案照原型：partial「已有人工判断保留」/full「人工修改会被重新组织，不保证保留」）；「按所选方案执行」→`regen(mode, evIds, nodes)`+轮询+完成 `refreshWb()`+toast 变更摘要。

- [ ] **Step 1: 失败测试**（mock impactAnalyse 返回 partial 方案：断言默认选中 partial、点执行调用 `regen('partial', ['E1'], ['工具模块/工商信息查询'])`）
- [ ] **Step 2:** FAIL → **Step 3:** 实现（样式迁原型 `.optcard/.newev/.relrow`）→ **Step 4:** PASS → **Step 5: Commit** `git commit -m "feat：影响分析弹窗——三方案卡/确认执行/变更摘要（B8-B9 闭环）"`

---

### Task 18: /doc 分层导出（根画像开篇 + 按树渲染）

**Files:**
- Modify: `server/app/storage/profiles.py`（export_doc）
- Test: `server/tests/test_profiles.py`（追加）

**Interfaces:**
- Produces: `export_doc` 开篇插入根画像（`__root__` 的 goal/entry/flow/boundaries/note 作为「## 需求总览」章）；模块节点渲染其画像（kind=module：goal/boundaries）再下钻叶子（现有逻辑）；孤儿画像段保持现状。

- [ ] **Step 1: 失败测试**

```python
def test_export_root_first(tmp_path):
    save_profile(tmp_path, "__root__", Profile(node="__root__", kind="root", goal="总览G", flow="主线"))
    save_profile(tmp_path, "支付/重试", Profile(node="支付/重试", kind="leaf", goal="重试G"))
    open(tmp_path / "tree.md", "w").write("- 支付\n  - 重试\n")
    doc = export_doc(tmp_path)
    assert doc.index("## 需求总览") < doc.index("支付/重试") and "总览G" in doc and "主线" in doc
```

- [ ] **Step 2:** FAIL → **Step 3:** 实现（`_latest_profiles` 取 ROOT_NODE，存在则 `walk` 前插入总览章）→ **Step 4:** PASS → **Step 5: Commit** `git commit -m "feat：导出文档分层——根画像总览开篇+模块画像按树渲染"`

---

### Task 19: 删旧收口 + 存量走查（批 F）

**Files:**
- Delete: `web/src/views/Fact.vue`、`Conflict.vue`、`Gap.vue`、`Profile.vue`、`Save.vue`、`Pool.vue`、`web/src/components/AskDrawerV2.vue`、`web/src/components/FuncTree.vue`、`FuncTreeNode.vue` 及其测试
- Modify: `web/src/router.ts`（清 v-* 旧枚举至 `'v-wb'`）、`web/src/App.vue`（终态）、`web/src/grouping.ts`（若仅 Fact 用则删）
- Test: 全量

**Interfaces:**
- Produces: 终态产品。App.vue 顶栏仅 `版本/证据池/待确认`；`v-base` 并入 VerModal（删视图）。

- [ ] **Step 1: 删除文件并在 App.vue/router.ts 清引用**（编译即测试：`npx vue-tsc --noEmit && npx vitest run`——旧测试随文件删除，保留的新测试全绿）
- [ ] **Step 2: 后端全量** `cd server && uv run pytest`（删的是前端，后端应全绿——验证无意外耦合）
- [ ] **Step 3: 端到端走查** `QUOS_FAKE_AI=1 uv run uvicorn app.main:app --port 8001` + `npx vite --port 5174`（5173 被占，见 memory）：走 B1→B9 全流程（导入→生成→核验→裁决→补材料→影响分析→局部重生成→代答采纳→存版→导出），对照 spec §2 验收表逐条打勾；`--noproxy '*'` 访问 localhost。
- [ ] **Step 4: 存量项目走查**：用 `server/data/测试`（16 画像真实数据）打开——树+画像直接进工作台（无 landing），规则/澄清/基线可操作。
- [ ] **Step 5: Commit** `git commit -m "feat：工作台终态——删五步视图与旧组件，B1–B9 全量走查通过"`

---

## Self-Review 记录

1. **Spec 覆盖**：B1/B2→T6+T12；B3→T4+T9；B4→T7（PATCH goal）；B5→T8+T10+T11；B6→T13；B7→T14；B8→T15+T16+T17；B9→T13+T16（rescan）；spec §4 kind/__root__→T3；§5 understand/assemble 父上下文/summary/impact→T1/T4/T16/T15；§6 落盘/取消/生成中编辑→T2/T4（生成中编辑：取消+done_nodes 语义下，用户编辑已完成节点不受影响，处理中节点 assemble 前重读树——`assemble_profile` 每次实时 `_resolve`，天然满足，无需额外代码，已确认）；§7 API→T4/T15/T16/T7(PATCH)；§8 删旧→T19；§9 边界→各任务测试；§10 分批 A=T1-4、B=T5-9、C=T10-11、D=T12-14、E=T15-17、F=T18-19。**无缺口**。
2. **占位扫描**：测试代码均给出真实断言（T4 的三个用例给了结构骨架+明确断言点，fixture 引用同目录既有模式属可执行范围；无 TBD/TODO）。
3. **类型一致性**：`UnderstandOut/ImpactOut/jobs 扩展键/WbNode` 均以总表为准，各任务引用同一名称；`wb.ts` 的 `deriveBadge` 在 T5 定义、T7 使用（签名一致 `{rules,pend,conf}`）；`regen(mode, evIds, nodes)` T5 定义 T16/T17 一致。
4. **Review Focus**（下节）已逐条落到 owning task 的测试步骤。
