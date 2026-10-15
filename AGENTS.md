# QuOS 项目开发规则

> 本文件由 ZCode 及通用 agent 约定在每次会话自动加载。维护机制：文档随接口演进由改接口的 agent 同步维护（不是人工事后补）。

## 1. 接口文档同步

任何接口增删改（端点、参数、请求体、响应结构、错误码），**同一次改动必须同步 `docs/api.md` 对应条目**。

文档漂移即对接断裂：外部 agent 按 api.md 对接，漏一条字段就是一次 422 往返。agent 是接口文档的第一维护人。

## 2. CLI 同步

agent 对接接口（`projects` / `materials` / `baseline` / `draft` / `import-draft` / `submit-draft` / `questions` / `post-questions` / `versions` / `changes`）增删改，**同一次改动必须同步**：

1. `server/app/cli.py` 对应子命令；
2. `docs/quos-agent-api.md`「CLI 调用」节的命令表；
3. `.agents/skills/req-organize/SKILL.md`「配套对接」节的指引（若涉及调用方式变化）。

CLI 是外部 agent 的首选对接通道，不同步等于接口变更未完成。
