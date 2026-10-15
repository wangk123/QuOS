# agent-integration Specification

## Purpose

外部 agent 与平台的对接通道：CLI 命令行包装（`server/app/cli.py`）。平台被动服务、agent 短事务（唤起 → 拉取 → 加工 → 提交 → 退出），CLI 覆盖 agent 消费的全部端点；接口契约参考与调用协议文档见 `docs/api.md` 与 `docs/quos-agent-api.md`，接口/CLI 变更的同步维护规则见仓库根 `AGENTS.md`。

## Requirements

### Requirement: CLI 调用通道

外部 agent 对接的全部端点提供 CLI 等价命令（`server/app/cli.py`，`uv run --directory server python -m app.cli <cmd>`），服务端行为与 HTTP 调用完全一致。

#### Scenario: agent 端点全部有 CLI 子命令

- **WHEN** agent 需要拉取或提交平台数据（项目/材料/基线/草案/批注/版本）
- **THEN** 均可通过对应 CLI 子命令完成，无需手拼 curl

#### Scenario: 硬错误拒收明细可解析

- **WHEN** CLI 提交草案被平台 422 拒收
- **THEN** 响应体 JSON（含 hard_errors）完整输出到 stdout，退出码非 0，agent 可据此修复重交

#### Scenario: 大内容走文件传参

- **WHEN** agent 用 `import-draft --md FILE` 提交 markdown 草案
- **THEN** 文件全文作为请求体 markdown 字段发出，不经 shell 参数转义
