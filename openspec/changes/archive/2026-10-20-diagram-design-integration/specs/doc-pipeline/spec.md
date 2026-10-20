# doc-pipeline Delta

## MODIFIED Requirements

### Requirement: 文档形态契约
章节正文 SHALL 由有序自由块(blocks)组成,块类型为 para(叙述)/states(状态链)/table(表格)/figure(线性链路,每行一条,平台以流程条呈现)/exceptions(异常路径)/diagram(自包含 HTML 图源,diagram-design 产物,前端 sandbox 渲染);章节可经 parent 指向父章节 id 构成层级。正文不再有固定槽位(状态机/异常段等由内容决定是否成块),表格与主链路以块承载、不得拆散塞入规则 text。
#### Scenario: 结构化内容成块
- **WHEN** agent 产出含参数表与主链路的章节
- **THEN** 参数表以 table 块、主链路以 figure 块呈现在正文,规则 text 只保留行为级约束
#### Scenario: diagram-design 图成 diagram 块
- **WHEN** agent 产出的 md 正文含图引用(如 `![需求文档主链路](figures/main-flow.html)`)且随附该图文件
- **THEN** 图 HTML 全文原样进入 diagram 块,前端 sandbox iframe 渲染真图
#### Scenario: 块结构与层级硬校验
- **WHEN** 草案含空块(如 table 无 rows)、未知块类型、或 parent 指向不存在/成环
- **THEN** 平台拒收并返回 BLOCK_*/CHAPTER_PARENT_* 错误明细

### Requirement: 草案提交与硬校验拒收
平台 SHALL 对 POST /api/v1/projects/{pid}/doc/draft 执行硬校验:active 规则的 quote 必须在所指材料 parsed_text 中可定位(归一化子串匹配;parsed_text 为空的图片类材料跳过;quote 少于 6 字降级软警告;失败时返回材料内最相近片段);规则编号**草案内部唯一**,与 Rule 表现存同编号视为修改路径放行,新编号不得与现存冲突,引用编号须闭合,material_id 不存在单列报错;必填结构完整(active 规则 violation 非空、章节有标题、作废规则必须带 replaced_by;正文块结构合法、parent 引用闭合且无环、diagram 块为 HTML 形态时须过结构校验)。任一硬错误时整体拒收并返回错误清单。
#### Scenario: 出处定位不到被拒收
- **WHEN** agent 提交的草案中规则 R12 的 quote 在材料 7 的文本中定位不到
- **THEN** 平台拒收整份草案,返回 hard_errors 指明 R12 出处核对失败并附材料内最相近片段,草案不入库
#### Scenario: 编号冲突被拒收,修改路径放行
- **WHEN** 草案内部两条规则使用相同编号,或新编号与 Rule 表现存冲突,或引用了不存在的编号
- **THEN** 平台拒收并返回编号冲突明细
- **WHEN** 草案复用 Rule 表现存编号 R12 并修改其文本
- **THEN** 视为修改路径,校验放行
#### Scenario: 图源结构非法被拒收
- **WHEN** 草案 diagram 块的 text 为 HTML 形态,但缺 title/desc、含 script 标签或事件属性、含外链资源,或内容越界 viewBox
- **THEN** 平台拒收并返回 DIAGRAM_* 错误明细(带块位置与失败项),agent 修复重交
#### Scenario: 非 HTML 形态图源放行走软警告
- **WHEN** 草案 diagram 块的 text 非 HTML 形态(存量 mermaid 源码,如旧基线增量重提时携带)
- **THEN** 草案照常入库,校验报告 soft_warnings 提示「图源已单轨为 diagram-design,请重画」,agent 修复轮感知后重画

### Requirement: markdown 导入
平台 SHALL 提供 POST /api/v1/projects/{pid}/doc/draft/import,请求为 multipart:markdown 全文 + 可选 figures 图文件集(自包含 HTML)与可选 rules_meta(规则级精修 violation/quote)。内置转换为 DocPayload(章节层级/规则编号三格式/正文块/表格/术语表/图引用 `![意图](figures/<slug>.html)` 解析为 diagram 块并收图文件全文入块——payload 快照冻结图版本,不建图资产表/mermaid 围栏照旧入 diagram 块并由校验侧出软警告提示重画/行内标记清洗),quote 自动匹配项目材料文本(相似度达标挂出处,未达标留空走软警告),转换后走与手工提交完全相同的两级校验与覆盖落库。引用闭合为硬校验:md 引用的图文件未随请求提交即拒收;提交了未被引用的图文件出软警告;图引用必须独立成行,出现在列表项/表格单元格/行内混排/引用块等位置一律 422 拒收(防图静默丢失)。
#### Scenario: 纯 markdown 导入自动挂出处
- **WHEN** agent 提交 md 文档(未携带 rules_meta),其中规则文本与某材料句相似度达标
- **THEN** 该规则自动挂该材料出处;未匹配规则 quote 留空,软警告不阻塞,由人工评审补
#### Scenario: 携带精修值导入
- **WHEN** 导入请求携带 rules_meta 中 FR-101 的 violation 与 quote
- **THEN** 精修值优先于自动匹配,校验与落库结果与手工构造 payload 提交一致
#### Scenario: 图引用文件缺失被拒收
- **WHEN** md 引用 figures/main-flow.html 但请求文件集中无此文件
- **THEN** 平台 422 拒收(FORMAT_CONTRACT 族,detail 带引用位置),agent 补文件重导
#### Scenario: 图引用位置非法被拒收
- **WHEN** md 的列表项、表格单元格或行内混排中出现指向 .html 的图片引用
- **THEN** 平台 422 拒收(FORMAT_CONTRACT 族,detail 带位置与修法「图引用须独立成行」),agent 调整为独立行重导
#### Scenario: 格式契约违规导入即拒收
- **WHEN** md 含 ASCII 盒子图、引用块承载实质内容,或所附图 HTML 未过结构校验(缺 title/desc/含 script 或事件属性/含外链资源/内容越界 viewBox)
- **THEN** 平台 422 拒收(FORMAT_CONTRACT/DIAGRAM_*,detail 带位置与修法),agent 修复重导,全程无人工
#### Scenario: 旧 mermaid 围栏降级入块
- **WHEN** md 含 mermaid 代码块(旧契约产物或未升级 agent 产出)
- **THEN** 其内容照旧原样进入 diagram 块(不丢弃不转存),校验报告 soft_warnings 提示「图源已单轨为 diagram-design,请重画」,不阻塞入库,前端按存量降级路径渲染
