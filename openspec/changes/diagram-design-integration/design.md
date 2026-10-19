# Design: diagram-design 单轨图源集成

## 0. 已拍板决策（对话定稿）

| 决策 | 结论 |
|---|---|
| 图源 | 单轨 diagram-design，mermaid 全链路退役，不保留双轨 |
| 图源体积 | 不设上限（payload 为 JSON 列，无 TEXT 64KB 限制） |
| 字体 | 在线 Google Fonts，离线降级接受，不自托管 |
| 导出 md（图转图片） | 本期不做，独立 change 后置 |
| 存量 mermaid 图 | 不自动迁移，渲染降级，随迭代重画 |

以下各节中标注**【我的 call】**的为设计者取舍，供评审时纠偏；其余为已拍板决策的直接展开或现状代码锚点。

## 1. 总体架构

图的生命周期：

```
生成（agent + diagram-design skill，产自包含 HTML，存 agent 侧 figures/ 目录）
  → 提交（需求文档 md[只含图引用] + figures/ 图文件集，一并经导入通道）
  → 存储（导入时图内容收进 doc diagram 块，text = HTML 全文；payload JSON 快照冻结版本）
  → 平台渲染（前端 sandbox iframe srcdoc，禁脚本）
  → [后置] 导出（export_svg.py 纯 Python，独立 change）
```

## 2. 数据契约（server/app/models.py）

- `diagram` 块 `text` 语义：mermaid 源码 → **自包含 HTML 全文**（`<!DOCTYPE html>` 开头的完整文档，diagram-design 产物形态）。
- **【我的 call】不加 `source` 判别字段**：单轨后 text 即 HTML；存量块是否 mermaid 由渲染端特征识别（text 以 `<` 起且含 `<svg`/`<!DOCTYPE` 为 HTML，否则按存量 mermaid 降级），判别只服务存量过渡，不进契约。
- `figure`（线性链路）块保留：仍是文本形态（每行一条 `A → B → C`），语义不变；变化仅在渲染（见 §5）与 skill 等价形态表述（figure 不再承诺「真图」）。
- 块类型注释同步：`diagram(自包含 HTML 图源,diagram-design 产物,前端 sandbox 渲染)`。

## 3. agent 产出物契约与 md 导入（server/app/services/md_import.py）

### 产出物分离（本 change 的架构原则）

图源与文档在 **agent 产出层分离**，在 **平台存储层内嵌**：

- agent 产出物 = 需求文档 md（正文只含图**引用**）+ `figures/` 目录下若干 HTML 图文件；
- 导入时平台解析引用，把图文件内容收进 diagram 块（text=HTML 全文），存储/快照/渲染维持单块内嵌——payload JSON 快照天然冻结图版本，不建图资产表、不做引用间接层。

### 引用语法

- md 正文的图以标准图片语法引用：`![图意图](figures/<slug>.html)`，如 `![需求文档主链路](figures/main-flow.html)`。
- **合法位置口径（块生成与闭合校验同口径，防静默丢图）**：图引用必须**独立成行**（前后仅空白）才解析为 diagram 块；md 任何其他位置（列表项内、表格单元格内、行内混排、引用块内）出现指向 `.html` 的图片引用 → 一律硬 422（FORMAT_CONTRACT 族，detail 带位置与修法「图引用须独立成行」），不静默剔除、不静默丢图。闭合校验的全文扫描与块生成按同一口径判定。
- alt 文本 = 图的意图提示（重画时给 diagram-design 的输入），不进块（图 HTML 自带 eyebrow/h1 标题）；slug 用 kebab-case。
- 仅识别 `.html` 目标；`figures/` 目录为约定位置。本期只收 HTML 一种图文件（SVG 等后置）。
- 原设计中的「diagram-design 四反引号围栏」方案**作废**——md 不再内嵌 HTML 图源，围栏自闭合问题不复存在，md_import 无需新增围栏分支与连字符正则适配。

### 导入通道（接口变更）

- API：`POST /api/v1/projects/{pid}/doc/draft/import` 改为 multipart——md 全文 + 图文件集（`figures` 多文件 part）；也兼容纯 md 无图提交。
- CLI：`import-draft` 扩展 `--figures <dir>` 参数（目录内文件即图集），与 md 一并提交。按根 AGENTS.md 铁律同步 `cli.py` / `docs/quos-agent-api.md` / `docs/api.md`。
- 引用闭合校验（硬）：md 引用的 `figures/<slug>.html` 未出现在提交文件集 → 422（FORMAT_CONTRACT 族，detail 带引用位置）；提交了未被引用的图文件 → 软警告（可能是废稿，提示清理）。
- 存量 `mermaid` 围栏：照旧入 diagram 块（text=mermaid 源码），前端按存量降级路径渲染（源码+重画提示），校验侧对非 HTML 形态出软警告（见 §4）——「旧契约 md」与「存量基线图」共用一套机制。
- ASCII 盒子图路径保留不变；其 R1 告警维持现行硬 422 语义。

## 4. 校验（server/app/services/）

现状锚点：doc.py L98 导入时逐图 `check_mermaid`（node 端 mermaid.parse）；validators.py L146 diagram 块仅校验 text 非空。现状 R1 全部产出为 FORMAT_CONTRACT 硬 422，「软警告」需显式分流。

- **vendor self_check**：将 skill 的 `skills/diagram-design/scripts/self_check.py`（MIT，头部保留版权注释）复制为 `server/app/services/diagram_check.py`，作为平台侧 HTML 图结构校验器。校验项：自包含（无外部 script/img 依赖）、SVG 可访问契约（title/desc 存在且 id 前缀化）、内容不越界 viewBox。适配两处：文件接口改为字符串接口；移除 motion script 白名单（平台图静态）。
- **两级分流**（HTML 形态判别：text 含 `<svg` 或 `<!DOCTYPE html`）：
  - HTML 形态 + 结构非法（缺 title/desc、含 script/事件属性/外链资源、内容越界）→ **硬 422 拒收**（FORMAT_CONTRACT 族，detail 带块位置与失败项）；
  - **非 HTML 形态（mermaid 源码等）→ 软警告不拒收**（「图源已单轨为 diagram-design，请重画」，并入校验报告 soft_warnings 通道，agent 修复轮感知后重画）。软的 rationale：存量项目的旧基线图在增量重提整份 payload 时仍会携带，硬拒收等于存量项目无法迭代；重画随迭代自然完成。
- 接入点两处：导入路径（doc.py 现 check_mermaid 接线位）与 draft 直传路径（check_draft 的 diagram 块校验升级），分流规则一致。
- `mermaid_check.py` 删除；server 对 web/node_modules/mermaid 的运行时依赖解除（node 子进程调用路径移除）。
- R1 组规则重写：删「mermaid 节点半角括号」「mermaid 保留字」两条；新增「diagram 块非 HTML 形态 → 软警告重画」；ASCII 盒子图条目维持。

## 5. 前端渲染（web/src/components/rev/DiagramView.vue）

现状锚点：mermaid.render + flows 自动转 flowchart TD + 失败降级流程条/源码；唯一消费方 DocPaper.vue（评审页）。

- **HTML 图分支**：`source` 为 HTML（特征识别同 §2）时，以 `<iframe sandbox="allow-same-origin" srcdoc="{html}">` 渲染。
  - sandbox 不含 `allow-scripts`：脚本执行被浏览器禁止（XSS 主防线）；
  - 含 `allow-same-origin`：仅为 onload 后读 contentDocument 高度做自适应（**【我的 call】**——替代方案是按 doc-inline viewBox 固定比例高度，但 skill 支持多种尺寸预设，自适应更稳）；
  - 宽度 100%，高度 onload 自适应 contentDocument.body scrollHeight，写入前 clamp 上限（防异常 HTML 撑爆页面）。
- **存量 mermaid 块**：走降级路径——显示源码 + 提示条「存量 mermaid 图，待迭代重画为 diagram-design」（复用现 mmd-degraded 样式与语义）。
- **flows 流程条转正**：线性链路不再自动生成 flowchart TD，直接以现降级路径的 flowbox 流程条呈现（该 UI 已存在，转正为主路径）。
- 依赖清理：删除 mermaid import、initialize、竞态守卫与残留清理逻辑（iframe 无 mermaid 的异步竞态问题）；`web/package.json` 移除 mermaid 依赖。
- 深色侧栏适配：图自身为暖纸面底色（diagram-design 设计系统），iframe 内自带背景，不做主题注入（**【我的 call】**：图的编辑设计完整性优先于平台主题统一）。

## 6. agent 侧 skill（.agents/skills/）

### req-organize（只留引用关系，画图主体责任在外部 skill）
- 图纪律收敛为**意图级**三件事：
  1. **主链路必须落图**：核心流程至少一张图，正文以 `![图意图](figures/<slug>.html)` 引用；线性 `A → B → C` 链路降为次级链路/文内小链路的轻量形态（figure 块）。
  2. **引用约定**：图文件放 `figures/` 目录、kebab-case 命名、只引用 `.html`、**引用必须独立成行**（列表/表格/行内混排放图引用会被平台 422 拒收）；图的实际绘制（图型选择、设计纪律、自检）全部交给 diagram-design skill，organize 不写任何画图逻辑。
  3. **产出物形态**：一次交付 = 需求文档 md + figures/ 图文件集，两者一并经导入通道提交。
- 「配套对接」节新增：声明对 `~/.agents/skills/diagram-design` 的依赖与安装命令（`npx skills add cathrynlavery/diagram-design`）、调用方式（把图的意图描述交给该 skill 产 HTML，存入 figures/）、无 skill 时的降级（线性链路兜底，不出 HTML 图）。
- **【我的 call】图型映射表不进 req-organize**：图型选择是 diagram-design 自己 SKILL.md 的 Selection 职责，organize 只表达「此处要一张什么意图的图」；皮肤与中文字体规则同样归属 diagram-design 使用说明（在配套对接节一句带过：默认皮肤、font link 追加 Noto Sans SC/Serif SC），不展开。

### req-review
- R 组图判据改写：图质量判据（是否超复杂度预算、形状是否乱用、self_check 是否通过）替代 mermaid 语法判据；发现存量 mermaid 图 → 标记建议重画。

### req-onepager
- 无图，不波及（SKILL.md 已核对零图引用）。

## 7. 存量迁移

- 不写自动迁移脚本。存量 diagram 块（mermaid 源码）在新前端下降级显示源码 + 重画提示。
- 重画路径：agent 在项目下次文档迭代时，用 skill 的 import-mermaid 流程（mermaid_extract.py 提取 digest → 按 type reference 重画）产出新图，随新草案导入。
- 演示项目（5175 项目 5）人工触发一次全链路重画验证：agent 重画 → 导入 → 校验 → 评审页渲染。

## 8. 规则与文档同步（项目铁律）

- `docs/api.md`：import-draft 条目重写——multipart 请求结构（md 全文 + figures 文件集 + rules_meta）、图引用语法与独立成行口径、引用闭合 422、非 HTML 形态软警告项、DIAGRAM_* 错误码。
- `docs/quos-agent-api.md`：CLI 命令表 `import-draft` 行加 `--figures <dir>` 参数说明。
- 根 `AGENTS.md`：命令清单本身不含参数，不动；「CLI 同步」铁律清单已含 import-draft，按此执行。
- `openspec/specs/`：本 change delta 合并（doc-pipeline / web-workbench）。

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| iframe srcdoc 的 XSS 面 | sandbox 禁脚本（浏览器层）+ diagram_check 禁 script/事件属性（校验层）双保险 |
| agent 环境缺 diagram-design skill | req-organize 配套对接节声明依赖与降级路径（线性链路兜底） |
| Google Fonts 在线依赖 | 已拍板接受离线字体降级 |
| 存量图体验倒退（降级源码显示） | 有重画提示文案；演示项目先行重画验证 |
| skill 上游变更（self_check 语义变化） | vendor 版本锁定在本 change，后续手动同步 |

## 10. 实施切分（供 tasks.md）

1. server：models 注释契约 → md_import 图引用解析（图片语法 .html → diagram 块）与引用闭合校验 → diagram_check vendor 与硬软分流 → doc.py/validators.py 接线 → 删 mermaid_check。
2. server 接口：import API 改 multipart（md + figures 文件集）→ cli.py `import-draft --figures` → api.md / quos-agent-api.md / AGENTS.md 同步。
3. web：DiagramView HTML 分支 + 存量降级 + flows 转正 → 删 mermaid 依赖 → 真机渲染验收。
4. skills：req-organize 图纪律收敛为意图级引用 + 配套对接节 → req-review R 组改写。
5. 验证：单测（md_import 引用解析与闭合/diagram_check/validators 定向）→ 演示项目全链路重画（md + figures 提交）。
