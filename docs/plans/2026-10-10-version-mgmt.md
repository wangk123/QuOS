# 版本管理优化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 版本基线从自增 `vN` 升级为手动 `x.x.x` 版本号 + 版本说明 + 回滚/废弃 + 预览 markdown 渲染模式。

**Architecture:** 后端沿用「版本 = data 目录 git tag」模型（`gitops.py` 四函数：save/list/restore/delete），router 挂四个端点；前端 `VerModal.vue` 重构交互（表单替代 window.prompt、行操作、确认弹层），预览渲染走新增受限 md 渲染器 `web/src/utils/md.ts`（无依赖、全量 escape）。

**Tech Stack:** FastAPI + Pydantic（server，uv 运行）；Vue 3 `<script setup>` + vitest + @vue/test-utils（web）。

**Spec:** `docs/specs/2026-10-10-version-mgmt-design.md`（设计裁定与边界以 spec 为准；原型 `reports/version-preview/index.html`）

## Global Constraints

- 不新增任何依赖（前后端均零新包）。
- 版本说明纯文本不渲染 markdown；「不支持 markdown」仅限版本说明，预览文档要渲染。
- 版本号校验三规则：`^\d+\.\d+\.\d+$`；不与已有版本重复；不低于列表最大**新格式**版本（旧 `vN` 不参与下限）。
- 「当前」徽章 = tag commit == HEAD（`cur` 字段），不依赖列表末位。
- 行数上限：组件/模块 500 行、工具 300 行。
- 文案中文；动作命名统一「新增版本」。
- 测试只跑定向（server: uv run pytest 指定文件；web: npx vitest run 指定文件）。
- Commit：本任务全部完成后一条 `feat：版本管理优化——手动版本号 x.x.x+说明+回滚废弃+预览 markdown 渲染`（用户裁定的大任务单条粒度，各 task 不单独 commit）。

## Review Focus

spec 未显式列出、但最可能咬人的输入类——每个都有对应测试钉住：

1. **带 `v` 前缀的版本号输入**（`v1.2.3`，用户惯性）→ 必须被格式规则拒绝（422），不能静默造出 `vv1.2.3` tag。→ Task 1 测试 `test_save_rejects_v_prefix`
2. **规则文本含 HTML**（`<script>`、`<img onerror>`，规则源自材料与用户输入）→ md 渲染必须全量 escape，v-html 无注入面。→ Task 6 测试 `test_escapes_html`
3. **表格单元格 `\|` 转义**（`profiles.py` 写出 `r.text.replace("|", "\\|")`）→ 渲染须还原为字面 `|`，不得劈裂单元格。→ Task 6 测试 `test_table_pipe_escape`
4. **回滚后「当前」位置**（reset --hard 后 HEAD 在中间版本）→ `cur` 徽章跟 HEAD 走，列表末项不自动是当前。→ Task 3 测试 `test_restore_marks_cur`、Task 7 组件测试
5. **旧 `vN` 项目继续用**（存量 tag 为 `v1,v2`）→ 列表兼容混排（`(N,0,0)` 排序）、可回滚/废弃、新存 `1.0.0` 不被旧 `v5` 卡倒挂下限。→ Task 1/2 测试

---

### Task 1: gitops — save_baseline 手动版本号与三规则校验

**Files:**
- Modify: `server/app/storage/gitops.py`
- Test: `server/tests/test_gitops.py`（新建）

**Interfaces:**
- Produces: `save_baseline(root, version: str, note: str) -> dict`，返回 `{"commit", "tag", "version"}`；校验失败抛 `ValueError`（消息即 422 detail）。`_semver(tag) -> tuple[int,int,int] | None`、`_sort_key(tag)` 供 Task 2 复用。

- [ ] **Step 1: 写失败测试**

新建 `server/tests/test_gitops.py`：

```python
# gitops 直测：tmp 真仓库覆盖版本号三规则（API 视角在 test_api.py）
import pytest
from app.storage import gitops


@pytest.fixture
def root(tmp_path):
    (tmp_path / "evidence.json").write_text("{}", "utf-8")
    return tmp_path


def test_save_version_tag_and_return(root):
    r = gitops.save_baseline(root, "1.2.3", "首个语义化版本")
    assert r["tag"] == "v1.2.3" and r["version"] == "1.2.3" and len(r["commit"]) >= 7


def test_save_rejects_bad_format(root):
    for bad in ["v1.2.3", "1.2", "1.2.3.4", "a.b.c", ""]:
        with pytest.raises(ValueError, match="格式"):
            gitops.save_baseline(root, bad, "x")


def test_save_rejects_duplicate(root):
    gitops.save_baseline(root, "1.0.0", "一")
    with pytest.raises(ValueError, match="已存在"):
        gitops.save_baseline(root, "1.0.0", "二")


def test_save_rejects_lower_than_max(root):
    gitops.save_baseline(root, "1.2.1", "一")
    for low in ["1.2.0", "1.1.9", "0.9.9"]:
        with pytest.raises(ValueError, match="不得低于"):
            gitops.save_baseline(root, low, "二")


def test_save_allows_high_version_with_legacy_tags(root):
    """旧 vN 不参与倒挂下限：存量 v5 仍可存 1.0.0"""
    gitops._git(root, "init")
    gitops._git(root, "add", "-A")
    gitops._git(root, "commit", *gitops._commit_args(root), "-m", "旧存档")
    gitops._git(root, "tag", "v5")
    r = gitops.save_baseline(root, "1.0.0", "新起点")
    assert r["tag"] == "v1.0.0"


def test_save_without_changes_still_tags(root):
    gitops.save_baseline(root, "1.0.0", "一")
    r = gitops.save_baseline(root, "1.0.1", "无变更")
    assert r["tag"] == "v1.0.1" and r["commit"]  # 无变更 tag 指向当前 commit
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_gitops.py -v`
Expected: FAIL（`save_baseline() takes 3 positional arguments but 4 were given`）

- [ ] **Step 3: 实现**

`gitops.py`：加模块级正则与辅助、改 `save_baseline`（删除自增 vN 逻辑）：

```python
_VER = re.compile(r"\d+\.\d+\.\d+")


def _semver(tag: str) -> tuple[int, int, int] | None:
    """新格式 v{x.y.z} → 三元组；其余（旧 vN 等）→ None"""
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(int(x) for x in m.groups()) if m else None


def _sort_key(tag: str) -> tuple[int, int, int]:
    """时间线排序键：新格式语义化；旧 vN 映射 (N,0,0)；兜底 0"""
    return _semver(tag) or ((int(re.sub(r"\D", "", tag) or 0) or 0, 0, 0))
```

```python
def save_baseline(root, version: str, note: str) -> dict:
    root = Path(root)
    if not _VER.fullmatch(version):
        raise ValueError(f"版本号格式须为 x.y.z（三段数字）: {version}")
    tags = _tags(root)
    tag = f"v{version}"
    if any(t["tag"] == tag for t in tags):
        raise ValueError(f"版本号已存在: {version}")
    max_new = max((s for s in (_semver(t["tag"]) for t in tags) if s), default=None)
    if max_new and tuple(int(x) for x in version.split(".")) <= max_new:
        raise ValueError(f"版本号不得低于已有最大版本 {'.'.join(map(str, max_new))}")
    if not (root / ".git").exists():
        _git(root, "init")
    _git(root, "add", "-A")
    if _git(root, "status", "--porcelain"):  # 无变更时跳过 commit
        _git(root, "commit", *_commit_args(root), "-m", note)
    commit = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", tag)
    return {"commit": commit, "tag": tag, "version": version}
```

注意 `_sort_key` 兜底分支 `(int(...) or 0, 0, 0)`：tag 无数字（如 `foo`）时 `int('')` 报错，`re.sub` 结果空串转 0。旧 `_tags` 内的数字排序改用 `_sort_key`（`tags.sort(key=lambda x: _sort_key(x["tag"]))`），为 Task 2 铺路。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_gitops.py -v`
Expected: 6 PASS

---

### Task 2: gitops — list_baselines 补 time/note/cur 与语义化排序

**Files:**
- Modify: `server/app/storage/gitops.py`
- Test: `server/tests/test_gitops.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `_sort_key`。
- Produces: `list_baselines(root) -> list[dict]`，每项 `{"tag", "commit", "note", "time"(unix 秒 int), "cur"(bool)}`，升序；Task 4 的 GET /baseline 直接返回它。

- [ ] **Step 1: 追加失败测试**

```python
def test_list_fields_and_semver_order(root):
    gitops.save_baseline(root, "1.0.0", "第一版说明")
    c1 = gitops._git(root, "rev-list", "-n1", "HEAD")
    (root / "rules.json").write_text("[]", "utf-8")
    gitops.save_baseline(root, "1.2.0", "第二版")
    gitops._git(root, "tag", "v0", c1)  # 旧格式混排：v0 指向 1.0.0 的 commit → (0,0,0) 排最前且非当前
    items = gitops.list_baselines(root)
    assert [i["tag"] for i in items] == ["v0", "v1.0.0", "v1.2.0"]
    assert items[2]["note"] == "第二版" and items[2]["time"] > 0
    assert items[2]["cur"] is True and items[0]["cur"] is False  # HEAD 所指=当前


def test_list_empty_without_git(root):
    assert gitops.list_baselines(root) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_gitops.py -v`
Expected: 新增 2 条 FAIL（`KeyError: 'note'` / dict 无 cur 字段）

- [ ] **Step 3: 实现**

替换 `list_baselines`（`_tags` 保持 tag/commit 精简，列表字段在此补齐）：

```python
def list_baselines(root) -> list[dict]:
    root = Path(root)
    if not (root / ".git").exists():
        return []
    out = _git(root, "for-each-ref", "refs/tags", "--format="
               "%(refname:short)%00%(objectname)%00%(contents:subject)%00%(committerdate:unix)")
    head = _git(root, "rev-parse", "HEAD")
    items = []
    for line in out.splitlines():
        if not line.strip():
            continue
        tag, commit, note, ts = line.split("\x00")
        items.append({"tag": tag, "commit": commit, "note": note,
                      "time": int(ts), "cur": commit == head})
    items.sort(key=lambda x: _sort_key(x["tag"]))
    return items
```

轻量 tag 的 `contents:*` / `committerdate:*` 会自动 peel 到指向的 commit——note 即存版时的 commit message，time 即提交时间。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_gitops.py -v`
Expected: 8 PASS

---

### Task 3: gitops — restore_baseline / delete_baseline

**Files:**
- Modify: `server/app/storage/gitops.py`
- Test: `server/tests/test_gitops.py`（追加）

**Interfaces:**
- Produces: `restore_baseline(root, tag: str) -> None`（tag 不存在抛 `KeyError`）；`delete_baseline(root, tag: str) -> None`（幂等，不存在也成功）。

- [ ] **Step 1: 追加失败测试**

```python
def test_restore_resets_content_and_cleans(root):
    gitops.save_baseline(root, "1.0.0", "一")
    (root / "rules.json").write_text('["新版内容"]', "utf-8")
    (root / "untracked.txt").write_text("未存版文件", "utf-8")
    gitops.restore_baseline(root, "v1.0.0")
    assert not (root / "rules.json").exists()      # 回到该版没有此文件
    assert not (root / "untracked.txt").exists()   # 未跟踪文件被清理
    assert gitops.list_baselines(root)[0]["cur"] is True  # HEAD 回到该版


def test_restore_unknown_tag_raises(root):
    gitops.save_baseline(root, "1.0.0", "一")
    with pytest.raises(KeyError):
        gitops.restore_baseline(root, "v9.9.9")


def test_delete_removes_tag_keeps_commit(root):
    gitops.save_baseline(root, "1.0.0", "一")
    commit = gitops.list_baselines(root)[0]["commit"]
    gitops.delete_baseline(root, "v1.0.0")
    assert gitops.list_baselines(root) == []
    assert gitops._git(root, "cat-file", "-t", commit) == "commit"  # 数据仍在 git 历史
    gitops.delete_baseline(root, "v1.0.0")  # 幂等
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_gitops.py -v`
Expected: 新增 3 条 FAIL（`AttributeError: ... no attribute 'restore_baseline'`）

- [ ] **Step 3: 实现**

```python
def restore_baseline(root, tag: str) -> None:
    """工作区完整回到该版：reset --hard + 清未跟踪文件（未存版修改丢弃，已裁定）"""
    root = Path(root)
    if tag not in {t["tag"] for t in _tags(root)}:
        raise KeyError(tag)
    _git(root, "reset", "--hard", tag)
    _git(root, "clean", "-fd")


def delete_baseline(root, tag: str) -> None:
    """废弃：tag 删除即时间线消失；commit 留在 git 历史。幂等"""
    root = Path(root)
    if tag in {t["tag"] for t in _tags(root)}:
        _git(root, "tag", "-d", tag)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_gitops.py -v`
Expected: 11 PASS

---

### Task 4: router — version 必填 + restore/DELETE 端点 + 既有 API 测试改写

**Files:**
- Modify: `server/app/api/router.py:75`（`BaselineIn`）、`:968-978`（baseline 路由块）
- Test: `server/tests/test_api.py`（改写 4 处既有用例 + 新增）

**Interfaces:**
- Consumes: Task 1-3 的 gitops 四函数。
- Produces: `POST /baseline`（Body `{version: str, note: str="基线存档"}`，422 detail 区分三规则，响应 `{commit, tag, version}`）；`GET /baseline`（数组，每项含 `time/note/cur`）；`POST /baseline/restore?tag=`（404 未知 tag）；`DELETE /baseline?tag=`（幂等 `{ok: true}`）。Task 5 的 api.ts 按此封装。

- [ ] **Step 1: 改写与新增 API 测试**

`test_api.py` 既有 baseline 相关改写（旧行为断言全部更新为新契约）：

```python
# ⑦ 段（约 99-107 行）改为：
    r = await client.post(f"{BASE}/baseline", json={"version": "1.0.0", "note": "首个基线"})
    assert r.status_code == 200
    first = r.json()
    assert first["tag"] == "v1.0.0" and first["version"] == "1.0.0"
    assert (root / ".git").is_dir()
    r = await client.get(f"{BASE}/baseline")
    item = r.json()[0]
    assert item["tag"] == "v1.0.0" and item["note"] == "首个基线" and item["cur"] is True
```

```python
# test_baseline_without_changes（约 233 行）改为：
async def test_baseline_without_changes(client):
    await client.post(f"{BASE}/baseline", json={"version": "1.0.0", "note": "一"})
    b2 = (await client.post(f"{BASE}/baseline", json={"version": "1.0.1", "note": "二"})).json()
    tags = (await client.get(f"{BASE}/baseline")).json()
    assert b2["tag"] == "v1.0.1" and len(tags) == 2  # 无变更也存版
```

```python
# test_baseline_tag_after_deletion（约 446 行）——自增语义退役，改测删除后版本号可复用（仍受倒挂规则约束，故复用高位版）：
async def test_baseline_delete_then_recreate(client):
    root = ensure_root("演示项目")
    await client.post(f"{BASE}/evidence", json={"raw": "x"})
    await client.post(f"{BASE}/baseline", json={"version": "1.0.0", "note": "一"})
    await client.post(f"{BASE}/baseline", json={"version": "1.1.0", "note": "二"})
    r = await client.delete(f"{BASE}/baseline", params={"tag": "v1.1.0"})
    assert r.status_code == 200
    tags = (await client.get(f"{BASE}/baseline")).json()
    assert [t["tag"] for t in tags] == ["v1.0.0"]  # 废弃=时间线彻底隐藏
    b3 = (await client.post(f"{BASE}/baseline", json={"version": "1.1.0", "note": "重来"})).json()
    assert b3["tag"] == "v1.1.0"  # 删除后版本号可复用（1.1.0 > 现存最大 1.0.0，不撞倒挂）
```

新增（文件末尾 baseline 区域）：

```python
async def test_baseline_validation_422(client):
    await client.post(f"{BASE}/baseline", json={"version": "1.0.0", "note": "一"})
    r = await client.post(f"{BASE}/baseline", json={"version": "v1.2.3"})
    assert r.status_code == 422 and "格式" in r.json()["detail"]
    r = await client.post(f"{BASE}/baseline", json={"version": "1.0.0"})
    assert r.status_code == 422 and "已存在" in r.json()["detail"]
    r = await client.post(f"{BASE}/baseline", json={"version": "0.9.0"})
    assert r.status_code == 422 and "不得低于" in r.json()["detail"]
    r = await client.post(f"{BASE}/baseline", json={"note": "缺版本号"})
    assert r.status_code == 422  # version 必填


async def test_baseline_restore(client):
    ensure_root("演示项目")
    await client.post(f"{BASE}/evidence", json={"raw": "x"})
    await client.post(f"{BASE}/baseline", json={"version": "1.0.0", "note": "一"})
    await client.post(f"{BASE}/evidence", json={"raw": "y"})
    r = await client.post(f"{BASE}/baseline/restore", params={"tag": "v1.0.0"})
    assert r.status_code == 200
    items = (await client.get(f"{BASE}/baseline")).json()
    assert items[0]["tag"] == "v1.0.0" and items[0]["cur"] is True
    r = await client.post(f"{BASE}/baseline/restore", params={"tag": "v9.9.9"})
    assert r.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_api.py -v -k baseline`
Expected: FAIL（422：version 为额外字段被忽略后走旧逻辑 / 路由不存在）

- [ ] **Step 3: 实现 router**

`BaselineIn` 加必填字段：

```python
class BaselineIn(BaseModel):
    version: str
    note: str = "基线存档"
```

baseline 路由块改为：

```python
@api_router.post("/baseline")
async def create_baseline(proj: str, body: BaselineIn):
    try:
        return gitops.save_baseline(_root(proj), body.version, body.note)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@api_router.get("/baseline")
async def list_baselines_route(proj: str):
    return gitops.list_baselines(_root(proj))


@api_router.post("/baseline/restore")
async def restore_baseline_route(proj: str, tag: str):
    try:
        gitops.restore_baseline(_root(proj), tag)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"版本不存在: {tag}")
    return {"ok": True}


@api_router.delete("/baseline")
async def delete_baseline_route(proj: str, tag: str):
    gitops.delete_baseline(_root(proj), tag)
    return {"ok": True}
```

- [ ] **Step 4: 跑定向测试确认通过**

Run: `cd server && uv run pytest tests/test_api.py tests/test_gitops.py -v`
Expected: 全 PASS（其余既有用例不应受影响——`-k` 外的也顺带全跑一次 test_api.py 防意外破坏）

---

### Task 5: web — api.ts 类型与函数迁移

**Files:**
- Modify: `web/src/api.ts:92-95`（Baseline 接口）、`:292-295`（baseline 函数）

**Interfaces:**
- Consumes: Task 4 的端点契约。
- Produces（Task 7 的 VerModal 消费）:

```ts
export interface Baseline {
  commit: string
  tag: string
  version?: string
  time?: number  // unix 秒，前端格式化
  note?: string
  cur?: boolean  // 「当前」徽章依据（HEAD 所指）
}
export const createBaseline = (version: string, note = '基线存档') =>
  req<Baseline>('/baseline', json('POST', { version, note }))
export const restoreBaseline = (tag: string) =>
  req<{ ok: boolean }>(`/baseline/restore?tag=${encodeURIComponent(tag)}`, json('POST', {}))
export const deprecateBaseline = (tag: string) =>
  req<{ ok: boolean }>(`/baseline?tag=${encodeURIComponent(tag)}`, json('DELETE', ''))
```

- [ ] **Step 1: 改 api.ts**（替换 92-95 接口注释与定义、292-295 的 `createBaseline`，追加 `restoreBaseline` / `deprecateBaseline`；接口注释同步新契约）

- [ ] **Step 2: 类型检查**

Run: `cd web && npx vue-tsc -b --noEmit 2>&1 | head -20`
Expected: VerModal.spec.ts / VerModal.vue 报 `createBaseline` 签名不匹配——**预期中**（Task 7 修复；本 task 不求绿，只确认 api.ts 自身无语法错）。若工具链把测试也算进 `-b`，跳过失败判定，仅看 api.ts 无报错。

---

### Task 6: web — utils/md.ts 受限渲染器

**Files:**
- Create: `web/src/utils/md.ts`
- Test: `web/src/utils/__tests__/md.spec.ts`（新建）

**Interfaces:**
- Produces: `renderMd(src: string): string`——HTML 字符串（已全量 escape），Task 7 预览 v-html 用。

- [ ] **Step 1: 写失败测试**

```ts
// 受限 md 渲染器：导出文档语法子集 + XSS escape（无依赖手写，见 spec §4）
import { describe, expect, it } from 'vitest'
import { renderMd } from '../md'

describe('renderMd（语法子集）', () => {
  it('标题按层级渲染', () => {
    expect(renderMd('# 结果文档\n## 需求总览\n### 目标')).toBe(
      '<h1>结果文档</h1><h2>需求总览</h2><h3>目标</h3>')
  })

  it('无序列表聚组', () => {
    expect(renderMd('- 目标：x\n- 入口：y')).toBe('<ul><li>目标：x</li><li>入口：y</li></ul>')
  })

  it('表格：表头+分隔行+数据行，\\| 还原为字面竖线', () => {
    const md = '| ID | 规则 |\n|---|---|\n| R1 | 支持 a\\|b |\n| R2 | 普通规则 |'
    expect(renderMd(md)).toBe(
      '<table><thead><tr><th>ID</th><th>规则</th></tr></thead>' +
      '<tbody><tr><td>R1</td><td>支持 a|b</td></tr><tr><td>R2</td><td>普通规则</td></tr></tbody></table>')
  })

  it('段落：连续行聚为一个 p，段内换行转 br', () => {
    expect(renderMd('主流程：\n第一步\n第二步\n\n第二段')).toBe(
      '<p>主流程：<br>第一步<br>第二步</p><p>第二段</p>')
  })

  it('空串与纯空白返回空串', () => {
    expect(renderMd('')).toBe('')
    expect(renderMd('\n\n')).toBe('')
  })
})

describe('renderMd（安全）', () => {
  it('HTML 全量转义：script/onerror 不构成标签', () => {
    const out = renderMd('<script>alert(1)</script>\n- <img onerror="x">')
    expect(out).not.toMatch(/<(script|img)/)
    expect(out).toContain('&lt;script&gt;')
    expect(out).toContain('&lt;img onerror=')
  })

  it('标题/单元格内的 HTML 也转义', () => {
    expect(renderMd('# <b>粗</b>')).toBe('<h1>&lt;b&gt;粗&lt;/b&gt;</h1>')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/utils/__tests__/md.spec.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `web/src/utils/md.ts`**

```ts
// 受限 markdown 渲染器（spec：版本管理 §4）——只覆盖导出文档用到的语法子集：
// #~###### 标题 / - 列表 / | 表格（\| 转义）/ 空行分段（段内换行转 <br>）。
// 输入源自材料与用户输入：所有文本先 escape 再组标签，v-html 无注入面。
const esc = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')

const splitRow = (line: string): string[] =>
  line.replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map(c => c.replace(/\\\|/g, '|').trim())

export function renderMd(src: string): string {
  const lines = src.split('\n')
  const out: string[] = []
  let para: string[] = []
  let list: string[] = []
  let table: string[][] = []

  const flush = () => {
    if (para.length) out.push(`<p>${para.map(esc).join('<br>')}</p>`)
    if (list.length) out.push(`<ul>${list.map(i => `<li>${esc(i)}</li>`).join('')}</ul>`)
    if (table.length) {
      const [head, ...body] = table
      const th = `<tr>${head.map(c => `<th>${esc(c)}</th>`).join('')}</tr>`
      const tb = body.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')
      out.push(`<table><thead>${th}</thead><tbody>${tb}</tbody></table>`)
    }
    para = []; list = []; table = []
  }

  for (const line of lines) {
    const h = line.match(/^(#{1,6}) (.*)$/u)
    const li = line.match(/^- (.*)$/u)
    if (h) { flush(); out.push(`<h${h[1].length}>${esc(h[2].trim())}</h${h[1].length}>`) }
    else if (li) { flush(); list.push(li[1].trim()) }
    else if (line.startsWith('|')) { flush(); table.push(splitRow(line)) }
    else if (!line.trim()) flush()
    else {
      if (list.length || table.length) flush()  // 列表/表格后接裸文本 → 各自成段
      para.push(line.trim())
    }
  }
  flush()
  return out.join('')
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/utils/__tests__/md.spec.ts`
Expected: 7 PASS

---

### Task 7: web — VerModal 重构（表单 / 行操作 / 确认弹层 / 预览双模式）

**Files:**
- Modify: `web/src/components/VerModal.vue`（全量重写 script 与模板，~330 行内）
- Modify: `web/src/style.css`（追加 `.vnote` `.vacts` `.vact` `.md-view` 样式，~25 行）
- Test: `web/src/components/__tests__/VerModal.spec.ts`（改写）

**Interfaces:**
- Consumes: Task 5 的 `Baseline` / `createBaseline(version, note)` / `restoreBaseline(tag)` / `deprecateBaseline(tag)`；Task 6 的 `renderMd`。
- Produces: 组件对外不变——props `{ open }`、emits `close` / `saved` / `restored`（回滚后父级刷新详情）。

- [ ] **Step 1: 改写组件测试（先定契约）**

`VerModal.spec.ts` 全量替换（mock 结构随新 api 签名）：

```ts
// 版本弹窗：时间线/新增版本表单/回滚废弃确认/预览双模式（api 全 mock）
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createBaseline, deprecateBaseline, getDoc, listBaselines, restoreBaseline } from '../../api'

vi.mock('../../api', () => {
  return {
    ApiError: class ApiError extends Error {
      status: number
      constructor(status: number, detail: unknown) {
        const d = detail instanceof Object && 'detail' in detail ? (detail as any).detail : detail
        super(typeof d === 'string' ? d : `HTTP ${status}`)
        this.status = status
      }
    },
    listBaselines: vi.fn(),
    createBaseline: vi.fn(),
    restoreBaseline: vi.fn(),
    deprecateBaseline: vi.fn(),
    getDoc: vi.fn(),
  }
})

const DOC = '# 需求文档\n\n## 需求总览\n\n| ID | 规则 |\n|---|---|\n| R1 | 目标 |'

let baselines: any[] = []

beforeEach(() => {
  vi.clearAllMocks()
  baselines = []
  vi.mocked(listBaselines).mockImplementation(async () => baselines.map(b => ({ ...b })))
  vi.mocked(createBaseline).mockImplementation(async (version: string, note?: string) => {
    const r = { commit: 'cccc123', tag: `v${version}`, version, cur: true, time: 1760000000, note }
    baselines.push({ ...r, cur: false })
    return r
  })
  vi.mocked(restoreBaseline).mockResolvedValue({ ok: true })
  vi.mocked(deprecateBaseline).mockResolvedValue({ ok: true })
  vi.mocked(getDoc).mockResolvedValue(DOC)
})

let lastW: VueWrapper<any> | null = null
async function mountModal(provide?: Record<string, unknown>) {
  const VerModal = (await import('../VerModal.vue')).default
  lastW?.unmount()
  lastW = mount(VerModal, { props: { open: true }, ...(provide ? { global: { provide } } : {}) })
  await flushPromises()
  return lastW
}

const openForm = async (w: VueWrapper<any>) => {
  // 主弹窗 foot 的「新增版本」开表单；表单内确认按钮用 data-testid 区分（同名不同按钮）
  await w.findAll('button').find(b => b.text() === '新增版本' && !b.attributes('data-testid'))!.trigger('click')
}
const submitForm = async (w: VueWrapper<any>) => {
  await w.find('[data-testid="commit-ver"]').trigger('click')
}

describe('VerModal（版本弹窗）', () => {
  it('无版本时展示空态文案', async () => {
    const w = await mountModal()
    expect(w.find('.mask.open').exists()).toBe(true)
    expect(w.text()).toContain('还没有版本——需要留底时点新增版本')
  })

  it('时间线渲染版本号/时间/说明；cur 字段标当前（非末位）', async () => {
    vi.mocked(listBaselines).mockResolvedValue([
      { tag: 'v1.0.0', commit: 'aaaa1111bbbb2222', version: '1.0.0', time: 1760000000, note: '初版' },
      { tag: 'v1.1.0', commit: 'ffff9999dddd8888', version: '1.1.0', time: 1760000600, note: '评审版', cur: true },
    ])
    const w = await mountModal()
    const items = w.findAll('.vitem')
    expect(items.length).toBe(2)
    expect(items[0].classes()).not.toContain('cur')
    expect(items[1].classes()).toContain('cur')
    expect(w.text()).toContain('1.1.0')
    expect(w.text()).toContain('当前')
    expect(w.text()).toContain('评审版')
    expect(w.text()).toContain('aaaa111')  // commit 短 hash
    expect(w.text()).toMatch(/2025-10-0[89] \d{2}:\d{2}/)  // 1760000000 → 本地 YYYY-MM-DD HH:mm（UTC+8 为 10-09）
  })

  it('新增版本：表单填版本号+说明，提交调 createBaseline 并重拉', async () => {
    const w = await mountModal()
    await openForm(w)
    await w.find('input[type="text"]').setValue('1.0.1')
    await w.find('textarea').setValue('评审前留底')
    await submitForm(w)
    await flushPromises()
    expect(createBaseline).toHaveBeenCalledWith('1.0.1', '评审前留底')
    expect(w.emitted('saved')).toBeTruthy()
    expect(listBaselines).toHaveBeenCalledTimes(2)
    expect(w.text()).toContain('v1.0.1')
  })

  it('版本号格式错：红字提示且不提交', async () => {
    const w = await mountModal()
    await openForm(w)
    await w.find('input[type="text"]').setValue('1.2')
    await submitForm(w)
    await flushPromises()
    expect(w.text()).toContain('格式须为 x.y.z')
    expect(createBaseline).not.toHaveBeenCalled()
  })

  it('回滚：确认弹层文案含丢弃警示，确认调 restoreBaseline 并 emit restored', async () => {
    vi.mocked(listBaselines).mockResolvedValue([
      { tag: 'v1.0.0', commit: 'aaaa1111bbbb2222', version: '1.0.0', time: 1760000000 },
      { tag: 'v1.1.0', commit: 'ffff9999dddd8888', version: '1.1.0', time: 1760000600, cur: true },
    ])
    const w = await mountModal()
    await w.findAll('.vact').find(b => b.text().includes('回滚'))!.trigger('click')
    expect(w.text()).toContain('回滚到 1.0.0')
    expect(w.text()).toContain('不可恢复')
    await w.findAll('button').find(b => b.text() === '确认回滚')!.trigger('click')
    await flushPromises()
    expect(restoreBaseline).toHaveBeenCalledWith('v1.0.0')
    expect(w.emitted('restored')).toBeTruthy()
    expect(listBaselines).toHaveBeenCalledTimes(2)
  })

  it('废弃：确认后调 deprecateBaseline 并重拉', async () => {
    vi.mocked(listBaselines).mockResolvedValue([
      { tag: 'v1.0.0', commit: 'aaaa1111bbbb2222', version: '1.0.0', time: 1760000000 },
      { tag: 'v1.1.0', commit: 'ffff9999dddd8888', version: '1.1.0', time: 1760000600, cur: true },
    ])
    const w = await mountModal()
    await w.findAll('.vact').find(b => b.text().includes('废弃'))!.trigger('click')
    expect(w.text()).toContain('废弃版本 1.0.0')
    await w.findAll('button').find(b => b.text() === '确认废弃')!.trigger('click')
    await flushPromises()
    expect(deprecateBaseline).toHaveBeenCalledWith('v1.0.0')
    expect(listBaselines).toHaveBeenCalledTimes(2)
  })

  it('预览双模式：默认渲染 markdown（表格/标题成 HTML），可切源码 pre', async () => {
    const w = await mountModal()
    await w.findAll('button').find(b => b.text().includes('预览 / 导出需求文档'))!.trigger('click')
    await flushPromises()
    expect(getDoc).toHaveBeenCalled()
    const view = w.find('.md-view')
    expect(view.exists()).toBe(true)
    expect(view.find('table').exists()).toBe(true)
    expect(view.find('h1').text()).toContain('需求文档')
    await w.findAll('button').find(b => b.text() === '源码')!.trigger('click')
    expect(w.find('.doc-outline').exists()).toBe(true)
    expect(w.findAll('button').some(b => b.text() === '下载 .md')).toBe(true)
  })

  it('新增版本失败 toast warn', async () => {
    const toasts: string[] = []
    vi.mocked(createBaseline).mockRejectedValueOnce(new ApiError(422, '版本号已存在: 1.0.0'))
    const w = await mountModal({ toast: (msg: string, cls?: string) => toasts.push(`${msg}|${cls ?? ''}`) })
    await openForm(w)
    await w.find('input[type="text"]').setValue('1.0.0')
    await submitForm(w)
    await flushPromises()
    expect(toasts.some(t => t.includes('新增失败') && t.includes('warn'))).toBe(true)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/components/__tests__/VerModal.spec.ts`
Expected: 全部 FAIL/报错（旧组件无表单/行操作/双模式）

- [ ] **Step 3: 重写 VerModal.vue**

结构要点（对照原型 `reports/version-preview/index.html` 的场景 1-6，文案以原型为准）：

```ts
// script 关键状态与函数（示意，完整实现对照原型交互）
import { computed, inject, ref, watch } from 'vue'
import { ApiError, createBaseline, deprecateBaseline, getDoc, listBaselines,
         restoreBaseline, type Baseline } from '../api'
import { renderMd } from '../utils/md'

const items = ref<Baseline[]>([])
const formOpen = ref(false)
const ver = ref(''), note = ref('')
const confirm = ref<null | { kind: 'restore' | 'deprecate'; b: Baseline }>(null)
const docOpen = ref(false), docText = ref(''), docMode = ref<'md' | 'src'>('md')

const VER_RE = /^\d+\.\d+\.\d+$/
const verErr = computed(() => {
  const v = ver.value.trim()
  if (!v) return ''
  if (!VER_RE.test(v)) return '格式须为 x.y.z 三段数字，如 1.2.2'
  if (items.value.some(b => b.tag === `v${v}`)) return `${v} 已存在——版本号不可与已有版本重复`
  const nums = v.split('.').map(Number)
  const maxNew = Math.max(0, ...items.value
    .map(b => b.tag.match(/^v(\d+)\.(\d+)\.(\d+)$/))
    .filter(Boolean)
    .map(m => (m![1] * 1e6) + (m![2] * 1e3) + m![3] * 1))
  if (nums[0] * 1e6 + nums[1] * 1e3 + nums[2] <= maxNew) return `不可低于已有最大版本 ${maxTag()}`
  return ''
})
const fmtTime = (t?: number) =>
  t ? new Date(t * 1000).toLocaleString('sv-SE', { hour12: false }).slice(0, 16) : ''  // YYYY-MM-DD HH:mm

async function save() {
  if (!VER_RE.test(ver.value.trim()) || verErr.value) return
  try {
    const r = await createBaseline(ver.value.trim(), note.value.trim() || undefined)
    toast(`已新增版本 ${r.tag}`, 'ok')
    emit('saved'); formOpen.value = false
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? `新增失败：${e.message}` : '新增失败', 'warn')
  }
}
async function doConfirm() {
  if (!confirm.value) return
  const { kind, b } = confirm.value
  try {
    if (kind === 'restore') { await restoreBaseline(b.tag); emit('restored') }
    else await deprecateBaseline(b.tag)
    toast(kind === 'restore' ? `已回滚到 ${b.tag}` : `已废弃 ${b.tag}`, 'ok')
    confirm.value = null
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? `操作失败：${e.message}` : '操作失败', 'warn')
  }
}
```

模板结构（三段式弹窗 × 4 个，DOM 顺序同现有模式——主弹窗在前，二级弹层在后）：
1. 主弹窗：时间线 `v-for`（`cur` class 绑 `b.cur`；版本号取 `b.tag` 去 `v` 前缀或 `b.version`；`vnote` 纯文本；**非当前行** hover 出 `.vacts`：「↩ 回滚到此版」「✕ 废弃」，点击设 `confirm`）；旧格式行（tag 不匹配 `v\d+\.\d+\.\d+`）加 `legacy` class + 「旧格式」徽章；foot：「新增版本」按钮 + 「预览 / 导出需求文档」。
2. 新增版本表单弹层：版本号 input（`:class="{ 'err-in': verErr }"`）+ 动态提示（红字 verErr / 灰字格式说明）+ 说明 textarea；foot 取消/新增版本（确认按钮带 `data-testid="commit-ver"`，与主弹窗同名按钮区分，测试选择器依赖它）。
3. 确认弹层（restore/deprecate 共用一个，文案按 kind）：回滚含红字「当前未存版的修改将被丢弃，且不可恢复」；废弃含「从时间线彻底消失……仍保留在 git 历史中」；确认按钮 `btn-danger`。
4. 预览弹层：头部「渲染 / 源码」切换按钮组（`docMode`）；body 三态——`md` 模式 `<div class="md-view" v-html="renderMd(docText)">`、`src` 模式 `<pre class="doc-outline">{{ docText }}`；foot 下载 .md（下载永远下源码）。

`style.css` 追加（对照原型样式，全局表）：

```css
.vitem .vnote { font-size: 12px; color: var(--fg); margin-top: 4px; white-space: pre-wrap; }
.vitem .vacts { display: none; gap: 6px; margin-left: auto; }
.vitem:hover .vacts { display: inline-flex; }
.vact { font-size: 11px; padding: 2px 8px; border-radius: 5px; background: var(--muted); color: var(--muted-fg); }
.vact:hover { background: var(--blue-bg); color: var(--primary); }
.vact.depr:hover { background: var(--red-bg); color: var(--destructive); }
.vitem.legacy h4 .vno { color: var(--muted-fg); }
.ferr { font-size: 11.5px; color: var(--destructive); margin-top: 4px; }
.fhint { font-size: 11.5px; color: var(--muted-fg); margin-top: 4px; }
.md-view { font-size: 13px; line-height: 1.7; }
.md-view h1 { font-size: 18px; margin: 18px 0 8px; } .md-view h2 { font-size: 16px; margin: 16px 0 6px; }
.md-view h3, .md-view h4 { font-size: 14px; margin: 12px 0 4px; }
.md-view table { border-collapse: collapse; margin: 8px 0; }
.md-view th, .md-view td { border: 1px solid var(--border2); padding: 5px 10px; font-size: 12.5px; text-align: left; }
.md-view th { background: var(--muted); }
.md-view ul { padding-left: 20px; margin: 6px 0; }
.md-view p { margin: 6px 0; }
```

- [ ] **Step 4: 跑组件测试确认通过**

Run: `cd web && npx vitest run src/components/__tests__/VerModal.spec.ts src/utils/__tests__/md.spec.ts`
Expected: 全 PASS（8 + 7）

- [ ] **Step 5: 类型与构建检查**

Run: `cd web && npx vue-tsc -b && npx vite build 2>&1 | tail -5`
Expected: 无类型错误、构建成功

---

### Task 8: 定向回归与收尾

**Files:** 无新改动（验证 + 提交）

- [ ] **Step 1: 后端定向全量**

Run: `cd server && uv run pytest tests/ -q 2>&1 | tail -5`
Expected: 全 PASS（gitops 新文件 + test_api 改写后，其余不应受影响；baseline 相关是公共底层吗——不是，模块独立，故跑全量仅为最终验证，符合「全部改动完成后的最终验证」例外）

- [ ] **Step 2: 前端定向全量**

Run: `cd web && npx vitest run 2>&1 | tail -5`
Expected: 全 PASS（VerModal 重写 + api 签名变更可能波及引用方——`createBaseline` 仅 VerModal 使用，grep 确认无其他引用）

- [ ] **Step 3: 手动冒烟（可选但推荐）**

起服务后在真实项目上过一遍原型场景 1-6：新增 `1.0.0` → 改点数据 → 新增 `1.0.1` → 回滚到 `1.0.0`（当前徽章移位）→ 再新增 `1.0.2` → 废弃 `1.0.0`（时间线消失）→ 预览渲染/源码切换 + 下载。注意 `NO_PROXY` 环境下访问 localhost:8000。

- [ ] **Step 4: Commit（单条）**

```bash
git add server/app/storage/gitops.py server/app/api/router.py server/tests/test_gitops.py server/tests/test_api.py \
        web/src/api.ts web/src/utils/md.ts web/src/utils/__tests__/md.spec.ts \
        web/src/components/VerModal.vue web/src/components/__tests__/VerModal.spec.ts web/src/style.css \
        docs/specs/2026-10-10-version-mgmt-design.md docs/plans/2026-10-10-version-mgmt.md
git commit -m "feat：版本管理优化——手动版本号 x.x.x+说明+回滚废弃+预览 markdown 渲染"
```

（reports/version-preview/ 原型目录不入库，与既有 reports/ 惯例一致。）
