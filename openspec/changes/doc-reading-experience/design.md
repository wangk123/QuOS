# Design: doc-reading-experience

> 设计基线:main@f14ac42(已 merge 入 proto/doc-visual-r1)。原型参照:`web/prototype/doc-visual-r1.html`。
> 标注约定:凡「**取舍**」开头的决策是设计者替用户做的判断,评审时可推翻;推翻只影响对应小节,不牵动架构。

## 0. 现状锚点(方案针对的代码事实)

| 事实 | 位置 | 对方案的意义 |
|---|---|---|
| para 块纯文本插值 `{{ b.text }}` | `DocPaper.vue:175` | 强调渲染的唯一改造点 |
| 规则文本已有 esc→html 管道(`ruleHtml`,mark 高亮) | `DocPaper.vue:59-79` | 强调标记复用同管道,先 esc 后替换,XSS 面不扩大 |
| 规则 popover(violation/quote/材料 hash)已有 | `DocPaper.vue:219-236` | 原型手法⑤平台已落地,不重做 |
| 批注锚定 = `text.includes(anchor.seg)` 子串匹配 | `DocPaper.vue:60,69` | **标记字符若留在文本中会使 seg 匹配失配**——锚定必须先剥标记 |
| md 导入把 `**粗体**` 转【括注】 | `md_import.py:27`(`_clean_inline`) | P1 改为保留成对标记 |
| 块契约 para/states/table/figure/exceptions/diagram | `models.py:136-148`(BlockInChapter) | P2 增 cards 类型 |
| 附录 TBD 已转批注(fill/confirm/choice)+三级锚定 | doc-pipeline spec「附录问题清单转批注」 | P2 待确认汇总区数据源=批注,不另立结构 |
| 术语出现章搜索(`termChapters`) | `utils/chapters.ts` | 同样需剥标记后匹配 |
| 图渲染统一 mermaid(DiagramView,flows 自动 flowchart) | `DiagramView.vue` | 原型「流程链/状态链」手法由它承载,P0 仅做视觉强化 |

## 1. P0 渲染层强化(零契约变化)

全部在 `DocPaper.vue` + `style.css`,不改任何接口与数据。

1. **章级主题色 + 编号徽章**:章节渲染序(扁平化后的 index)映射到固定 10 色循环(青/靛/蓝/紫/琥珀/绿/玫红/石板/天蓝/深灰,600 为主色 700 为文字色,白底对比度 ≥4.5:1);章号徽章、章内强调色、速览条、待确认题型徽章全部取章色。**取舍**:配色循环写死前端,不做语义映射(如"安全章永远红")——章的主题由内容决定,固定映射会僵化。
2. **章末规则速览条**:每章规则区末尾渲染 `FR-xxx` chips(点击滚动到对应规则行),数据从 `chapter.rule_nos` 派生。**取舍**:原型里速览在章末,平台放章末(读完整章后回查)而非章首(章首已有 background 概览,再放速览重复)。
3. **文档头统计 chips**:章节数 / 规则数(active)/ 待答批注数 / 术语数,全部前端从 payload + annos 计算,不让 AI 申报(杜绝编造)。含 draft 状态徽标(已有)。
4. **目录滚动联动**:文档区容器 scroll 事件(已有独立滚动结构)计算当前章,目录项高亮。被动监听,不引入 IntersectionObserver 依赖。

**验收**:云风控(22 规则)与瀚海两项目打开,视觉编码成立;旧 draft 无任何行为变化(纯 CSS/模板层)。

## 2. P1 行内强调(小契约改动)

### 2.1 契约与导入
- `**强调**` 语法进入 para.text 与规则 text 的合法字符集;`_clean_inline` 删除「粗体→【】」转换,保留成对 `**` 原样入库。**取舍**:只认 `**` 一种标记,不支持斜体/行内代码染色——一种语义一种语法,词表克制。
- **标记字段范围(口径)**:`**` 仅允许存在于 para.text 与规则 text;其余一切经 `_clean_inline` 的字段——章节标题、表格表头与单元格、figure flows、violation、meta.scope、术语释义——一律**剥星号保留内文**(不转【】、不拒收)。理由:表格里 `**是**` 不该挡导入,【】转换是新语义下的历史包袱,保留则会满屏裸星号(这些字段全是纯文本插值)。`_clean_inline` 拆为 `keep_marks`(para/规则)与 `strip_marks`(其余)两个入口。
- 不成对 `**`(奇数个)按格式契约 fail fast:422 `FORMAT_CONTRACT`(与既有 ASCII 盒子图同级),detail 给位置与修法;校验范围同样只有 para.text 与规则 text。
- 表格单元格不支持标记(剥星号落地,见上)。**取舍**,可推翻。

### 2.2 前端渲染
- `DocPaper` 新增 `hl(text)`:esc 后把 `**x**` 替换为 `<em class="hl">x</em>`(章色),用于 para 与规则行;规则行与批注 mark 高亮叠加时顺序为:esc → 替换强调 → 注入 mark(mark 的 seg 在剥标记文本上求位置,见 2.3)。
- **取舍**:数字/代码标识符不做独立样式类(原型有 `.num` 类)——降低生成侧要求,`**` 标了就染,前端不猜哪些该特殊。

### 2.3 锚定不漂移(本阶段核心风险)
- 新增 `stripMarks(text)`:`**x**` → `x`。三处消费点改在剥标记文本上执行:
  1. 前端批注 seg 锚定(`ruleHtml` 的 includes/replace);
  2. 术语出现章搜索(`termChapters`);
  3. 服务端附录 TBD 正文标注搜索(【TBD-xx】所在章定位)与 quote 相似度匹配输入(text 侧)。
- 渲染与匹配分离原则:**匹配永远用纯文本,渲染永远在 html 上**。规则 quote 字段本身不含标记(素材原文切片),不受影响。
- **seg 与标记边界相交的口径(builder check 提出)**:seg 一部分在标记内一部分在外(如 text=`...为 **6 位数字**`,seg=`码为 6 位数字`)时,朴素 esc→replace 会静默丢锚,不可接受。渲染管道定为**统一区间模型**:对每段文本先在纯文本上求出批注 mark 区间(偏移),再求出 `**` 强调区间,按区间生成嵌套 html(mark 与 em 同时呈现);当 seg 与多个强调区间碎片相交导致嵌套不成立时,降级为整段 seg 用 mark 包裹、该处强调退为普通文本。禁止任何静默丢锚路径。

### 2.4 生成侧与质量 lint
- `req-organize`「markdown 格式契约」增强调纪律:值得标的三类词——术语首次出现、量化数字与阈值、代码标识符/配置项;密度上限约每百字 ≤3 处;一段最多标 5 处。禁给整句加粗。
- 服务端软 lint,**度量口径(builder check 提出,操作性定义)**:逐章计算,分母 = 该章全部 para.text 与规则 text 剥标记后的字符总数,分子 = 该章成对 `**` 标记次数;比率 > 3 处/百字,或存在单个标记内文本剥空白后 ≥20 字符且含句终标点(。;!?;视为整句加粗)→ soft warning 转确认题,不阻塞入库。
- `req-review` R 组(可渲染组)增 R6:强调标记成对、密度合规、无整句加粗。

## 3. P2 结构增量(可选字段,缺省降级)

### 3.1 契约(models.py,全部默认空,零迁移)
```
DocMeta 增:  summary: str = ""            # 一句话概要(≤60 字)
             keywords: list[str] = []
             reader_paths: list[{role: str, ch_ids: list[str], skip: str = ""}] = []
BlockInChapter 增 type == "cards":
  { title, items: [{icon: str = "", title: str, lines: list[str], badges: list[str] = []}] }
```
- icon 为语义枚举(user/users/shield/key/clock/phone/alert/check/flow/db/gear/book/flag/target),非法值降级为无图标,不拒收(视觉件不设硬门)。
- 校验:cards.items 非空且每项 title 非空(空块硬拒,沿用 BLOCK_* 口径);keywords 3-8 个;reader_paths 的 ch_ids 必须闭合(引用不存在章节 → 硬错误,同 CHAPTER_PARENT_* 家族)。

### 3.2 渲染(DocPaper)
- **文档头**:verLabel 下方渲染 summary(有则显示)+ keywords chips + 读者路径行(role + 章节 chips 跳转 + skip 文案);无则整区不渲染——旧数据零感知。
- **cards 块**:两列网格(≤2 项单列),图标+语义标题+要点列表+badges chips,配色取章色;**导出/降级口径**:cards 无对应 md 语法,md 交付物(平台外)由 agent 侧 skill 负责降级为「小标题+列表」;平台内版本快照存 payload 原样。
- **待确认问题汇总区**:术语表章之前渲染一张卡片区,数据 = `source=agent && status=pending` 的批注(现成数据),呈现题型徽章(选择/确认/填空)+题面摘要+规则引用 chip(点击 → 激活右栏对应批注卡);pending 清零则整区不渲染(定稿自然消失)。**取舍**:汇总区是纯读侧聚合视图,批注右栏仍是唯一交互与裁决入口,不产生第二套 TBD 数据——避免与批注体系双轨。
- **取舍**:不加 `steps` 块(原型编号步骤链)——链路已有 figure(线性链自动 flowchart)与 diagram(mermaid)两形态,steps 是第三个链路块,语义重叠;原型中 steps 的视觉效果由 mermaid flowchart TD 等价承载。

### 3.3 生成侧(req-organize)
- 文档骨架「文档头」层增生成纪律:summary 一句话(这文档解决什么、范围多大);keywords 3-8;读者路径按文档头已声明的读者对象逐类给「先读哪几章(章节标题)、可跳什么」。
- 卡片使用判据:用户类清单、端到端场景、痛点清单三类内容,条目 ≥2 且每条可独立成卡时用 cards;其余仍用 para/table。不强迫卡片化。

### 3.4 md 导入
- summary/keywords/reader_paths/cards **不做 md 自动转换**(md 无对应语法,agent 走 payload 路径或后续再议)。**取舍**:导入路径保持行为不变,把格式契约复杂度压在最小面。

## 4. 困难应对对照(前期分析 → 本设计)

| 前期识别的困难 | 设计解法 | 残余风险 |
|---|---|---|
| 批注锚点漂移 | 匹配剥标记、渲染在 html;cards 为新增块不动既有块 | 需回归瀚海 18 条批注锚定 |
| AI 染色质量漂移 | skill 三类词纪律+密度上限;服务端密度 lint 软转题;review R6 | 密度阈值需按实测定参(初始 3 处/百字) |
| 导出保真 | `**` 与 md 同源无损;cards 降级规则落在 skill 侧 | 无平台内 md 导出端点,无需平台改 |
| XSS | esc→白名单替换,复用 ruleHtml 管道,不引入新 v-html 面 | — |
| TBD 双轨 | 汇总区=批注只读聚合 | — |
| 工程协调 | 基于 merge 后 main 现状设计,继续在 proto/doc-visual-r1 分支 | 合并回 main 时按惯例 squash |

## 5. 测试与验收

- **server**(pytest,定向):契约默认值兼容(旧 payload load 不报错、新字段缺省);不成对 `**` 拒收;cards 空块拒收;reader_paths 引用不闭合拒收;密度 lint 软警告;stripMarks 服务端消费点(附录标注搜索)用带标记文本回归。
- **web**(vitest,定向):hl() 渲染(成对替换/不成对原样);剥标记后批注 seg 锚定仍命中;术语搜索带标记命中;cards/summary/keywords/reader_paths 缺省时区块不渲染;速览 chips 与规则行联动。
- **真机验收**:①云风控 md 重导(含 ** 标记的新版)→ 文档头/染色/速览/待确认汇总区全要素;②瀚海旧 draft(无新字段)→ 降级渲染无劣化、18 条批注锚定不丢;③P0 独立验收(改造前后同数据对比)。
- **验收基准**:原型 R1 的 9 手法中,①②③(部分)⑤⑥⑦⑧⑨ 在平台复现;③概要/关键词/读者路径与④卡片为 AI 新产能,依赖一份用新纪律生成的文档做终验(steps 手法由 diagram 等价,见 §3.2 取舍)。

## 6. 实施顺序与规模预估

| 阶段 | 内容 | 规模 |
|---|---|---|
| P0 | DocPaper 模板+CSS+scroll-spy | 前端 1 个组件内,约 +150 行样式 |
| P1 | md_import 一行语义反转+校验+stripMarks 三消费点+前端 hl() | server ~80 行 / web ~40 行 / skill 增节 |
| P2 | 契约字段+cards 校验+渲染四件套+skill 纪律 | server ~120 行 / web ~250 行 / skill 增节 |

每阶段独立提交、独立可验收;P0 先行(纯收益),P1/P2 依次进入。实施计划(writing-plans → tasks.md)在本设计评审通过后产出。
