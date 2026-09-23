# QuOS

Quality OS —— 质量操作系统。

## 定位

全质量域工作台：需求整理、案例设计、缺陷管理、回归自动化、性能、安全模块化集成。为 AI 深度协作的测试流程而设计——内核（功能树、证据池、基线、AI 编排器、判断规则库）统一支撑所有模块。

当前由单人使用与开发；架构不设单人限制，模块与内核均按可扩展设计。

## 架构

```
内核（树 / 证据 / 基线 / AI 编排 / 规则库）
  └── 模块：reqspec · casegen · defect · rerun · perf · sec
```

- 总体架构：[docs/architecture.md](docs/architecture.md)
- 需求文档：[docs/requirements.md](docs/requirements.md)
- 模块路线：[docs/roadmap.md](docs/roadmap.md)
- reqspec 设计 spec：[docs/specs/2026-09-23-reqspec-design.md](docs/specs/2026-09-23-reqspec-design.md)

## 状态

立项完成。M1（reqspec 需求整理）spec 已定稿，交互原型：`prototype/reqspec.html`（浏览器直接打开，支持一键演示）。
