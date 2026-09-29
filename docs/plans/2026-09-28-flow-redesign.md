# 整理流程重构（flow redesign）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec `docs/specs/2026-09-28-flow-redesign-design.md`：五步四字流程 + 顶栏澄清池 + 规则挂节点/重要度排序 + AI 树骨架。

**Architecture:** 前端重排导航与视图（Vue3 无 router 库，视图状态在 `web/src/router.ts`）；后端给 `Rule` 加 `node`、树节点加 `priority`，extract prompt 带树上下文做归属标注，新增 outline/scaffold 链路；分组聚合逻辑抽成前端纯函数模块 `web/src/grouping.ts` 以便 vitest 覆盖。

**Tech Stack:** FastAPI + pydantic（server，uv 管理）；Vue3 + Vite + vitest（web）；AI 任务 = `server/app/ai/prompts/*.md` 模板 + `tasks.py` 封装。

**Spec:** docs/specs/2026-09-28-flow-redesign-design.md（本计划的所有设计决策以 spec 为准）

## Global Constraints

- Commit 格式：`<type>：<描述>`（type ∈ feat|fix|refactor|test|docs…，技术名词保留英文）。
- 不新增任何依赖（前端无 @vue/test-utils，Vue 组件不做单测，逻辑抽纯函数测）。
- 术语：UI 文案「规则」→「规则」、「问人」→「澄清池」；数据层 `Rule`/接口路径不改名。
- 后端测试：`cd server && uv run pytest tests/<文件> -v`（asyncio_mode=auto）；前端：`cd web && npm run test` / `npm run build`。
- 行数上限：前端组件 500 行（Fact.vue 重构必须把分组逻辑放 grouping.ts）；后端模块 500 行。
- 存量数据兼容：旧 `rules.json` 无 `node` 字段 → pydantic 默认 `""`，不写迁移；旧 `tree.md` 无 priority 后缀 → 默认 `""`。
- 工作区已有未提交改动（规则 confirm/ask 闭环等）——本计划基于其上开发，commit 时只 add 本任务触及文件。

## Review Focus

1. **AI 编造 node 路径**（extract 返回树中不存在的路径）→ 服务端白名单校验置 `""` 进未归类。测试：Task 5 Step 1。
2. **节点改名后规则 node 失配**（存量全路径不再在树中）→ 前端归「未归类」桶显示，不丢数据。测试：Task 9 Step 1 `失配归属进未归类`。
3. **tree.md 名称本身含 `@P1` 文本** → parse 仅剥离行尾严格的 `@P0|@P1|@P2` 后缀。测试：Task 7 Step 1 `名称含@不误剥`。
4. **assemble 节点过滤后规则集为空** → 空用户画像正常返回不 500。测试：Task 8 Step 1 `无匹配规则时空卡组装`。
5. **scaffold 对非空树调用**（重复点击/并发）→ 409 拒绝，不覆盖已有树。测试：Task 13 Step 1 `非空树拒绝`。

---

### Task 1: 导航重排与四字改名（router.ts）

**Files:**
- Modify: `web/src/router.ts:25-32`

**Interfaces:**
- Produces: `NAV_FLOW` 新值（顺序 `'v-fact'|'v-conf'|'v-card'|'v-gap'|'v-save'`，标签 `规则提取|冲突裁决|生成画像|查漏补缺|定稿存档`）。`ViewName` 与 `'v-ask'` 本任务不动（Task 3 移除）。

- [ ] **Step 1: 修改 NAV_FLOW**

```ts
export const NAV_FLOW: [ViewName, string][] = [
  ['v-fact', '规则提取'],
  ['v-conf', '冲突裁决'],
  ['v-card', '生成画像'],
  ['v-gap', '查漏补缺'],
  ['v-save', '定稿存档'],
]
```

- [ ] **Step 2: 构建验证**

Run: `cd web && npm run build`
Expected: vue-tsc 无错误（v-ask 仍在 ViewName/VIEW_CMP，仅导航不可达）

- [ ] **Step 3: Commit**

```bash
git add web/src/router.ts
git commit -m "refactor：整理流程导航重排为五步四字命名"
```

---

### Task 2: 五视图 + App 文案统一

**Files:**
- Modify: `web/src/views/Fact.vue`、`Conflict.vue`、`Profile.vue`、`Gap.vue`、`Save.vue`、`Pool.vue`、`App.vue`

**Interfaces:**
- Consumes: Task 1 的步骤序号（①规则提取 ②冲突裁决 ③生成画像 ④查漏补缺 ⑤定稿存档）。
- Produces: 无代码接口，纯文案。

- [ ] **Step 1: 逐文件替换文案**

| 文件:行 | 旧 | 新 |
|---|---|---|
| Fact.vue:143 | `① 提事实 · {{ curName }}` | `① 规则提取 · {{ curName }}` |
| Fact.vue:144 | `AI 读材料，一句句写下…` | `AI 读材料提取行为规则，逐条核验；按模块›功能点分组，组内按重要度排序。` |
| Fact.vue:164 | `规则表 · {{ curName }}` | `规则表 · {{ curName }}` |
| Fact.vue:170 | `<th>规则（必须能判对错）</th>` | `<th>规则（必须能判对错）</th>` |
| Fact.vue:133 | `已进「问人」清单（⑤ 确认答案后自动核过）` | `已进澄清池（答案确认后自动核过）` |
| Fact.vue:201 | `还没有规则——点「提取池中相关材料」` | `还没有规则——点「提取池中相关材料」` |
| Conflict.vue:80 | `② 挑矛盾` | `② 冲突裁决` |
| Conflict.vue:110 | `转问人` | `转澄清` |
| Conflict.vue:56 | `已进「问人」清单` | `已进澄清池` |
| Conflict.vue:112 | `已转问人` | `已转澄清` |
| Conflict.vue:62-64 | `对当前规则全集跑矛盾检测` / `条规则两两比对` | `对当前规则全集跑冲突检测` / `条规则两两比对` |
| Profile.vue:98 | `④ 成用户画像` | `③ 生成画像` |
| Profile.vue:99 | `规则挂到树叶上；挂不上的 = 树缺枝，补。` | `核验通过的规则聚合成需求画像草稿——挂不上的 = 树缺枝，补。` |
| Profile.vue:52 | `AI 组装用户画像：规则挂树…` | `AI 生成画像：规则挂树 · 标置信度 · 并入补充意见…` |
| Profile.vue:113 | `规则就绪…（组装要求全部规则已核验…）` | `规则就绪，点击「AI 生成画像草稿」…（要求全部规则已核验且非「待实证」）` |
| Profile.vue:122 | `规则 {{ card.rules.length }} 条规则` | `画像 {{ card.rules.length }} 条规则` |
| Profile.vue:147 | `未确认项（转「问人」）` | `未确认项（转澄清池）` |
| Gap.vue:89 | `③ 找空白` | `④ 查漏补缺` |
| Gap.vue:38 | `空白 → 「问人」清单` | `缺口 → 澄清池` |
| Gap.vue:111 | `转问人` | `转澄清` |
| Gap.vue:114 | `已转问人` | `已转澄清` |
| Gap.vue:119 | `没有空白记录——…（组装用户画像后扫描更准）` | `没有缺口记录——点「AI 重扫」（先生成画像，扫描更准）` |
| Gap.vue:124 | `找空白 · 维度配置` | `查漏补缺 · 维度配置` |
| Save.vue:88 | `⑥ 存档` | `⑤ 定稿存档` |
| Save.vue:89 | `本节点整理完成 → 用户画像并入项目基线…` | `补充意见重生成终稿，存入项目基线（git commit+tag）。` |
| Save.vue:100 | `规则 {{ asrtCnt }} 条` | `规则 {{ asrtCnt }} 条` |
| Save.vue:103 | `建议先回 ⑤ 问人收口` | `建议先在顶栏澄清池收口` |
| Pool.vue:102 | `// 跳到 ① 提事实查看新规则` | `// 跳到 ① 规则提取查看新规则` |
| Pool.vue:97/100/113 | `提炼行为规则` / `条规则` | `提炼行为规则` / `条规则` |
| App.vue:217 | `某节点整理完成（⑥存档）后出现` | `某节点定稿存档后出现` |
| App.vue:221 | `只重跑该子树的 ①-⑤` | `只重跑该子树的 ①-④ 再重新定稿` |

- [ ] **Step 2: 构建 + 前端测试验证**

Run: `cd web && npm run build && npm run test`
Expected: 均通过（纯文案改动，router.test.ts 不涉）

- [ ] **Step 3: Commit**

```bash
git add web/src/views/ web/src/App.vue
git commit -m "refactor：五视图文案统一（规则→规则、问人→澄清池、步骤序号对齐）"
```

---

### Task 3: 澄清池顶栏化（Ask → 抽屉组件）

**Files:**
- Create: `web/src/components/AskDrawer.vue`（由 `web/src/views/Ask.vue` 迁移改造）
- Delete: `web/src/views/Ask.vue`
- Modify: `web/src/App.vue`、`web/src/router.ts`

**Interfaces:**
- Produces: `AskDrawer` 组件，props `{ open: boolean }`，emits `('close' | 'changed')`；App.vue 顶栏「澄清池」按钮带未答角标。

- [ ] **Step 1: 迁移 Ask.vue → components/AskDrawer.vue**

script 逻辑原样保留（load/answer/verify/copyExport、exportText 去掉 `curName` 引用改为「本批」），模板改为抽屉结构：

```vue
<template>
  <div v-if="open" class="drawer-bg" @click.self="$emit('close')">
    <div class="drawer" role="dialog" aria-modal="true">
      <div class="dw-hd">
        <h3>澄清池 <span class="src">{{ items.length }} 项 · 待问 {{ waiting.length }}</span></h3>
        <button class="ghost" type="button" @click="$emit('close')">✕</button>
      </div>
      <p class="dw-sub">攒一批一次问，给选择题不给问答题——规则提取/冲突裁决/查漏补缺的存疑项都汇到这里。</p>
      <!-- 原 Ask.vue 的 card-box 表格 + 导出预览两块原样搬入，空态文案改为：
           「空——②冲突、④缺口、①无依据规则可转到这里」 -->
    </div>
  </div>
</template>
```

```vue
<style scoped>
.drawer-bg { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 90; }
.drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(720px, 92vw);
  background: #fff; box-shadow: -4px 0 24px rgba(0,0,0,.12); padding: 16px 20px; overflow-y: auto; }
.dw-hd { display: flex; justify-content: space-between; align-items: center; }
.dw-sub { font-size: 12px; color: var(--muted-fg); margin: 4px 0 12px; }
</style>
```

answer/verify 成功后追加 `emit('changed')`（App 重算角标）。onMounted 改为 `watch(() => props.open, v => { if (v) void load() })`。

- [ ] **Step 2: App.vue 集成**

```ts
import AskDrawer from './components/AskDrawer.vue'
import { getClarifications } from './api'
const clarOpen = ref(false)
const clarWait = ref(0)
async function refreshClar() {
  clarWait.value = (await getClarifications()).filter(c => c.st === 'wait').length
}
```

`boot()` 里 `void refreshClar().catch(() => {})`；header 模板（`.baseline-tag` 之后）加：

```html
<button class="ghost clar-btn" type="button" @click="clarOpen = true">
  澄清池<span v-if="clarWait" class="clar-badge">{{ clarWait }}</span>
</button>
<AskDrawer :open="clarOpen" @close="clarOpen = false" @changed="refreshClar" />
```

```css
.clar-btn { position: relative; }
.clar-badge { position: absolute; top: -4px; right: -8px; min-width: 16px; height: 16px;
  border-radius: 8px; background: var(--destructive); color: #fff; font-size: 10px;
  display: flex; align-items: center; justify-content: center; padding: 0 4px; }
```

- [ ] **Step 3: router.ts 移除 v-ask**

`ViewName` 联合类型删 `'v-ask'`；App.vue `VIEW_CMP` 删 `'v-ask': Ask` 行与 import。

- [ ] **Step 4: 构建 + 测试验证**

Run: `cd web && npm run build && npm run test`
Expected: 通过（ViewName 收窄后无残留引用报错）

- [ ] **Step 5: Commit**

```bash
git add web/src/components/AskDrawer.vue web/src/App.vue web/src/router.ts
git rm web/src/views/Ask.vue
git commit -m "feat：问人降为顶栏澄清池（抽屉+未答角标，全程可达）"
```

---

### Task 4: 查漏补缺按当前节点扫描（后端）

**Files:**
- Modify: `server/app/api/router.py:301-309`（rescan_gaps）、`web/src/api.ts:188`、`web/src/views/Gap.vue:44-55`

**Interfaces:**
- Produces: `POST /gaps/rescan?node_path=<数字路径>`——带参时 summary 仅取该节点用户画像；该节点无用户画像 422；不带参保持旧行为（全部用户画像）。`rescanGaps(nodePath?: string)`。

- [ ] **Step 1: 写失败测试（server/tests/test_api.py 追加）**

```python
async def test_gaps_scan_scoped_to_node(client, monkeypatch):
    from app.storage import cards as card_store
    from app.storage.cards import Profile, Rule
    root = ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "风控"})
    card_store.save_profile(root, "支付/放款重试", Profile(node="支付/放款重试", goal="不重复放款"))
    card_store.save_profile(root, "风控", Profile(node="风控", goal="额度不超限"))

    seen = {}
    async def mock_gaps(summary, dims):
        seen["summary"] = summary
        return []
    monkeypatch.setattr(tasks, "gaps", mock_gaps)

    r = await client.post(f"{BASE}/gaps/rescan", params={"node_path": "0,0"})
    assert r.status_code == 200
    assert "不重复放款" in seen["summary"] and "额度不超限" not in seen["summary"]

    r = await client.post(f"{BASE}/gaps/rescan", params={"node_path": "1"})
    assert r.status_code == 422 and "无用户画像" in r.json()["detail"]

    await client.post(f"{BASE}/gaps/rescan")  # 不带参：旧行为全部用户画像
    assert "额度不超限" in seen["summary"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_api.py::test_gaps_scan_scoped_to_node -v`
Expected: FAIL（summary 含全部用户画像 / 422 未实现）

- [ ] **Step 3: 实现 rescan_gaps 节点过滤**

```python
@api_router.post("/gaps/rescan")
async def rescan_gaps(proj: str, node_path: str = ""):
    root = _root(proj)
    dim_list = dims.get_dims(root)
    if node_path:
        nodes = _load_tree(root)
        node, full = _resolve(nodes, node_path)
        if node is None:
            raise HTTPException(status_code=404, detail=f"节点不存在: {node_path}")
        card = cards.load_profile(root, full)
        if card is None:
            raise HTTPException(status_code=422, detail=f"节点无用户画像，请先生成画像: {node_path}")
        summary = _card_summary(card)
    else:
        summary = "\n".join(_card_summary(c) for c in cards.load_all(root)) or "（暂无用户画像）"
    detected = await _ai(tasks.gaps, summary, dim_list)
    detected = [g for g in detected if g.dim in dim_list]
    items = findings.merge_gaps(root, detected)
    return [g.model_dump() for g in items]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_api.py -v`
Expected: 全部 PASS（旧测试不带参不受影响）

- [ ] **Step 5: 前端接线**

`web/src/api.ts`：

```ts
export const rescanGaps = (nodePath?: string) =>
  req<Gap[]>(`/gaps/rescan${nodePath ? `?node_path=${encodeURIComponent(nodePath)}` : ''}`, { method: 'POST' })
```

`Gap.vue` rescan()：开头加 `if (!curPath.value) { toast('先在左侧选中要审查的功能点'); return }`，调用改 `rescanGaps(curPath.value)`。

- [ ] **Step 6: 构建验证 + Commit**

Run: `cd web && npm run build`
Expected: 通过

```bash
git add server/app/api/router.py server/tests/test_api.py web/src/api.ts web/src/views/Gap.vue
git commit -m "fix：查漏补缺扫描限定当前节点用户画像（原误吃全局用户画像）"
```

---

### Task 5: Rule.node 字段与提取归属

**Files:**
- Modify: `server/app/core/models.py:20-30`、`server/app/storage/tree.py`（加 paths）、`server/app/ai/prompts/extract.md`、`server/app/ai/tasks.py:43-49`、`server/app/ai/fake.py:13-18`、`server/app/api/router.py:163-180`（extract_evidence）
- Test: `server/tests/test_api.py`、`server/tests/test_ai_extract.py`

**Interfaces:**
- Produces: `Rule.node: str = ""`（功能点全路径，空=未归类）；`tree.paths(nodes) -> list[str]`（全部节点全路径，树序）；`tasks.extract(content, type, tree_text: str)`（第三参为换行分隔的路径清单文本）。

- [ ] **Step 1: 写失败测试（test_api.py 追加）**

```python
async def test_extract_binds_node_and_sanitizes(client, monkeypatch):
    ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
    await client.post(f"{BASE}/evidence", json={"raw": "重试材料"})

    async def mock_extract(content, evidence_type, tree_text):
        assert "支付/放款重试" in tree_text
        return [Rule(id="E1", text="当超时重试3次", src="retry.py:15", conf="实证",
                          node="支付/放款重试"),
                Rule(id="E2", text="当失败告警", src="log.py:3", conf="实证",
                          node="支付/编造的节点")]  # AI 编造路径
    monkeypatch.setattr(tasks, "extract", mock_extract)

    ev_id = (await client.get(f"{BASE}/evidence")).json()[0]["id"]
    r = await client.post(f"{BASE}/evidence/{ev_id}/extract")
    assert r.status_code == 200
    rows = {a["id"]: a for a in (await client.get(f"{BASE}/rules")).json()}
    assert rows["A1"]["node"] == "支付/放款重试"
    assert rows["A2"]["node"] == ""  # 编造路径被白名单置空
```

```python
async def test_legacy_rules_without_node_load(client):
    # 存量 rules.json 无 node 字段 → 默认 ""，不炸
    import json
    from app.storage import rules as rule_store
    root = ensure_root("演示项目")
    (root / "rules.json").write_text(
        json.dumps([{"id": "A1", "text": "t", "src": "s", "conf": "实证"}], ensure_ascii=False), "utf-8")
    rows = (await client.get(f"{BASE}/rules")).json()
    assert rows[0]["node"] == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_api.py::test_extract_binds_node_and_sanitizes -v`
Expected: FAIL（mock_extract 收到 2 参报 TypeError）

- [ ] **Step 3: 实现**

`models.py` Rule 加字段：

```python
    node: str = ""  # 归属功能点全路径；空 = 未归类（树缺枝探伤器入口）
```

`tree.py` 末尾加：

```python
def paths(nodes: list[Node], prefix: str = "") -> list[str]:
    """全部节点全路径（树序）——extract 归属白名单与前端分组索引共用"""
    out: list[str] = []
    for n in nodes:
        full = f"{prefix}/{n.name}" if prefix else n.name
        out.append(full)
        out.extend(paths(n.children, full))
    return out
```

`prompts/extract.md`：输入段加一段、输出 JSON 加 node 字段、要求加第 7 条：

```markdown
功能树节点清单（node 必须取自其中某行的原文，确定不了就填空字符串）：

{tree_list}
```

输出结构改为 `{{"rules": [{{"id": "E1", "text": "…", "src": "retry.py:15", "conf": "实证", "node": "支付/放款重试"}}]}}`。

`tasks.py`：

```python
async def extract(evidence_content: str, evidence_type: str, tree_text: str) -> list[Rule]:
    out = await complete(
        "extract",
        {"material": evidence_content, "evidence_type": evidence_type, "tree_list": tree_text},
        ExtractOut,
    )
    return out.rules
```

`fake.py`：`async def fake_extract(evidence_content: str, evidence_type: str, tree_text: str)`，返回的规则加 `node=""`。

`router.py` extract_evidence 改：

```python
    nodes = _load_tree(root)
    valid = set(tree.paths(nodes))
    got = await _ai(tasks.extract, _evidence_text(root, ev), ev.type, "\n".join(valid) or "（空树：全部留空）")
    items = [a for a in rule_store.load(root) if a.src_id != ev_id]
    n = max((int(a.id[1:]) for a in items if a.id.startswith("A") and a.id[1:].isdigit()), default=0)
    for a in got:
        n += 1
        if a.node not in valid:
            a.node = ""
        items.append(a.model_copy(update={"id": f"A{n}", "src_id": ev_id}))
```

- [ ] **Step 4: 更新受签名影响的既有测试**

`test_api.py`：`test_end_to_end` 与 `test_verify_correction_written_back` 的 `mock_extract` 改三参 `(content, evidence_type, tree_text)`；`test_end_to_end` 的规则构造加 `node="放款/放款重试"`（树已建好，保证后续 assemble 语义不变）。
`test_ai_extract.py`：`test_extract` 调用改 `await tasks.extract("代码内容", "代码", "支付/放款重试")`，mock 内规则 `variables["tree_list"] == "支付/放款重试"`。

- [ ] **Step 5: 跑定向测试确认通过**

Run: `cd server && uv run pytest tests/test_api.py tests/test_ai_extract.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add server/app/core/models.py server/app/storage/tree.py server/app/ai/prompts/extract.md server/app/ai/tasks.py server/app/ai/fake.py server/app/api/router.py server/tests/test_api.py server/tests/test_ai_extract.py
git commit -m "feat：规则提取绑定节点归属（Rule.node + 提取白名单校验）"
```

---

### Task 6: 规则归属修改 API

**Files:**
- Modify: `server/app/api/router.py`（规则区追加）、`web/src/api.ts`

**Interfaces:**
- Produces: `PUT /rules/{aid}/node`，body `{"node": "支付/放款重试"}`，node 须为空串或树中路径；204。`setRuleNode(id, node)`（Task 9 消费）。

- [ ] **Step 1: 写失败测试（test_api.py 追加）**

```python
async def test_set_assertion_node(client):
    from app.storage import rules as rule_store
    root = ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    rule_store.save(root, [Rule(id="A1", text="t", src="s", conf="实证")])

    r = await client.put(f"{BASE}/rules/A1/node", json={"node": "支付"})
    assert r.status_code == 204
    assert (await client.get(f"{BASE}/rules")).json()[0]["node"] == "支付"

    assert (await client.put(f"{BASE}/rules/A1/node", json={"node": "不存在"})).status_code == 422
    assert (await client.put(f"{BASE}/rules/A1/node", json={"node": ""})).status_code == 204  # 清空回未归类
    assert (await client.put(f"{BASE}/rules/NOPE/node", json={"node": "支付"})).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_api.py::test_set_assertion_node -v`
Expected: FAIL（405/404，路由不存在）

- [ ] **Step 3: 实现（router.py 规则区追加）**

```python
class NodeIn(BaseModel):
    node: str


@api_router.put("/rules/{aid}/node", status_code=204)
async def set_assertion_node(proj: str, aid: str, body: NodeIn):
    """人工挂载/改归属：node 必须为空（回未归类）或树中全路径"""
    root = _root(proj)
    amap = _assert_map(root)
    if aid not in amap:
        raise HTTPException(status_code=404, detail=f"规则不存在: {aid}")
    if body.node and body.node not in tree.paths(_load_tree(root)):
        raise HTTPException(status_code=422, detail=f"节点不存在: {body.node}")
    amap[aid].node = body.node
    rule_store.save(root, list(amap.values()))
```

`api.ts`：

```ts
/** 人工挂载/改归属；node 为空串 = 回未归类 */
export const setRuleNode = (id: string, node: string) =>
  req<void>(`/rules/${encodeURIComponent(id)}/node`, json('PUT', { node }))
```

- [ ] **Step 4: 跑测试确认通过 + Commit**

Run: `cd server && uv run pytest tests/test_api.py::test_set_assertion_node -v && cd ../web && npm run build`
Expected: PASS / 构建通过

```bash
git add server/app/api/router.py server/tests/test_api.py web/src/api.ts
git commit -m "feat：规则归属人工修改端点 PUT /rules/{aid}/node"
```

---

### Task 7: 树节点 priority（后端）

**Files:**
- Modify: `server/app/storage/tree.py`、`server/app/api/router.py:358-383`（mutate_tree）
- Test: `server/tests/test_tree.py`

**Interfaces:**
- Produces: `Node.priority: str`（`""|"P0"|"P1"|"P2"`）；tree.md 行尾标记 ` @P0` 语法（dump 加/parse 剥）；`POST /tree {op:"prio", path, name:"P0"|"P1"|"P2"|""}`。GET /tree 的 model_dump 自动携带 priority。

- [ ] **Step 1: 写失败测试（test_tree.py 追加）**

```python
def test_priority_roundtrip(tmp_path):
    from app.storage import tree
    nodes = [tree.Node(name="支付", priority="P0"),
             tree.Node(name="风控", children=[tree.Node(name="额度", priority="P2")])]
    tree.save(tmp_path, nodes)
    text = (tmp_path / "tree.md").read_text("utf-8")
    assert "- 支付 @P0" in text and "  - 额度 @P2" in text
    back = tree.load(tmp_path)
    assert back[0].priority == "P0" and back[1].children[0].priority == "P2"


def test_priority_suffix_strict(tmp_path):
    from app.storage import tree
    # 名称本身含 @：仅行尾严格 @P0|@P1|@P2 才剥离，其余是名称一部分
    (tmp_path / "tree.md").write_text("- 邮件@公司\n- 支付@P9\n- 风控 @P1\n", "utf-8")
    nodes = tree.load(tmp_path)
    assert nodes[0].name == "邮件@公司" and nodes[0].priority == ""
    assert nodes[1].name == "支付@P9" and nodes[1].priority == ""
    assert nodes[2].name == "风控" and nodes[2].priority == "P1"


def test_priority_legacy_no_suffix(tmp_path):
    from app.storage import tree
    (tmp_path / "tree.md").write_text("- 支付\n", "utf-8")
    assert tree.load(tmp_path)[0].priority == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_tree.py -v -k priority`
Expected: FAIL（Node 无 priority 字段）

- [ ] **Step 3: 实现**

`tree.py`：

```python
import re

class Node(BaseModel):
    name: str
    children: list["Node"] = Field(default_factory=list)
    open: bool = True
    priority: str = ""  # ''|'P0'|'P1'|'P2'：仅前端分组排序展示用，不改树序

_PRIO_RE = re.compile(r"\s*@(P[012])$")
```

parse 中 `node = Node(...)` 一行改为：

```python
        body = raw.lstrip()[2:].strip()
        m = _PRIO_RE.search(body)
        node = Node(name=body[: m.start()] if m else body, priority=m.group(1) if m else "")
```

dump 中 `lines.append(...)` 改为：

```python
            lines.append("  " * depth + "- " + n.name + (f" @{n.priority}" if n.priority else ""))
```

`router.py` mutate_tree：op 分支加（`_PRIO = {"", "P0", "P1", "P2"}` 常量放函数外）：

```python
        elif body.op == "prio":
            if body.path is None:
                raise HTTPException(status_code=422, detail="prio 需要 path")
            if body.name not in _PRIO:
                raise HTTPException(status_code=422, detail="name 必须为 P0/P1/P2 或空串")
            tree.set_priority(nodes, body.path, body.name)
```

`tree.py` 加：

```python
def set_priority(nodes: list[Node], path: str, priority: str) -> None:
    node = find(nodes, path)
    if node is None:
        raise ValueError(f"非法路径: {path}")
    node.priority = priority
```

- [ ] **Step 4: 跑测试确认通过（含全量 tree/api 回归）**

Run: `cd server && uv run pytest tests/test_tree.py tests/test_api.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/storage/tree.py server/app/api/router.py server/tests/test_tree.py
git commit -m "feat：树节点重要度 P0/P1/P2（tree.md 行尾标记 + prio 操作）"
```

---

### Task 8: 生成画像按节点过滤规则

**Files:**
- Modify: `server/app/api/router.py:395-407`（assemble_card）
- Test: `server/tests/test_api.py`

**Interfaces:**
- Consumes: Task 5 的 `Rule.node`。

- [ ] **Step 1: 写失败测试（test_api.py 追加）**

```python
async def test_assemble_filters_by_node(client, monkeypatch):
    from app.storage import rules as rule_store
    root = ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "风控"})
    rule_store.save(root, [
        Rule(id="A1", text="重试3次", src="r.py:1", conf="实证", verified=True, node="支付/放款重试"),
        Rule(id="A2", text="风控拦截", src="r.py:2", conf="实证", verified=True, node="风控"),
        Rule(id="A3", text="未归类规则", src="r.py:3", conf="实证", verified=True, node=""),
    ])
    seen = {}
    async def mock_assemble(rules, node_name, note):
        seen["ids"] = [a.id for a in rules]
        return Profile(node=node_name, goal="g")
    monkeypatch.setattr(tasks, "assemble", mock_assemble)

    r = await client.post(f"{BASE}/profiles/assemble", json={"node_path": "0,0", "note": ""})
    assert r.status_code == 200 and seen["ids"] == ["A1"]  # 只吃本节点规则


async def test_assemble_empty_rules_ok(client, monkeypatch):
    # 节点无任何归属规则 → 空规则集组装不 500（AI 仍产出画像框架）
    ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    async def mock_assemble(rules, node_name, note):
        assert rules == []
        return Profile(node=node_name, goal="g")
    monkeypatch.setattr(tasks, "assemble", mock_assemble)
    r = await client.post(f"{BASE}/profiles/assemble", json={"node_path": "0", "note": ""})
    assert r.status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_api.py::test_assemble_filters_by_node -v`
Expected: FAIL（seen ids 含 A1/A2/A3）

- [ ] **Step 3: 实现（assemble_card 一行过滤）**

```python
    void = _void_ids(root)
    usable = [a for a in rule_store.load(root) if a.id not in void and a.node == full]
```

同步更新既有 `test_assemble_excludes_voided_rules`：三条 Rule 构造加 `node="放款"`（node_path "0" 的 full 即「放款」）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_api.py -v`
Expected: 全部 PASS（test_end_to_end 在 Task 5 已带 node）

- [ ] **Step 5: Commit**

```bash
git add server/app/api/router.py server/tests/test_api.py
git commit -m "fix：生成画像只组装当前节点规则（修多节点 R# 污染，M1.x 偏差#4 关闭）"
```

---

### Task 9: 规则表分组视图（grouping.ts + Fact.vue 重构）

**Files:**
- Create: `web/src/grouping.ts`、`web/src/grouping.test.ts`
- Modify: `web/src/views/Fact.vue`、`web/src/api.ts:36-46`（Rule 加 node）

**Interfaces:**
- Consumes: Task 5 的 `a.node`、Task 7 的 `TreeNode.priority`、Task 6 的 `setRuleNode`。
- Produces: `buildGroups(rules, tree)` → `{ groups: RuleGroup[]; unclassified: Rule[] }`（类型见 Step 1）。

- [ ] **Step 1: 写失败测试（grouping.test.ts）**

```ts
import { describe, expect, it } from 'vitest'
import { buildGroups } from './grouping'
import type { Rule, TreeNode } from './api'

const A = (id: string, node: string, verified = true): Rule =>
  ({ id, text: id, src: 's', conf: '实证', st: 'open', verified, suspect: false, node })

const TREE: TreeNode[] = [
  { name: '支付', children: [{ name: '放款重试', children: [], open: true, priority: 'P1' }], open: true, priority: '' },
  { name: '风控', children: [{ name: '额度', children: [], open: true, priority: 'P0' },
    { name: '黑名单', children: [], open: true, priority: '' }], open: true, priority: 'P2' },
]

describe('buildGroups', () => {
  it('按父路径分组，功能点挂父组', () => {
    const { groups, unclassified } = buildGroups([A('A1', '支付/放款重试'), A('A2', '风控/额度')], TREE)
    expect(unclassified).toHaveLength(0)
    const pay = groups.find(g => g.label === '支付')!
    expect(pay.nodes.map(n => n.path)).toEqual(['支付/放款重试'])
    expect(pay.nodes[0].rules.map(r => r.id)).toEqual(['A1'])
  })
  it('组内功能点按 P0→P1→P2→空 再按树序', () => {
    const { groups } = buildGroups([A('A1', '风控/额度'), A('A2', '风控/黑名单')], TREE)
    expect(groups.find(g => g.label === '风控')!.nodes.map(n => n.name)).toEqual(['额度', '黑名单'])
  })
  it('顶层功能点（无父）进「（未分组）」且置顶', () => {
    const tree: TreeNode[] = [{ name: '放款', children: [], open: true, priority: '' }]
    const { groups } = buildGroups([A('A1', '放款')], tree)
    expect(groups[0].label).toBe('（未分组）')
  })
  it('node 失配（改名残留）与空 node 都进未归类，不丢', () => {
    const { unclassified } = buildGroups([A('A1', ''), A('A2', '已被改名/旧路径')], TREE)
    expect(unclassified.map(a => a.id)).toEqual(['A1', 'A2'])
  })
  it('组头统计：核验 n/m', () => {
    const { groups } = buildGroups([A('A1', '风控/额度'), A('A2', '风控/额度', false)], TREE)
    const n = groups.find(g => g.label === '风控')!.nodes[0]
    expect(n.rules.length).toBe(2)
    expect(n.rules.filter(r => r.verified).length).toBe(1)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test`
Expected: FAIL（grouping.ts 不存在）

- [ ] **Step 3: 实现 grouping.ts**

```ts
// 规则表分组：按 模块（父路径）› 功能点 两级聚合；组内功能点按 P0→P1→P2→空、再按树序。
// 失配归属（节点改名残留）与空 node 均进 unclassified，由人工重新挂载。
import type { Rule, TreeNode } from './api'

export interface GroupedPoint {
  path: string
  name: string
  priority: string
  order: number
  rules: Rule[]
}
export interface RuleGroup {
  key: string
  label: string
  order: number
  nodes: GroupedPoint[]
}
export interface GroupResult {
  groups: RuleGroup[]
  unclassified: Rule[]
}

const PRIO_RANK: Record<string, number> = { P0: 0, P1: 1, P2: 2, '': 3 }

interface Index {
  path: string
  name: string
  parent: string // 父路径；顶层节点为 ''
  priority: string
  order: number
}

function indexTree(nodes: TreeNode[], prefix = '', counter = { n: 0 }): Index[] {
  const out: Index[] = []
  for (const nd of nodes) {
    const path = prefix ? `${prefix}/${nd.name}` : nd.name
    out.push({ path, name: nd.name, parent: prefix, priority: nd.priority ?? '', order: counter.n++ })
    out.push(...indexTree(nd.children, path, counter))
  }
  return out
}

export function buildGroups(rules: Rule[], treeNodes: TreeNode[]): GroupResult {
  const idx = indexTree(treeNodes)
  const byPath = new Map(idx.map(i => [i.path, i]))
  const rulesOf = new Map<string, Rule[]>()
  const unclassified: Rule[] = []
  for (const r of rules) {
    if (r.node && byPath.has(r.node)) {
      const arr = rulesOf.get(r.node) ?? []
      arr.push(r)
      rulesOf.set(r.node, arr)
    } else {
      unclassified.push(r)
    }
  }
  const groupMap = new Map<string, RuleGroup>()
  for (const i of idx) {
    const rs = rulesOf.get(i.path)
    if (!rs?.length) continue
    const g =
      groupMap.get(i.parent) ??
      ({ key: i.parent, label: i.parent || '（未分组）', order: -1, nodes: [] } as RuleGroup)
    g.nodes.push({ path: i.path, name: i.name, priority: i.priority, order: i.order, rules: rs })
    groupMap.set(i.parent, g)
  }
  const groups = [...groupMap.values()]
  for (const g of groups) {
    g.order = idx.find(i => i.path === (g.nodes[0] as GroupedPoint).path)!.order
    g.nodes.sort((a, b) => PRIO_RANK[a.priority] - PRIO_RANK[b.priority] || a.order - b.order)
  }
  groups.sort((a, b) => (a.key === '' ? -1 : b.key === '' ? 1 : a.order - b.order))
  return { groups, unclassified }
}
```

注意：`api.ts` 的 `TreeNode` 与 `Rule` 先加 `priority?: string`、`node?: string` 字段；Index 接口如上只含五个字段，不引入未用属性。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test`
Expected: grouping.test.ts 全 PASS

- [ ] **Step 5: Fact.vue 重构（数据流与模板骨架）**

script 增加：`const treeNodes = ref<TreeNode[]>([])`（load 里并入 `getTree()`）、`const { groups, unclassified } = computed(() => buildGroups(items.value, treeNodes.value))`、折叠状态 `const collapsed = ref<Record<string, boolean>>({})`、挂载函数：

```ts
async function assign(a: Rule, node: string) {
  try {
    await setRuleNode(a.id, node)
    await load()
    toast(node ? `${a.id} → 已挂 ${node}` : `${a.id} → 已移回未归类`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `挂载失败：${e.message}` : '挂载失败', 'warn')
  }
}
```

模板：原单层 `<table>` 改为按 `groups` 循环——组头行（`g.label` + 折叠开关，`collapsed[g.key]` 控制）、组内每个功能点一个小节头（`n.path` + `P0/P1/P2` 徽章 + `核验 x/y`，x=`n.rules.filter(r=>r.verified).length`）+ 该功能点规则表格（列结构与原表完全一致，行的核/人工过/转澄清按钮不变）。顶部 statbar 保留。分组之后放未归类桶（置底常显）：

```html
<div class="card-box unclass-box">
  <div class="hd">未归类 · {{ unclassified.length }} 条
    <span class="sub" style="font-weight: 400">树缺枝的探伤器——左侧补节点后行内选归属</span></div>
  <table><!-- 同列结构；行尾加： -->
    <td><select :value="a.node" @change="assign(a, ($event.target as HTMLSelectElement).value)">
      <option value="">（选功能点挂载）</option>
      <option v-for="p in allPaths" :key="p" :value="p">{{ p }}</option>
    </select></td>
  </table>
</div>
```

`allPaths = computed(() => paths 前端版：walk treeNodes 收集全路径，2 空格缩进/层)`。普通分组行同样附该 select（`assign` 改归属/移回）。

- [ ] **Step 6: 构建 + 手动验证点 + Commit**

Run: `cd web && npm run build && npm run test`
Expected: 通过。手动（dev 起后）：风控云项目规则表出现「风控云›功能点」分组；未归类规则可选路径挂载；核验按钮行为不变。

```bash
git add web/src/grouping.ts web/src/grouping.test.ts web/src/views/Fact.vue web/src/api.ts
git commit -m "feat：规则表按模块›功能点分组（重要度排序+未归类桶+行内挂载）"
```

---

### Task 10: 侧栏 priority 徽章与标记

**Files:**
- Modify: `web/src/components/FuncTree.vue`、`web/src/App.vue:121-143`、`web/src/api.ts:100`

**Interfaces:**
- Consumes: Task 7 的 `op:"prio"`。
- Produces: 徽章点击循环 `'' → P0 → P1 → P2 → ''`。

- [ ] **Step 1: api.ts 类型与调用**

`TreeOpName` 加 `'prio'`（`treeOp` 已透传 name，无需改函数体）。

- [ ] **Step 2: FuncTree.vue 节点行加优先级按钮**

emit 类型扩展：`op: [op: 'add' | 'rename' | 'del' | 'prio', path: string]`（App.onOp 的 op 参数联合类型同步加 `'prio'`）。节点名后加按钮——有档位显示徽章、无档位显示浅色 ☆，点击都 emit `('op', 'prio', path)`：

```html
<span class="prio-badge" :class="node.priority ? `p-${node.priority}` : 'p-none'"
  :title="`重要度 ${node.priority || '未标'}（点击切换）`" @click.stop="emit('op', 'prio', path)"
>{{ node.priority || '☆' }}</span>
```

```css
.prio-badge { font-size: 9.5px; font-weight: 700; padding: 1px 4px; border-radius: 4px;
  margin-left: 4px; cursor: pointer; }
.p-P0 { background: var(--red-bg); color: var(--destructive); }
.p-P1 { background: #fff4e0; color: #b8860b; }
.p-P2 { background: var(--muted); color: var(--muted-fg); }
.p-none { color: var(--border2); }
```

- [ ] **Step 3: App.vue onOp 加 prio 分支**

```ts
    } else if (op === 'prio') {
      const n = findNode(path)
      if (!n) return
      const NEXT: Record<string, string> = { '': 'P0', P0: 'P1', P1: 'P2', P2: '' }
      await treeOp('prio', path, NEXT[n.priority ?? ''] ?? 'P0')
```

- [ ] **Step 4: 构建 + Commit**

Run: `cd web && npm run build`
Expected: 通过。手动：点徽章循环变色，刷新后保持（tree.md 落 ` @P0`）。

```bash
git add web/src/components/FuncTree.vue web/src/App.vue web/src/api.ts
git commit -m "feat：功能树节点重要度徽章（点击循环 P0/P1/P2）"
```

---

### Task 11: 定稿存档页补「重生成终稿」

**Files:**
- Modify: `web/src/views/Save.vue`

**Interfaces:**
- Consumes: `assemble(nodePath, note)`（api.ts 已有）、`curPath`。

- [ ] **Step 1: Save.vue 增交互**

script：`import { assemble } from '../api'`、`const note = ref('')`、`const regen = ref(false)`；

```ts
async function regenerate() {
  if (!curPath.value) { toast('先在左侧选中功能点'); return }
  regen.value = true
  try {
    await assemble(curPath.value, note.value)
    toast('终稿已按补充意见重新生成', 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `重生成失败：${e.message}` : '重生成失败', 'warn')
  } finally { regen.value = false }
}
```

模板（存基线按钮之前）加一块：

```html
<div class="card-box">
  <div class="hd">补充意见重生成终稿 · {{ curName }}</div>
  <div class="bd">
    <textarea v-model="note" rows="2" placeholder="AI 不知道的口头约定、历史坑、业务约束——并入画像「补充说明」并影响规则" />
    <button class="btn" type="button" :disabled="regen" @click="regenerate">
      {{ regen ? 'AI 重新生成中…' : '重新生成终稿' }}</button>
  </div>
</div>
```

- [ ] **Step 2: 构建 + Commit**

Run: `cd web && npm run build`
Expected: 通过

```bash
git add web/src/views/Save.vue
git commit -m "feat：定稿页并入补充意见重生成终稿"
```

---

### Task 12: outline AI 任务（骨架生成）

**Files:**
- Create: `server/app/ai/prompts/outline.md`
- Modify: `server/app/ai/tasks.py`、`server/app/ai/fake.py`

**Interfaces:**
- Produces: `tasks.outline(material: str) -> list[OutlineNode]`；`OutlineNode(name: str, children: list[OutlineNode])`（router 转 `tree.Node`）。

- [ ] **Step 1: 写失败测试（test_ai_extract.py 追加）**

```python
async def test_outline(monkeypatch):
    fake = tasks.OutlineOut(nodes=[tasks.OutlineNode(name="支付", children=[
        tasks.OutlineNode(name="放款重试", children=[])])])
    async def mock(task, variables, schema):
        assert "材料" in variables["material"]
        return fake
    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.outline("材料内容")
    assert out[0].name == "支付" and out[0].children[0].name == "放款重试"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_ai_extract.py::test_outline -v`
Expected: FAIL（OutlineOut 不存在）

- [ ] **Step 3: 实现**

`prompts/outline.md`：

```markdown
你是一名资深测试工程师，正在为需求逆向整理搭功能树骨架：从材料中归纳 系统›模块›功能点 的层级结构。

## 输入

材料内容：

{material}

## 要求

1. 只依据材料中出现的功能线索归纳，不臆造材料未提及的模块。
2. 层级 2-3 层：顶层为业务模块（3-8 个），其下为功能点（每模块 2-6 个）；材料单薄时宁可少不可编。
3. 名称 2-8 个字，名词短语，不带编号和标点。
4. children 为空时输出空数组。

## 输出

只输出一个 JSON 对象，不输出其他文字：

{{"nodes": [{{"name": "支付", "children": [{{"name": "放款重试", "children": []}}]}}]}}
```

`tasks.py` 追加：

```python
class OutlineNode(BaseModel):
    name: str
    children: list["OutlineNode"] = []


class OutlineOut(BaseModel):
    nodes: list[OutlineNode]


async def outline(material: str) -> list[OutlineNode]:
    out = await complete("outline", {"material": material}, OutlineOut)
    return out.nodes
```

`fake.py` 追加并挂载：

```python
async def fake_outline(material: str) -> list[tasks.OutlineNode]:
    return [tasks.OutlineNode(name="支付", children=[
        tasks.OutlineNode(name="放款重试", children=[]),
        tasks.OutlineNode(name="回调处理", children=[]),
    ])]

# install() 中追加：
    tasks.outline = fake_outline
```

- [ ] **Step 4: 跑测试确认通过 + Commit**

Run: `cd server && uv run pytest tests/test_ai_extract.py -v`
Expected: PASS

```bash
git add server/app/ai/prompts/outline.md server/app/ai/tasks.py server/app/ai/fake.py server/tests/test_ai_extract.py
git commit -m "feat：AI 树骨架任务 outline（证据池→模块›功能点层级）"
```

---

### Task 13: POST /tree/scaffold 路由

**Files:**
- Modify: `server/app/api/router.py`（树区追加）、`web/src/api.ts`

**Interfaces:**
- Consumes: Task 12 的 `tasks.outline`。
- Produces: `POST /tree/scaffold`——树空且证据池有可提取材料时生成骨架并落盘，返回节点列表；非空树 409；无可提取材料 422。`scaffoldTree()`（Task 14 消费）。

- [ ] **Step 1: 写失败测试（test_api.py 追加）**

```python
async def test_tree_scaffold(client, monkeypatch):
    ensure_root("演示项目")
    await client.post(f"{BASE}/evidence", json={"raw": "支付模块支持放款重试与回调处理。"})
    await client.post(f"{BASE}/evidence", content=b"\x89PNG",
                      headers={"content-type": "application/octet-stream", "x-filename": "s.png"})

    async def mock_outline(material):
        assert "放款重试" in material  # 拼接的是文本材料，截图只有文件名不入正文
        return [tasks.OutlineNode(name="支付", children=[
            tasks.OutlineNode(name="放款重试", children=[])])]
    monkeypatch.setattr(tasks, "outline", mock_outline)

    r = await client.post(f"{BASE}/tree/scaffold")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "支付"
    assert (ensure_root("演示项目") / "tree.md").exists()

    r = await client.post(f"{BASE}/tree/scaffold")  # 树已非空：拒绝覆盖
    assert r.status_code == 409


async def test_tree_scaffold_empty_pool(client):
    ensure_root("演示项目")
    r = await client.post(f"{BASE}/tree/scaffold")
    assert r.status_code == 422 and "可提取" in r.json()["detail"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_api.py::test_tree_scaffold -v`
Expected: FAIL（404 路由不存在）

- [ ] **Step 3: 实现（router.py 树区追加）**

```python
def _to_tree_nodes(items) -> list[tree.Node]:
    return [tree.Node(name=i.name, children=_to_tree_nodes(i.children)) for i in items]


@api_router.post("/tree/scaffold")
async def scaffold_tree(proj: str):
    """AI 从证据池生成功能树骨架（仅树空时可用；生成后人工在侧栏调整即采纳）"""
    root = _root(proj)
    if _load_tree(root):
        raise HTTPException(status_code=409, detail="功能树非空，不覆盖——如需调整请在左侧手工编辑")
    texts = [_evidence_text(root, e) for e in await evidence.list_all(root)
             if e.type not in ("截图", "压缩包")]
    if not texts:
        raise HTTPException(status_code=422, detail="证据池没有可提取材料，请先入池")
    material = "\n\n".join(t[:8000] for t in texts)  # 每份截断防超长
    items = await _ai(tasks.outline, material)
    nodes = _to_tree_nodes(items)
    tree.save(root, nodes)
    return [n.model_dump() for n in nodes]
```

`api.ts`：

```ts
/** AI 从证据池生成树骨架（仅树空时；后端 409/422 抛 ApiError） */
export const scaffoldTree = () => req<TreeNode[]>('/tree/scaffold', { method: 'POST' })
```

- [ ] **Step 4: 跑测试确认通过 + Commit**

Run: `cd server && uv run pytest tests/test_api.py -v && cd ../web && npm run build`
Expected: 全部 PASS / 构建通过

```bash
git add server/app/api/router.py server/tests/test_api.py web/src/api.ts
git commit -m "feat：POST /tree/scaffold AI 骨架生成（树空保护+材料截断）"
```

---

### Task 14: 树空拦截与骨架引导（前端）

**Files:**
- Modify: `web/src/views/Fact.vue`、`web/src/App.vue`

**Interfaces:**
- Consumes: Task 13 的 `scaffoldTree()`、Task 9 的 `treeNodes`。
- Produces: App.vue `provide('reloadTree', loadTree)`（Fact 消费刷新侧栏）。

- [ ] **Step 1: App.vue 暴露树刷新**

`loadTree` 定义后加 `provide('reloadTree', loadTree)`（import 已有 provide）。

- [ ] **Step 2: Fact.vue 树空引导块**

script：

```ts
const reloadTree = inject<() => Promise<void>>('reloadTree', async () => {})
const scaffolding = ref(false)
async function genScaffold() {
  scaffolding.value = true
  try {
    await scaffoldTree()
    await Promise.all([reloadTree(), load()])
    toast('骨架已生成——请在左侧检查调整后开始提取', 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `生成失败：${e.message}` : '生成失败', 'warn')
  } finally { scaffolding.value = false }
}
```

模板（视图头与统计条之间）：

```html
<div v-if="!treeNodes.length" class="card-box scaffold-guide">
  <div class="hd">功能树还没有骨架</div>
  <div class="bd">
    规则要挂到功能点上——先搭骨架：手工在左侧添加节点，或让 AI 从证据池材料归纳。
    <div style="margin-top: 8px; display: flex; gap: 8px">
      <button class="btn-ghost" type="button" @click="toast('在左侧「＋ 根节点」开始手工搭建')">手工在左侧搭建</button>
      <button class="btn-accent" type="button" :disabled="scaffolding || !evidence.length"
        :title="!evidence.length ? '证据池为空，请先入池' : ''" @click="genScaffold">
        {{ scaffolding ? 'AI 归纳中…' : 'AI 从证据池生成' }}</button>
    </div>
  </div>
</div>
```

（`evidence` 已在 Fact.vue 现有数据中；树空时下方规则区显示空态。）

- [ ] **Step 3: 构建 + 手动验证 + Commit**

Run: `cd web && npm run build && npm run test`
Expected: 通过。手动：新建项目→①规则提取见引导块；池空时 AI 按钮置灰；生成后侧栏出现树。

```bash
git add web/src/views/Fact.vue web/src/App.vue
git commit -m "feat：规则提取树空拦截引导（手工/AI 骨架）"
```

---

## 收尾验证（全部任务完成后）

- [ ] `cd server && uv run pytest`（全量一次，最终验证）
- [ ] `cd web && npm run build && npm run test`
- [ ] 手动端到端：新建项目 → 入池材料 → ①树空引导 → AI 骨架 → 提取（规则分组+未归类挂载）→ 核验 → ②冲突裁决 → ③生成画像 → ④查漏补缺（当前节点）→ 顶栏澄清池回收 → ⑤定稿存档 → 基线出现。
