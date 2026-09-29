# 澄清池材料级回答（material-level clarification）· 设计 spec

> 日期：2026-09-29 ｜ 状态：P1 已实现（2026-09-29） ｜ 前置：flow-redesign-design（docs/specs/2026-09-28-flow-redesign-design.md）澄清池章节 ｜ 基线：main 12effaf ｜ 关联在途：AskDrawerV2 用户画像流 mock（已确认采纳为正式 UI 骨架，本轮正式化）

## 1. 问题：澄清池回答单位错位

现有澄清池以「一道题」为回答单位、以「选项序号」为回答形态，与真实使用场景错位：

| # | 缺陷 | 现状代码 |
|---|---|---|
| 1 | **回答方式只有文本选择题**：`answer` 只收选项序号（`idx`），无文本答案、无附件 | `router.py resolve_clarification` / `clarifications.answer` |
| 2 | **无材料级回答**：实际补充材料时往往一份材料（图片/文档/一段文字）回答多个甚至全部待问项，而不是逐题作答；补料后也没有「重新检索全部待问问题」的机制 | 无对应功能 |
| 3 | **图片/PDF 材料用不上**：截图类型禁止 AI 提取；PDF 按 utf-8 读是乱码 | `classify.py`、`_evidence_text` |
| 4 | 展示形态差（已被 AskDrawerV2 用户画像流 mock 验证解决，本轮正式化） | `AskDrawer.vue` V1 表格 |

约束与前提：
- LLM 为 DeepSeek V4.1-Flash，**原生多模态**，支持图片输入（OpenAI 兼容 `image_url` 格式）。
- QuOS 哲学：文件为真相源、证据池为一等公民、AI 产出=推测级（真伪由人定）。

## 2. 设计总览

**材料即证据：澄清池的补材料入口 = 带意图的证据入池。** 存储只有一份（`evidence/files/` + index.json），入口决定意图与落地动作：

| | 证据池入口（现有） | 澄清池入口（新增「补材料」） |
|---|---|---|
| 用户意图 | 「新材料供全流程用」 | 「这份材料回答待问问题」 |
| 落地动作 | 只入池，提取等步骤手动触发 | 入池 + `source:'clar'` 标记 + **自动触发澄清重检** |
| 溯源 | 无标记 | 证据池显示「澄清补料」来源徽章 |

第三种流向：不上传新文件，在澄清池**勾选池内既有材料**发起重检（对应「意识到某份旧文档其实答了某些题」的场景）。

核心链路：

```
澄清池「补材料」（文本/图片/pdf/docx，多份）
  → 证据入池（source='clar'）
  → 自动澄清重检 job（clar-review）：全部 wait 题 × 本次材料
       AI 逐题输出 {answer, quote, ev_ids, conf} → 存 clar.ai（待采纳）
  → 人工逐题/批量「采纳」→ 写正式答案 st='answered' → 既有规则核过联动
  → （可选）「以新材料重跑整理」pipeline job：提取→核验→冲突重扫→重检→受影响画像清单（不自动重建）
```

已确认的三个决策：整体=方案一（材料即证据+自动重检+可选编排）；**AI 代答人工采纳**（未过目不落账）；**重检范围仅本次材料**（答案引用哪份材料一目了然、成本可控）。

## 3. 数据模型扩展

```python
class Evidence(BaseModel):
    ...  # 既有字段不变
    source: str = ""            # 'clar' = 澄清池补料入口；空 = 证据池入口

class AiReview(BaseModel):       # 澄清重检的代答结果（待人工采纳）
    answer: str                  # 代答文本（choice 题=选项原文；open 题=材料归纳）
    quote: str                   # 材料原文摘录（文本材料服务端 substring 强校验）
    ev_ids: list[str]            # 引用的材料
    conf: str                    # high | med | low

class ClarAnswer(BaseModel):     # 采纳/人答后的结构化答案
    kind: str                    # 'opt'（选项）| 'text'（文本）| 'material'（材料，含人工看图作答）
    text: str                    # 答案文本（opt 时=选项文本）
    ev_ids: list[str] = []       # kind='material' 时关联证据

class Clarification(BaseModel):
    no: int
    q: str
    kind: str = "choice"         # 'choice' | 'open'（opts 为空即 open；旧数据默认 choice）
    opts: list[str] = []
    st: str = "wait"             # wait | answered | verified（models.py 现默认值 'open' 顺手修正）
    answer: str | None = None    # 兼容展示用答案文本（= ans.text）
    ref: str | None = None
    ai: AiReview | None = None   # 待采纳代答；采纳/忽略后置 None
    ans: ClarAnswer | None = None
```

兼容：`clarifications.json` 旧行缺新字段，Pydantic 默认值兜底，**不迁移**。

## 4. 材料解析升级（服务端）

| 类型 | 现状 | 目标 |
|---|---|---|
| 文本/粘贴 | 直接用 | 不变 |
| docx | 剥 XML | 不变 |
| **pdf** | utf-8 读=乱码 | **pypdf 提取文本**（新增依赖）；扫描件提不出文本时入池成功、提取时报 422 提示「扫描件暂不支持，请转图片」 |
| **图片（png/jpg/webp）** | 禁止提取 | **多模态直读**：长边 >1600px 用 Pillow 压缩（新增依赖）控 token；解除「截图禁止提取」限制 |
| 仓库/压缩包 | 不支持 | 维持不支持 |

`runner._call` 升级为多模态：`content` 由纯字符串改为 parts 数组（`[{type:'text'}, {type:'image_url', url:'data:image/...;base64,...'}]`）；纯文本任务传参不变、零影响。`complete(task, variables, schema, images: list[bytes] = [])`。

`_evidence_text` → `_evidence_parts(root, ev) -> tuple[str, list[bytes]]`（文本 + 图片字节列表）：extract / verify / scaffold / clar-review 全部消费方切换；无图片时行为与现状一致。

## 5. 澄清重检（clar-review）

**新 AI 任务** `prompts/clar-review.md` + Pydantic 输出：

- 输入：全部 `wait` 问题（no/kind/q/opts）× 本次材料 parts（仅本次，不混全池）
- 输出：`{results: [{no, answered: bool, answer, quote, conf}]}`
- 服务端校验（防幻觉）：
  - choice 题 answer 必须命中 `opts` 之一，否则视为未答出
  - 文本材料：quote 必须是材料文本 substring，校验不过 → conf 降 low
  - 图片材料：quote 无法 substring 校验，UI 标注「图片摘录·未校验」
- 落库：写入各题 `clar.ai`，`st` 保持 `wait`；先清后写（每次重检覆盖上次代答）

**Job 编排**：`kind='clar-review'`，复用 jobs 架构（单 running、GET /jobs 轮询）。题数 >20 分批（沿用 VERIFY_BATCH 模式），材料 parts 每批重复携带。成本护栏：一次重检材料文本总量 ≤ 30k 字（超出截断并在 job 里提示）、图片 ≤ 5 张/次（超出 422）。

**人工采纳闭环**（复用既有联动语义，router.py:632-637）：

- 逐题「采纳」：`ans = {kind: choice题'opt'/open题'material', text: ai.answer, ev_ids: ai.ev_ids}`，`answer=ai.answer`，`st='answered'`，`ai=None`；若 `ref` 指向规则 → 规则 `verified=True`（既有联动，不改）
- 批量采纳：全部有代答的题一次采纳（P2；P1 仅逐题）
- 「忽略」：`ai=None`，题保持 wait
- `verify`（标记已实证）语义不变

**单题人答升级**：`action='answer'` 支持 `idx`（choice）或 `text`（open，落 `ans={kind:'text'}`）；open 题可同时挂附件（附件入池 `source='clar'` 并记入 `ans.ev_ids`——人工看图作答的场景）。

## 6. 管线联动（可选编排，不自动重跑；P2）

`POST /pipeline/rerun {ev_ids}` → `kind='pipeline'` job，串行执行、单步失败记录并继续：

| 步 | 动作 | 复用 |
|---|---|---|
| 1 | 对选定材料逐份 AI 提取（含图片多模态） | `tasks.extract` |
| 2 | 新产出规则全量核验 | `tasks.verify`（分批） |
| 3 | 冲突重扫 | `tasks.conflict` + `merge_conflicts` |
| 4 | 澄清重检 | §5 |
| 5 | 汇总「受影响画像节点清单」= 新增/核验被修正规则的 `node` 去重 | 读规则 |

**画像不自动重建**（防覆盖人工编辑）：清单随 job 返回，前端在 ③生成画像 视图顶部展示「N 个节点可能过期」+「批量生成」按钮（走既有 `assemble-batch`，pipeline 已结束不占 job 槽）。**功能树不做自动调整**（scaffold 仍限树空；非空树维持侧栏人工编辑）。

## 7. 前端设计（AskDrawerV2 正式化）

上轮用户画像流 mock 转正式（去 mock、接 API），结构沿用：tabs（待问/已答/全部）+ 折叠已答 + 补材料题型 + 两段式导出。新增：

| 区块 | 设计 |
|---|---|
| **补材料投递条**（待问 tab 顶部） | 拖拽/粘贴/选择多文件（文本、图片、pdf、docx）→ 上传即入池+重检；进行中显示 job 进度（复用全局 AI 进度条） |
| **AI 代答卡** | 题卡内嵌区块：代答答案 + 材料摘录（可展开）+ 来源材料 chip（图片可预览大图）+ conf 徽章（high 绿/med 蓝/low 橙）+「采纳 / 忽略」；列表顶部「批量采纳」 |
| **单题附件** | open 题输入区旁「+附件」，入池并关联该题 | 
| **池内材料重检**（P2） | 投递条旁「用池内材料重检」：弹层勾选证据（含 clar 来源徽章）→ 发起重检 |
| 证据池 | `source='clar'` 徽章「澄清补料」；材料行「发起澄清重检」入口 |

## 8. API 变更清单

| 端点 | 变更 | 期 |
|---|---|---|
| `POST /evidence` | + 可选 `source` 参数（仅 'clar' 合法；澄清池入口传） | P1 |
| `POST /evidence/{id}/extract` | 截图类型解除限制（多模态）；pdf 走 pypdf | P1 |
| `POST /clarifications/materials` | **新增**：multipart 多文件（或 JSON 文本）→ 入池 source='clar' → 自动建 clar-review job → `{ev_ids, job_id}` | P1 |
| `POST /clarifications` | ClarIn 扩展：`answer` 支持 `idx \| text`，可选 `ev_ids[]`（open 题附件关联，附件先经 `/evidence` 上传）；新增 `adopt` / `ignore` | P1 |
| `POST /clarifications/review` | **新增**：`{ev_ids}` 用池内既有材料发起重检 | P2 |
| `POST /pipeline/rerun` | **新增**：§6 编排 job | P2 |
| `GET /jobs` | 不变（新 kind 自然透出） | — |

## 9. 边界、兼容与风险

- 附件 ≤10MB/份；重检单次图片 ≤5 张、文本 ≤30k 字（护栏，超出 422/截断提示）
- jobs 单 running 槽沿用：clar-review 与批量画像互斥，重检通常 1~2 次调用、秒级
- 新增依赖：`pypdf`（PDF 提文）、`Pillow`（图片压缩）——本 spec 批准即视为授权新增
- 多模态 token 成本：图片压缩后单图约数百~千 token 级，重检按次调用可控
- 幻觉防护：choice 命中校验 + quote substring 强校验（图片除外，UI 标注）+ 人工采纳闸门三层
- 旧数据零迁移；V1 表格 UI 与 mock 开关移除，AskDrawerV2 为唯一实现

## 10. 分期

| 期 | 内容 |
|---|---|
| **P1（本轮实现）** | 数据模型、入池入口+source、pdf/图片解析+runner 多模态、clar-review job+代答卡+采纳闭环、V2 正式化、单题文本/附件作答 |
| **P2（后续）** | pipeline 编排 job + 受影响画像清单、池内材料勾选重检、批量采纳、证据池反向入口 |

## 11. 测试要点

- 后端：模型兼容（旧 JSON 加载）、materials 入池标记与 job 创建、clar-review 输出校验（choice 命中/quote substring/conf 降级）、adopt 规则核过联动、answer text 扩展、pdf 提文（fake AI 注入）、截图提取解除限制
- 前端：V2 真实数据渲染与折叠、投递条上传流、代答卡采纳/忽略交互、conf 徽章与图片未校验标注
