# doc-pipeline 能力 delta

## ADDED Requirements

### Requirement: 基线读取
平台 SHALL 提供 GET /api/v1/projects/{pid}/doc/baseline 返回当前定稿快照、规则当前态与变更记录;项目无定稿时返回空基线标志,作为 agent 增量加工起点。
#### Scenario: 首次加工取基线
- **WHEN** 项目尚无任何定稿版本,agent 请求基线
- **THEN** 返回空基线标志(empty=true),agent 据此执行冷启动加工

### Requirement: 草案提交与硬校验拒收
平台 SHALL 对 POST /api/v1/projects/{pid}/doc/draft 执行硬校验:active 规则的 quote 必须在所指材料 parsed_text 中可定位(归一化子串匹配;parsed_text 为空的图片类材料跳过;quote 少于 6 字降级软警告;失败时返回材料内最相近片段);规则编号**草案内部唯一**,与 Rule 表现存同编号视为修改路径放行,新编号不得与现存冲突,引用编号须闭合,material_id 不存在单列报错;必填结构完整(active 规则 violation 非空、章节有标题、作废规则必须带 replaced_by)。任一硬错误时整体拒收并返回错误清单。
#### Scenario: 出处定位不到被拒收
- **WHEN** agent 提交的草案中规则 R12 的 quote 在材料 7 的文本中定位不到
- **THEN** 平台拒收整份草案,返回 hard_errors 指明 R12 出处核对失败并附材料内最相近片段,草案不入库
#### Scenario: 编号冲突被拒收,修改路径放行
- **WHEN** 草案内部两条规则使用相同编号,或新编号与 Rule 表现存冲突,或引用了不存在的编号
- **THEN** 平台拒收并返回编号冲突明细
- **WHEN** 草案复用 Rule 表现存编号 R12 并修改其文本
- **THEN** 视为修改路径,校验放行

### Requirement: 软警告转题
平台 SHALL 对软警告不阻塞入库:草案标记 reviewing,警告自动生成对应题型进入人闸门队列,含:草案申报的 new_terms 每条生成术语确认题、已登记术语正文写法不一致生成确认题、violation 与规则正文完全雷同生成确认题、章节零规则或状态机段为空生成填空题;自动题按题型与关键内容去重。
#### Scenario: 申报新术语自动出题
- **WHEN** 草案 new_terms 含「幂等键」(agent 自查申报)
- **THEN** 草案照常入库为 reviewing,并自动生成一条确认题:「术语『幂等键』是否收录入术语表?请给定义」
#### Scenario: 可判定性存疑出题
- **WHEN** 规则的 violation 字段为空或与规则正文完全雷同
- **THEN** 自动生成确认题请人补「怎样算违反」

### Requirement: 校验报告返回
平台 SHALL 在草案提交响应中返回完整校验报告(hard_errors / soft_warnings / 自动生成的题目清单),供 agent 决定修正重交或留给人裁。
#### Scenario: 硬错误修正重交
- **WHEN** agent 收到 hard_errors 后修正 quote 并重新提交
- **THEN** 校验通过,草案进入 reviewing,前次被拒草案不留库
