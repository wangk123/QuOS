# Proposal: agent 对接接口文档 + CLI 通道

## Why

1. **接口契约无权威参考**：20 个端点的请求/响应结构散落在 docstring、`docs/quos-agent-api.md`（协议视角）、测试与前端 `api.ts` 中；外部 agent 对接只靠 quos-agent-api.md 的流程叙述，查一个端点的精确字段要翻源码。
2. **agent 对接靠 curl 手拼 body**：`POST /doc/draft/import` 的 markdown 全文、questions 的 JSON 数组，用 curl 传既难写又易错（引号转义、大文件）；422 拒收后的 `detail.hard_errors` 结构也难在 shell 里读。
3. **文档会漂移**：接口变了没人记得改文档。维护机制采用**规则驱动**（用户拍板 2026-10-15）：把同步义务写进 agent 必读的规则文件（项目根 `AGENTS.md` + `openspec/project.md` 指针），之后任何 agent 改接口时自动遵循。不做测试拦截、不做自动生成。

## What Changes

1. **`docs/api.md`（新建）**：全端点接口参考（方法/路径/参数/请求体/响应/错误码，按域分组）。与 `docs/quos-agent-api.md` 分工：后者保持 agent 协议视角（调用顺序、校验纪律、实战沉淀），顶部互链。
2. **`server/app/cli.py`（新建）**：CLI 通道，子命令一一对应 agent 对接端点（8 个消费 + 2 个只读）。argparse + httpx，零新依赖。调用形式 `uv run --directory server python -m app.cli <cmd>`。
3. **项目根 `AGENTS.md`（新建）**：两条开发规则——①接口增删改必须同步 `docs/api.md`；②agent 对接接口增删改必须同步 `server/app/cli.py` 子命令与 skill 调用指引。`openspec/project.md` 全局约束加一行指针。ZCode 每次会话自动加载 AGENTS.md，实现「接口变更时 agent 自动维护文档」。
4. **CLI 用法落档（渐进式披露）**：详细用法进 `docs/quos-agent-api.md` 新增「CLI 调用」节；`.agents/skills/req-organize/SKILL.md`「配套对接」节仅改一两句指引（本仓库提供 CLI、优先 CLI、用法见 docs 两份文档），不把 CLI 详情堆进 SKILL.md。req-review / req-breakdown 无平台调用，不动。

## Impact

- 新增 3 个文件（api.md、cli.py、AGENTS.md）+ CLI 冒烟测试，修改 3 个（quos-agent-api.md、req-organize/SKILL.md、project.md）。
- 不改任何现有端点行为；CLI 是纯客户端包装，服务端零改动。
- 新 capability `agent-integration`（specs delta）。
