# QuOS v2

Quality OS —— 质量工作台。平台只做三件事:**给 agent 定标准(接口+两级校验)、给人做闸门(批注式评审)、给文档管生命周期(版本)**。AI 加工完全外部化(外部 agent + 项目内 skill),平台不内置任何 LLM。

## 架构

```
外部 agent(ZCode 等)+ skill(.agents/skills/req-organize)
        │ HTTP(localhost)
        ▼
QuOS 平台(FastAPI):统一 REST + 两级校验闸门 + 批注/草案/版本状态机
  SQLite(唯一真相源 server/data/quos.db)+ 文件系统(材料二进制)
        ▲ 浏览器:材料上传 / 批注式文档评审 / 定稿发版 / 版本回退
```

- 设计与规格:`openspec/changes/archive/2026-10-15-quos-v2-rebuild/`(design + specs 六能力域;ADR 见 `docs/adr/`)
- 需求整理加工协议:`.agents/skills/req-organize/SKILL.md` 「平台对接」章节

## 快速开始

```bash
cd server && uv sync && uv run uvicorn app.main:app --port 8000   # 后端
cd web && npm install && QUOS_API=http://127.0.0.1:8000 npx vite  # 前端(默认 8000,可覆盖)
cd server && uv run pytest tests/ -v                               # 测试
```

## 核心流程

材料上传 → agent 拉材料与基线、按 skill 加工 → `POST /doc/draft` 过两级校验(硬错误 422 拒收 / 软警告转批注锚进正文)→ 人在评审页批注式作答(答完转绿)→ agent 取 answered 收敛重交 → 人自定义版本号定稿发版 → 版本页查变更记录 / 回退基线。

版本只增不改;规则编号项目内稳定、作废留痕;批注按题型+关键内容跨草案去重。
