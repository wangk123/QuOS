# agent 接口文档 + CLI 通道 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 agent 对接端点提供 CLI 通道与全端点接口文档，并以 AGENTS.md 规则驱动后续同步维护。

**Architecture:** CLI 是纯客户端包装（argparse + httpx，请求收敛到单一 `_request`），服务端零改动；接口文档为 docs/api.md（现状描述）；维护机制为规则入 AGENTS.md（非测试拦截）。

**Tech Stack:** Python 3.12 / argparse / httpx（已在 dev group）/ pytest。

**Spec:** `openspec/changes/agent-api-docs-cli/design.md`（含 proposal.md；执行者须先读）

## Global Constraints

- 零新依赖：只用标准库 argparse + httpx。
- 服务端（`server/app/api/`、`main.py`）零改动。
- `cli.py` ≤ 300 行（工具函数上限）。
- 不做防漂移测试、不做文档自动生成（用户拍板，design.md §6）。
- skill 改动遵循渐进式披露：req-organize/SKILL.md 只改「配套对接（可选）」节，不新增其他内容。
- 文档只描述代码现状，不写愿景。
- Commit：各任务不单独提交，全部完成最终一条（用户 git 纪律）。

## Review Focus

- 服务未启动 → 退出码 2 + stderr 含「服务未启动」提示，不抛 traceback（Task 1 测试钉）。
- 422 响应体 `{"detail": {"hard_errors": [...]}}` 原样透传 stdout，agent 可解析（Task 1 测试钉）。
- 中文内容 stdout 输出 `ensure_ascii=False`，不被转义成 \uXXXX（Task 1 测试钉）。
- `--file`/`--md` 文件不存在 → 退出码 2 + stderr 提示路径，不抛 traceback（Task 2 测试钉）。
- 本机代理 127.0.0.1:7897 劫持 localhost 请求 → `trust_env=False` 写死在 `_make_client`（代码约束，MockTransport 测不到 env 劫持，靠 review）。

---

### Task 1: CLI 骨架 + HTTP 核心 + projects 命令

**Files:**
- Create: `server/app/cli.py`
- Test: `server/tests/test_cli.py`

**Interfaces:**
- Produces: `_make_client(base: str) -> httpx.Client`（`base_url=base, trust_env=False, timeout=30`）；`_request(client, method: str, path: str, *, json_body=None, params=None) -> int`（发请求、按输出约定打印、返回退出码）；`build_parser() -> argparse.ArgumentParser`；`main(argv: list[str] | None = None) -> int`（`if __name__ == "__main__": sys.exit(main())`）。
- 全局参数：`--base`（默认 `http://127.0.0.1:8000`）。
- 输出约定（design.md §2）：成功/HTTP 错误均 `json.dumps(resp.json(), ensure_ascii=False, indent=2)` 出 stdout；HTTP 错误另出 stderr 一行 `HTTP {status}: {method} {path}` 并返回 1；`httpx.ConnectError`/`httpx.ConnectTimeout` → stderr `连接失败({base})：服务未启动？./start.sh` 返回 2；无 JSON 的响应体原样文本出 stdout。

- [ ] **Step 1: 写失败测试**（`tests/test_cli.py`，用 `httpx.MockTransport` + `capsys` + `monkeypatch`，monkeypatch `app.cli._make_client` 返回带 MockTransport 的 Client）

```python
def _patch_client(monkeypatch, handler):
    monkeypatch.setattr("app.cli._make_client", lambda base: httpx.Client(
        transport=httpx.MockTransport(handler)))

def test_projects_happy_path(monkeypatch, capsys):
    _patch_client(monkeypatch, lambda req: httpx.Response(200, json={"ok": True}))
    assert cli.main(["projects"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {"ok": True}

def test_http_error_detail_to_stdout(monkeypatch, capsys):
    _patch_client(monkeypatch, lambda req: httpx.Response(
        422, json={"detail": {"hard_errors": [{"code": "QUOTE_NOT_FOUND", "rule_no": "FR-101", "detail": "x"}]}}))
    assert cli.main(["projects"]) == 1
    oe = capsys.readouterr()
    assert json.loads(oe.out)["detail"]["hard_errors"][0]["code"] == "QUOTE_NOT_FOUND"
    assert "HTTP 422" in oe.err

def test_connect_error_exit_2(monkeypatch, capsys):
    def boom(req): raise httpx.ConnectError("refused")
    _patch_client(monkeypatch, boom)
    assert cli.main(["projects"]) == 2
    assert "服务未启动" in capsys.readouterr().err

def test_chinese_not_escaped(monkeypatch, capsys):
    _patch_client(monkeypatch, lambda req: httpx.Response(200, json={"name": "云风控"}))
    cli.main(["projects"])
    assert "云风控" in capsys.readouterr().out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_cli.py -v`
Expected: FAIL（`ModuleNotFoundError: app.cli` 或 import error）

- [ ] **Step 3: 实现 `server/app/cli.py`**

模块 docstring 一句话（CLI 通道：agent 对接端点的命令行包装，用法见 docs/quos-agent-api.md）。`build_parser()` 挂 `--base` 与 `projects` 子命令（help「项目列表（找 pid）」）；`main` 解析后 dispatch 到 `_request(client, "GET", "/api/v1/projects")` 并 `sys.exit`。测试替身经 `_make_client` 注入，production 路径直接用它。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && uv run pytest tests/test_cli.py -v`
Expected: 4 PASS

---

### Task 2: 其余 9 个子命令

**Files:**
- Modify: `server/app/cli.py`
- Test: `server/tests/test_cli.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `_make_client`/`_request`/`build_parser`/`main`。
- Produces: 子命令 `materials PID`、`baseline PID`、`draft PID`、`import-draft PID --md FILE [--meta FILE]`、`submit-draft PID --file FILE`、`questions PID [--status STATUS]`、`post-questions PID --file FILE`、`versions PID`、`changes PID [--version V]`。路径模板：`/api/v1/projects/{pid}/materials|doc/baseline|doc/draft|doc/draft/import|doc/draft|questions|doc/versions|doc/changes`；`questions` 的 status、`changes` 的 version 走 query params。文件读取统一 helper `_read_file(path: str, what: str) -> str`（不存在/读失败 → stderr 提示 + SystemExit(2)）。body：import-draft `{"markdown": md, "rules_meta": json.loads(meta) 若有}`（rules_meta 为 null 时省略键）；submit-draft/post-questions `json.loads(file 内容)`。

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_import_draft_reads_md_file(monkeypatch, capsys, tmp_path):
    md = tmp_path / "doc.md"; md.write_text("# 测试文档\n\n- FR-101 必须支持批量导入。", encoding="utf-8")
    seen = {}
    def handler(req):
        seen["body"] = json.loads(req.content); seen["path"] = str(req.url)
        return httpx.Response(200, json={"draft_id": 7})
    _patch_client(monkeypatch, handler)
    assert cli.main(["import-draft", "3", "--md", str(md)]) == 0
    assert seen["path"].endswith("/api/v1/projects/3/doc/draft/import")
    assert seen["body"]["markdown"].startswith("# 测试文档")

def test_import_draft_with_meta(...):   # --meta 传 JSON 文件 → body.rules_meta 等于其解析值
def test_parser_questions_opts(...):    # build_parser 解析 ["questions","5","--status","answered"] → ns.pid==5, ns.status=="answered"
def test_parser_changes_version(...):   # ["changes","5","--version","1.0.0"] → ns.version=="1.0.0"
def test_missing_file_exit_2(monkeypatch, capsys):
    assert cli.main(["import-draft", "3", "--md", "/no/such.md"]) == 2
    assert "不存在" in capsys.readouterr().err
```

（`test_import_draft_with_meta`/`test_parser_*` 按 Task 1 风格补全断言，上为命名与要点。）

- [ ] **Step 2: 跑测试确认新增用例失败**

Run: `cd server && uv run pytest tests/test_cli.py -v`
Expected: 新增用例 FAIL（子命令不存在 → argparse SystemExit 2 且 stderr 无「不存在」提示，断言失败）

- [ ] **Step 3: 实现 9 个子命令**

每个命令一个两行的 handler 函数（读参 → `_request`）；help 中文一句话对齐 design.md §1 表；不写额外注释。

- [ ] **Step 4: 跑测试确认通过 + 冒烟**

Run: `cd server && uv run pytest tests/test_cli.py -v && uv run python -m app.cli --help && uv run python -m app.cli import-draft --help`
Expected: 全 PASS；`--help` 列出 10 个子命令。

---

### Task 3: docs/api.md 全端点接口参考

**Files:**
- Create: `docs/api.md`

**Interfaces:**
- Consumes: 代码现状（`server/app/api/*.py`、`main.py` 的 health）。
- Produces: 后续 Task 4/5 引用的文档路径 `docs/api.md`。

- [ ] **Step 1: 写文档**

结构：①头部——基址 `http://127.0.0.1:8000`、通用错误约定（404 不存在 / 409 冲突 / 422 校验拒收、`{"detail": {"hard_errors": [{code, rule_no?, detail}]}}` 结构）、与 `docs/quos-agent-api.md` 分工互链（本文=端点契约参考，彼文=agent 调用协议）、维护提示（接口变更须同步本文，规则见根目录 AGENTS.md）；②按域五节：projects（6 端点）、materials（3）、doc（8）、questions（3）、health（1）；每端点列方法、路径、路径/query 参数、请求体字段（含类型与可选性，从 pydantic 模型提取）、响应结构与关键字段、错误码（哪些情形 404/409/422，422 的 code 列表如 QUOTE_NOT_FOUND/BLOCK_*/CHAPTER_PARENT_*/SCHEMA/FORMAT_CONTRACT/MERMAID_SYNTAX/SINGLE_REVIEWING）。语言中文，描述现状。

- [ ] **Step 2: 机器核对端点全覆盖（一次性验收，不落测试文件）**

Run: `cd server && uv run python -c "
import re
from app.main import app
routes = sorted(f'{sorted(r.methods - {\"HEAD\"})[0]} {r.path}' for r in app.routes if hasattr(r, 'methods'))
doc = open('../docs/api.md').read()
missing = [r for r in routes if r.split(' ', 1)[1] not in doc]
print(len(routes), 'routes;', 'missing:', missing)"`
Expected: 输出 21 routes; missing: []（含 health；/openapi.json /docs 等无 methods 的自动排除）

- [ ] **Step 3: 人工复查**

对照 `server/app/api/doc.py:64-84`（ImportBody）与 `questions.py:44-62`（QuestionIn）抽查 import-draft 与 questions 两节的字段描述与代码一致。

---

### Task 4: AGENTS.md + project.md 指针

**Files:**
- Create: `AGENTS.md`（项目根）
- Modify: `openspec/project.md`（「全局约束」节末尾追加一行）

**Interfaces:**
- Consumes: design.md §4 的两条规则文本。
- Produces: 后续所有 agent 会话自动加载的项目规则。

- [ ] **Step 1: 写 AGENTS.md**

标题「QuOS 项目开发规则」+ 两节：
1. **接口文档同步**：任何接口增删改（端点/参数/请求体/响应/错误码），同一次改动必须同步 `docs/api.md` 对应条目；
2. **CLI 同步**：agent 对接接口（projects/materials/baseline/draft/import-draft/submit-draft/questions/post-questions/versions/changes）增删改，同一次改动必须同步 `server/app/cli.py` 子命令、`docs/quos-agent-api.md`「CLI 调用」节与 `.agents/skills/req-organize/SKILL.md`「配套对接」节。
每节末尾一句 why（文档漂移即对接断裂，agent 是文档的第一维护人）。全文 ≤ 20 行。

- [ ] **Step 2: project.md「全局约束」追加一行**

`- 接口与 CLI 变更须按根目录 AGENTS.md 开发规则同步维护 docs/api.md 与 server/app/cli.py（含 skill 对接指引）`

- [ ] **Step 3: 人工复查**

确认 AGENTS.md 位于项目根（ZCode 自动加载位置）；两条规则与 design.md §4 一致。

---

### Task 5: quos-agent-api.md「CLI 调用」节 + req-organize 指引

**Files:**
- Modify: `docs/quos-agent-api.md`（「调用顺序」节后插入新节）
- Modify: `.agents/skills/req-organize/SKILL.md`（仅「配套对接（可选）」节）

**Interfaces:**
- Consumes: Task 2 的子命令清单、Task 3 的 docs/api.md。
- Produces: agent 实际读的 CLI 用法文档。

- [ ] **Step 1: quos-agent-api.md 插「CLI 调用」节**

内容：调用形式 `uv run --directory server python -m app.cli <cmd>`（在仓库根执行；`--base` 可覆盖基址；不设命令别名）；一张命令表（10 命令 ↔ 用途，参数细节指向 `--help` 与 docs/api.md）；输出约定三条（成功 JSON 出 stdout 退出码 0；422 明细出 stdout 退出码 1，配合「校验报告处理纪律」修复重交；连接失败退出码 2 = 服务未起）。在「调用顺序」每步的 HTTP 形式后标注该步的 CLI 完整命令。既有协议文字不动。

- [ ] **Step 2: req-organize/SKILL.md 改「配套对接（可选）」节**

将该节改为：保持「本 skill 独立通用」定性；本仓库环境提供 CLI——提交/拉取平台数据优先用 `uv run --directory server python -m app.cli <cmd>`（文件传参、422 明细机器可读），命令用法见 `docs/quos-agent-api.md`「CLI 调用」，端点契约见 `docs/api.md`。3-4 句以内，其余章节零改动。

- [ ] **Step 3: 人工复查**

grep 确认 SKILL.md 仅「配套对接」节有 diff；quos-agent-api.md 既有节内容零改动（git diff 核对）。

---

### Task 6: 最终验证 + commit

**Files:**
- 无新增；全量回归。

- [ ] **Step 1: server 全量测试**

Run: `cd server && uv run pytest -q`
Expected: 全绿（原 78 + 新增 test_cli 用例）。

- [ ] **Step 2: 真机冒烟**

Run: `curl -s --noproxy '*' http://127.0.0.1:8000/api/v1/health || ./start.sh &` 确认服务在，然后 `uv run --directory server python -m app.cli projects`
Expected: 输出项目列表 JSON（真数据）。若 8000 被占或服务未起，先起服务再跑。

- [ ] **Step 3: commit（一条）**

```bash
git add docs/api.md AGENTS.md server/app/cli.py server/tests/test_cli.py docs/quos-agent-api.md .agents/skills/req-organize/SKILL.md openspec/project.md openspec/changes/agent-api-docs-cli/
git commit -m "feat：agent 对接 CLI 通道 + 全端点接口文档 + AGENTS.md 同步维护规则（接口/CLI 变更同步 api.md 与 skill 指引）"
```
