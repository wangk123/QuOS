# Proposal: doc-reading-experience — 需求文档阅读体验平台化(钉钉听记风格落地)

## Why

原型 R1(`web/prototype/doc-visual-r1.html`,已合入 main)验证了钉钉 AI 听记「智能切片主题模板」的 9 项展示手法在需求文档上的阅读收益:章级主题色形成视觉切片、行内强调染色构成扫读快车道、文档头概要+统计+读者路径建立 1 分钟入口、TBD 待办化集中呈现。用户确认方向后要求平台化。

平台现状距原型差三块:①渲染层无章级视觉编码(para 纯文本、无速览、无文档头聚合);②契约层无强调语义(md 导入把 `**粗体**` 清洗为【括注】)、无文档头元数据(概要/关键词/读者路径)、无卡片块;③生成侧(req-organize skill)无对应纪律。

## What Changes

三阶段,每阶段独立可交付、独立可回退:

- **P0 渲染层强化(零契约变化)**:章级主题色+编号徽章、章末规则速览条、文档头统计 chips(前端派生)、目录滚动联动高亮。旧数据立即受益,无任何服务端改动。
- **P1 行内强调(小契约改动)**:para 与规则 text 支持 `**强调**` 标记;md 导入从「粗体转【】」改为「保留成对标记」;前端 esc 后白名单渲染为章色强调;**批注锚定/术语搜索在剥离标记的文本上执行**(锚点不漂移);不成对 `**` 按格式契约硬拒收;染色密度 lint 软警告转题。
- **P2 结构增量(可选字段,缺省降级)**:meta 增可选 `summary/keywords/reader_paths`;新块类型 `cards`(知识卡片);文档末尾「待确认问题」汇总区(读侧聚合自批注数据,不另立数据结构);req-organize 同步生成纪律。

## Impact

- **specs**:doc-pipeline(文档形态契约、markdown 导入、新增文档头元数据 Requirement)、web-workbench(文档评审页布局、正文批注与规则锚点)。
- **代码**:server(models.py 契约默认值、md_import、validators)、web(DocPaper.vue、style.css)、`.agents/skills/req-organize/SKILL.md`。
- **兼容**:全部新字段可选+读侧降级,已入库草案(draft 51 等)零迁移零改动;旧数据渲染不劣化(无标记则无强调、无 summary 则无概要区)。
- **不做**(non-goals):`steps` 步骤条块(与 figure/diagram 语义重叠,链路一律走既有两形态);TBD 独立数据结构(走批注体系);主题色/染色的用户自定义配置。
