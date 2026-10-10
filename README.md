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

## 快速开始

```bash
./start.sh              # 依赖检查 → 前端构建 → 启动 http://localhost:8000
QUOS_FAKE_AI=1 ./start.sh   # 假数据模式（无需 LLM key）
./start.sh --build      # 强制重建前端
```

LLM 配置走 `.env`（`QUOS_LLM_API_KEY/BASE_URL/MODEL`，不入 git）；MySQL 索引库可选（`QUOS_DB_*`，文件系统为真相源，不可达自动降级目录扫描）。

## v1.0.0 —— M1 reqspec 需求整理

首个可用版本：从材料上传到规则核验的完整闭环，真实 LLM 部署运行。

**项目管理**
- 多项目工作台：文件系统真相源 + MySQL 元数据索引（可重建）
- 项目编辑（改名/描述）、归档/恢复、输名确认删除

**需求工作台（reqspec）**
- 一键生成 → 后台流水 → 自由编辑；智能生成 full | smart（自动核验遗留疑点与范围重组）
- 功能树：任意层级解析/增删改、树编辑四能力（改名/加子/删除/加模块）
- 证据池：多模态材料（pypdf/Pillow）、材料即证据、missing 检测
- 规则库：核验通过 / 待处理两分体系（冲突多方归组、缺口补写闭环、规则修正、手动记规则）
- 澄清池：材料级问答 + AI 重检代答（人工采纳/忽略）
- 徽章一致性：归属唯一函数，树/详情/统计三端点同源，恒等式测试钉死
- 基线：git 基线历史、定稿存档、导出

**AI 引擎**
- LLM 编排器：understand / extract / verify / conflict / gap / assemble / impact，JSON 校验 + 重试闸门
- dsh headless agent 引擎（`QUOS_DSH_CMD` 可配，未配自动 off 降级直连）
- 长任务 job 化：分批真实进度、刷新可恢复、SSE 流式

**质量基线**：后端 181 + 前端 67 测试全绿。
