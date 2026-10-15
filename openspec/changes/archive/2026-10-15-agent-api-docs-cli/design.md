# Design: agent 对接接口文档 + CLI 通道

## 1. agent 对接端点清单（CLI 覆盖范围）

从 `docs/quos-agent-api.md` 调用顺序与代码导出，agent 消费的端点共 10 个：

| # | 端点 | 用途 | CLI 子命令 |
|---|---|---|---|
| 1 | `GET /api/v1/projects` | 找 pid | `projects` |
| 2 | `GET /api/v1/projects/{pid}/materials` | 拉材料（parsed_text 出处源） | `materials PID` |
| 3 | `GET /api/v1/projects/{pid}/doc/baseline` | 拉基线（冷启动判断） | `baseline PID` |
| 4 | `GET /api/v1/projects/{pid}/doc/draft` | 读当前 reviewing 草案 | `draft PID` |
| 5 | `POST /api/v1/projects/{pid}/doc/draft/import` | md 导入（推荐提交路径） | `import-draft PID --md FILE [--meta FILE]` |
| 6 | `POST /api/v1/projects/{pid}/doc/draft` | 手工 payload 提交 | `submit-draft PID --file FILE` |
| 7 | `GET /api/v1/projects/{pid}/questions?status=` | 取批注/已答批注 | `questions PID [--status STATUS]` |
| 8 | `POST /api/v1/projects/{pid}/questions` | 批量提交批注 | `post-questions PID --file FILE` |
| 9 | `GET /api/v1/projects/{pid}/doc/versions` | 版本列表（断点续跑参考） | `versions PID` |
| 10 | `GET /api/v1/projects/{pid}/doc/changes` | 变更记录 | `changes PID [--version V]` |

不在 CLI 范围（人在平台/前端操作）：materials 上传删除、项目 CRUD/归档、finalize/revert、questions answer。`--base` 全局参数覆盖基址（默认 `http://127.0.0.1:8000`）。

## 2. CLI 设计（`server/app/cli.py`）

- **零新依赖**：argparse + httpx（httpx 已在 dev group；`uv run` 默认装 dev group）。约 200 行，单文件。
- **输入走文件不走参数**：md 全文、payload、questions 数组一律 `--file`/`--md` 从文件读——agent 产物本来就是文件，绕开 shell 转义与大 body 限制。`rules_meta` 用 `--meta FILE`（JSON）。
- **输出约定**：
  - 成功：响应 JSON 直出 stdout（agent 可 `| jq` 或直接读），退出码 0；
  - HTTP 错误（422/404/409）：响应体 JSON 仍出 stdout（`hard_errors` 明细是 agent 修复闭环的输入，必须机器可读），状态行出 stderr，退出码 1（builder check 自决：agent 语义靠 stdout JSON，退出码取值无影响）；
  - 连接失败（服务未起）：stderr 提示 `服务未启动？./start.sh`，退出码 2。
- **禁用系统代理**：httpx 客户端 `trust_env=False`——本机全局代理 127.0.0.1:7897 会劫持对 127.0.0.1:8000 的请求，导致「服务未启动」误报（builder check 自决，项目已知坑）。
- **测试**：常规冒烟（新代码的基本验证，非防漂移机制）——`tests/test_cli.py` 覆盖 `--help`、参数解析、一条 MockTransport happy path（import-draft 读 md 文件 → 断言请求体 → 假响应直出 stdout）。HTTP 调用收敛到模块级 `_request()`，便于注入替身，不起真服务。
- 帮助文本中文；详细用法只写在 `docs/quos-agent-api.md`「CLI 调用」节（单一事实源：`--help` 与 `docs/api.md`）。

## 3. 接口文档结构（`docs/api.md`）

- 头部：基址、错误约定（404/409/422 语义、hard_errors 结构）、与 quos-agent-api.md 的分工互链、维护规则提示（改接口须同步本文档，见 AGENTS.md）。
- 按域分节：projects / materials / doc / questions / health。每端点：方法、路径、参数、请求体字段、响应结构、错误码——从代码 docstring/模型提取**现状**，描述行为不写愿景。
- 维护方式为规则驱动（见 §5），文档保持人可读的 markdown，不做机器可解析格式约束。

## 4. 规则落档（项目根 `AGENTS.md` + `openspec/project.md`）

**`AGENTS.md`（新建，项目根）**——ZCode 及通用 agent 约定每次会话自动加载，内容两条规则：

1. **接口文档同步**：任何接口增删改（端点/参数/请求体/响应结构/错误码），同一次改动必须同步 `docs/api.md` 对应条目；
2. **CLI 同步**：agent 对接接口（§1 清单）增删改，同一次改动必须同步 `server/app/cli.py` 子命令与 `docs/quos-agent-api.md` 的 CLI 用法、`.agents/skills/req-organize` 的对接指引。

**`openspec/project.md`** 全局约束追加一行：接口与 CLI 变更须按 `AGENTS.md` 开发规则同步维护 `docs/api.md` 与 CLI。

「自动维护」的机制即此：规则进 agent 必读文件，改接口的会话自动带上义务。不建测试拦截、不做文档生成。

## 5. skill 同步（渐进式披露）

- **详细内容不进 SKILL.md**：CLI 每条命令的用法写 `docs/quos-agent-api.md` 新增「CLI 调用」节（含每步的 CLI 等价命令、422 输出语义、文件传参约定）；端点契约见 `docs/api.md`。
- **`.agents/skills/req-organize/SKILL.md`** 仅改「配套对接（可选）」节一两句：本仓库环境提供 CLI（`uv run --directory server python -m app.cli <cmd>`），提交/拉取优先 CLI，用法与端点契约见 docs 两份文档。其余内容不动，不趁机堆砌。
- req-review / req-breakdown 无平台调用，不动。

## 6. 明确不做

- 不做测试拦截文档漂移（用户拍板：规则驱动而非机器强制）。
- 不做 OpenAPI 自动生成 markdown（生成物无人读等于没文档）。
- 不给「人的端点」（上传/定稿/回滚/作答）做 CLI——触发权在人，走前端。
- 不改 quos-agent-api.md 既有协议内容，只增「CLI 调用」节。
- 流程纪律（改接口须同步文档）不进 `specs/`——spec 只描述系统运行时行为，纪律归 AGENTS.md / project.md。
