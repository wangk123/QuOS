# doc-pipeline 能力 delta

## ADDED Requirements

### Requirement: 基线读取
平台 SHALL 提供 GET /api/v1/projects/{pid}/doc/baseline 返回当前定稿快照、规则当前态与变更记录;项目无定稿时返回空基线标志,作为 agent 增量加工起点。
#### Scenario: 首次加工取基线
- **WHEN** 项目尚无任何定稿版本,agent 请求基线
- **THEN** 返回空基线标志(empty=true),agent 据此执行冷启动加工

### Requirement: 文档形态契约
章节正文 SHALL 由有序自由块(blocks)组成,块类型为 para(叙述)/states(状态链)/table(表格)/figure(链路图,每行一条)/exceptions(异常路径);章节可经 parent 指向父章节 id 构成层级。正文不再有固定槽位(状态机/异常段等由内容决定是否成块),表格与主链路以块承载、不得拆散塞入规则 text。
#### Scenario: 结构化内容成块
- **WHEN** agent 产出含参数表与主链路的章节
- **THEN** 参数表以 table 块、主链路以 figure 块呈现在正文,规则 text 只保留行为级约束
#### Scenario: 块结构与层级硬校验
- **WHEN** 草案含空块(如 table 无 rows)、未知块类型、或 parent 指向不存在/成环
- **THEN** 平台拒收并返回 BLOCK_*/CHAPTER_PARENT_* 错误明细

### Requirement: 草案提交与硬校验拒收
平台 SHALL 对 POST /api/v1/projects/{pid}/doc/draft 执行硬校验:active 规则的 quote 必须在所指材料 parsed_text 中可定位(归一化子串匹配;parsed_text 为空的图片类材料跳过;quote 少于 6 字降级软警告;失败时返回材料内最相近片段);规则编号**草案内部唯一**,与 Rule 表现存同编号视为修改路径放行,新编号不得与现存冲突,引用编号须闭合,material_id 不存在单列报错;必填结构完整(active 规则 violation 非空、章节有标题、作废规则必须带 replaced_by;正文块结构合法、parent 引用闭合且无环)。任一硬错误时整体拒收并返回错误清单。
#### Scenario: 出处定位不到被拒收
- **WHEN** agent 提交的草案中规则 R12 的 quote 在材料 7 的文本中定位不到
- **THEN** 平台拒收整份草案,返回 hard_errors 指明 R12 出处核对失败并附材料内最相近片段,草案不入库
#### Scenario: 编号冲突被拒收,修改路径放行
- **WHEN** 草案内部两条规则使用相同编号,或新编号与 Rule 表现存冲突,或引用了不存在的编号
- **THEN** 平台拒收并返回编号冲突明细
- **WHEN** 草案复用 Rule 表现存编号 R12 并修改其文本
- **THEN** 视为修改路径,校验放行

### Requirement: 软警告转题
平台 SHALL 对软警告不阻塞入库:草案标记 reviewing,警告自动生成对应题型进入人闸门队列,含:草案申报的 new_terms 每条生成术语确认题、已登记术语正文写法不一致生成确认题、violation 与规则正文完全雷同生成确认题、**空壳章节(无正文块且零规则)生成填空题**——有叙述或规则任一的章节不出题,不强迫按模板填满;自动题按题型与关键内容去重。
#### Scenario: 申报新术语自动出题
- **WHEN** 草案 new_terms 含「幂等键」(agent 自查申报)
- **THEN** 草案照常入库为 reviewing,并自动生成一条确认题:「术语『幂等键』是否收录入术语表?请给定义」
#### Scenario: 可判定性存疑出题
- **WHEN** 规则的 violation 字段为空或与规则正文完全雷同
- **THEN** 自动生成确认题请人补「怎样算违反」

### Requirement: markdown 导入
平台 SHALL 提供 POST /api/v1/projects/{pid}/doc/draft/import:接收 markdown 全文与可选 rules_meta(规则级精修 violation/quote),内置转换为 DocPayload(章节层级/规则编号三格式/正文块/表格/术语表/图与 mermaid 降级/行内标记清洗),quote 自动匹配项目材料文本(相似度达标挂出处,未达标留空走软警告),转换后走与手工提交完全相同的两级校验与覆盖落库。
#### Scenario: 纯 markdown 导入自动挂出处
- **WHEN** agent 提交 md 文档(未携带 rules_meta),其中规则文本与某材料句相似度达标
- **THEN** 该规则自动挂该材料出处;未匹配规则 quote 留空,软警告不阻塞,由人工评审补
#### Scenario: 携带精修值导入
- **WHEN** 导入请求携带 rules_meta 中 FR-101 的 violation 与 quote
- **THEN** 精修值优先于自动匹配,校验与落库结果与手工构造 payload 提交一致

### Requirement: 校验报告返回
平台 SHALL 在草案提交响应中返回完整校验报告(hard_errors / soft_warnings / 自动生成的题目清单),供 agent 决定修正重交或留给人裁。
#### Scenario: 硬错误修正重交
- **WHEN** agent 收到 hard_errors 后修正 quote 并重新提交
- **THEN** 校验通过,草案进入 reviewing,前次被拒草案不留库
