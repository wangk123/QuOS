# doc-pipeline Delta

## MODIFIED Requirements

### Requirement: 文档形态契约
章节正文 SHALL 由有序自由块(blocks)组成,块类型为 para(叙述)/states(状态链/流程, → 连接)/table(表格)/figure(链路图,每行一条)/exceptions(异常路径)/diagram(mermaid 源码,统一图渲染)/cards(知识卡片组:图标+语义标题+要点,承载用户类/场景/痛点等可成卡内容);章节可经 parent 指向父章节 id 构成层级。正文不再有固定槽位,表格与主链路以块承载、不得拆散塞入规则 text。
para 与规则 text SHALL 支持行内强调标记 `**强调**`(成对出现);批注锚定、术语出现章搜索及附录标注定位 SHALL 在剥离标记后的纯文本上执行,标记仅用于渲染强调。
文档 meta SHALL 支持可选字段:summary(一句话概要)、keywords(3-8 个)、reader_paths(每类读者的先读章节与可跳说明,章节 id 须闭合)。

#### Scenario: 结构化内容成块
- **WHEN** agent 产出含参数表与主链路的章节
- **THEN** 参数表以 table 块、主链路以 figure 块呈现在正文,规则 text 只保留行为级约束

#### Scenario: mermaid 图成 diagram 块
- **WHEN** agent 产出含 mermaid 代码块的文档
- **THEN** mermaid 源码原样进入 diagram 块,前端统一真图渲染

#### Scenario: 块结构与层级硬校验
- **WHEN** 草案含空块(如 table 无 rows、cards 无 items)、未知块类型、或 parent 指向不存在/成环
- **THEN** 平台拒收并返回 BLOCK_*/CHAPTER_PARENT_* 错误明细

#### Scenario: 用户类成卡
- **WHEN** agent 产出用户类清单(≥2 类,每类含特征与能干什么)
- **THEN** 以 cards 块承载,每用户类一张卡;渲染缺 icon 时降级为无图标卡片

#### Scenario: 行内强调标记成对校验
- **WHEN** para 或规则 text 含不成对 `**`(奇数个星号标记)
- **THEN** 平台 422 拒收(FORMAT_CONTRACT),detail 指明位置

#### Scenario: 标记不干扰锚定
- **WHEN** 含 `**图形验证码**` 标记的规则文本上锚定 seg 为「图形验证码」的批注
- **THEN** 锚定在剥离标记的文本上命中,渲染时强调与批注高亮同时呈现

#### Scenario: 文档头元数据校验
- **WHEN** reader_paths 引用不存在的章节 id,或 keywords 为 2 个
- **THEN** 引用不闭合硬拒收;keywords 数量越界软警告转题

### Requirement: markdown 导入
平台 SHALL 提供 POST /api/v1/projects/{pid}/doc/draft/import:接收 markdown 全文与可选 rules_meta(规则级精修 violation/quote),内置转换为 DocPayload(章节层级/规则编号三格式/正文块/表格/术语表/mermaid 围栏原样入 diagram 块/行内成对 `**` 强调标记保留),quote 自动匹配项目材料文本(相似度达标挂出处,未达标留空走软警告),转换后走与手工提交完全相同的两级校验与覆盖落库。summary/keywords/reader_paths/cards 不做 md 自动转换(agent 走 payload 提交路径承载)。

#### Scenario: 纯 markdown 导入自动挂出处
- **WHEN** agent 提交 md 文档(未携带 rules_meta),其中规则文本与某材料句相似度达标
- **THEN** 该规则自动挂该材料出处;未匹配规则 quote 留空,软警告不阻塞,由人工评审补

#### Scenario: 携带精修值导入
- **WHEN** 导入请求携带 rules_meta 中 FR-101 的 violation 与 quote
- **THEN** 精修值优先于自动匹配,校验与落库结果与手工构造 payload 提交一致

#### Scenario: 格式契约违规导入即拒收
- **WHEN** md 含 ASCII 盒子图、mermaid 节点半角括号、引用块承载实质内容、不成对 `**` 标记,或 mermaid 语法错误(node 端真实 parse)
- **THEN** 平台 422 拒收(FORMAT_CONTRACT/MERMAID_SYNTAX,detail 带位置与修法),agent 修复重导,全程无人工

#### Scenario: 成对强调标记保留
- **WHEN** md 正文含 `**6 位数字**` 粗体
- **THEN** 导入后 para.text 保留 `**6 位数字**` 原样(不再转换为【】),前端渲染为强调

## ADDED Requirements

### Requirement: 强调密度软告警
平台 SHALL 对行内强调密度执行软 lint(默认每百字超过 3 处标记或存在整句加粗):不阻塞入库,生成确认题请人裁决强调是否得当。

#### Scenario: 染色过密转题
- **WHEN** 某章 para 平均每百字含 5 处 `**` 标记
- **THEN** 草案照常入库,自动生成确认题「第 N 章强调密度过高,请确认强调选词是否得当」
