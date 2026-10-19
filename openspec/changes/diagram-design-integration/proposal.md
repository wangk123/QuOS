# Proposal: diagram-design 单轨图源集成

## Why

mermaid 自动布局不可控，AI 生成图观感差，是文档质量的显性短板；QuOS 的图没有人手改这一环、改图全由 AI 按建议执行，所以「给 AI 换画图工具」与「图质量提升」是同一条路径。diagram-design skill（cathrynlavery/diagram-design，57K stars，MIT）以编辑设计系统产出自包含 HTML+SVG 图，自带校验（self_check）、导出（export_svg，纯 Python）与 mermaid 存量迁移（mermaid_extract）链路，2026-10 试点已在 QuOS 需求文档主链路图上验证质量并验收。平台单轨切换：图源从 mermaid 源码统一为 diagram-design 自包含 HTML，mermaid 全链路（渲染/校验/契约）退役。

## What Changes

- **架构原则：图源与文档在 agent 产出层分离、平台存储层内嵌**。agent 交付 = 需求文档 md（正文只含 `![图意图](figures/<slug>.html)` 引用）+ `figures/` HTML 图文件集；导入时平台把图内容收进 diagram 块，payload 快照天然冻结图版本，不建图资产表。
- **数据契约**：diagram 块 text 语义从 mermaid 源码改为自包含 HTML（diagram-design 产物）；figure（线性链路）保留文本形态，渲染转正为流程条（不再自动转 mermaid 真图）。
- **md 导入契约**：import API 改 multipart（md + figures 文件集）、CLI `import-draft` 增 `--figures`；图引用解析入 diagram 块；引用闭合为硬校验（引用文件缺失 422）；存量 mermaid 围栏照旧入块 + 软警告提示重画。
- **校验换血**：node 端 mermaid.parse（mermaid_check.py）退役；vendor skill 的 self_check.py 为 `diagram_check.py` 接入两级校验；硬软分流——HTML 形态结构非法（缺 title/desc、script/事件属性/外链、越界）422 拒收，非 HTML 形态（存量 mermaid）软警告放行。
- **前端渲染**：DiagramView 的 mermaid.render 分支替换为 sandbox iframe srcdoc（禁脚本）；存量 mermaid 块渲染降级显示源码 + 重画提示；flows 流程条渲染转正；移除 web 的 mermaid 依赖。
- **skill 三件套**：req-organize 图纪律收敛为意图级（主链路必须落图 + 引用约定 + 产出物形态），画图逻辑零条——图型选择/设计纪律/自检全归 diagram-design skill，配套对接节只留依赖声明与调用方式；req-review R 组图判据同步改写；req-onepager 无图、不波及。
- **存量迁移**：不写自动迁移；存量 mermaid 图渲染降级，随文档迭代由 agent 按 skill 的 import-mermaid 流程重画；演示项目人工触发一次重画作全链路验证。
- **后置（不在本 change）**：导出 md 时图转 SVG 资产、PNG 光栅化（Playwright 依赖）、字体自托管、品牌 profile marker。

已拍板决策：单轨（不留 mermaid 双轨）；不设图源体积限制（payload 为 JSON 列，无 64KB 风险）；字体走在线 Google Fonts、离线降级可接受；req-organize 不含画图逻辑，只保留引用关系。
