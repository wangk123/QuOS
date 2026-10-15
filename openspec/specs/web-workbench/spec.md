# web-workbench Specification

## Purpose
TBD - created by archiving change quos-v2-rebuild. Update Purpose after archive.

## Requirements

### Requirement: 平台骨架与项目内导航
前端 SHALL 采用深色侧栏 + 浅色内容区的平台骨架:侧栏为项目树,进入项目后展开项目内子页导航(材料 / 文档评审 / 版本);材料、评审、文档是项目内部资源,不作为全局一级页面;面包屑为 QuOS / 项目名 / 子页。
#### Scenario: 进入项目
- **WHEN** 用户在项目总览点击某项目
- **THEN** 进入该项目的文档评审页,侧栏该项目下展开三个子页入口,文档评审入口带待处理批注数徽标

### Requirement: 文档评审页布局
文档评审页 SHALL 为固定视口结构(各栏独立滚动,页面不整体滚动):文档区 = 文档正文(章节层级编号渲染,正文块按 para/states/table/figure/exceptions/diagram 分派,规则编号锚点,恒全宽) + 内嵌目录列(章节树:层级编号+每章批注计数;三态 pinned 常驻挤占正文 / hover 悬浮浮层 / hidden 只留把手;右缘拖拽调宽限界并记忆);术语表以文档末章词条表呈现(术语/释义/出现章节,chip 点击定位);右 = 批注栏。工具条含:草案状态徽标、基于基线版本与摘要文字、**定稿发版按钮**。
#### Scenario: 独立滚动
- **WHEN** 用户滚动文档正文
- **THEN** 仅文档区滚动,批注栏位置不动
#### Scenario: 目录宽度拖拽
- **WHEN** 用户拖动目录右缘把手调整宽度
- **THEN** 目录宽度在限界内变化并记忆,刷新后保持;正文流式区域相应伸缩

### Requirement: 正文批注与规则锚点
文档正文 SHALL 支持批注高亮标记(未答琥珀、已答绿)与规则编号锚点:点正文标记激活右栏对应批注卡;点规则编号弹出 popover(怎样算违反/出处引用/材料 hash)。
#### Scenario: 点规则编号
- **WHEN** 用户点击规则编号 R13
- **THEN** 弹出 popover 展示可判定表述与出处引用,点击外部关闭

### Requirement: 版本页
版本页 SHALL 呈现版本时间线(草案评审中项 + 历史定稿项)+ 选中版本的条款级变更 diff;每个已定稿版本提供「回退到此版」操作;发版后新版本带发版说明出现在时间线顶部。
#### Scenario: 回退基线
- **WHEN** 用户在 v2 上点击「回退到此版」并确认
- **THEN** 当前基线置为 v2,v2 之后版本保留在历史中,后续草案基于 v2 加工
