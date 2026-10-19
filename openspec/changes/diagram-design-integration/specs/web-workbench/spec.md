# web-workbench Delta

## MODIFIED Requirements

### Requirement: 文档评审页布局
文档评审页 SHALL 为固定视口结构(各栏独立滚动,页面不整体滚动):文档区 = 文档正文(章节层级编号渲染,正文块按 para/states/table/figure/exceptions/diagram 分派——diagram 块以 sandbox iframe srcdoc 渲染自包含 HTML 图(禁脚本执行,高度自适应),figure 块以流程条呈现线性链路,存量 mermaid 块降级显示源码并附重画提示;规则编号锚点,恒全宽) + 内嵌目录列(章节树:层级编号+每章批注计数;三态 pinned 常驻挤占正文 / hover 悬浮浮层 / hidden 只留把手;右缘拖拽调宽限界并记忆);术语表以文档末章词条表呈现(术语/释义/出现章节,chip 点击定位);右 = 批注栏。工具条含:草案状态徽标、基于基线版本与摘要文字、**定稿发版按钮**。
#### Scenario: 独立滚动
- **WHEN** 用户滚动文档正文
- **THEN** 仅文档区滚动,批注栏位置不动
#### Scenario: 目录宽度拖拽
- **WHEN** 用户拖动目录右缘把手调整宽度
- **THEN** 目录宽度在限界内变化并记忆,刷新后保持;正文流式区域相应伸缩
#### Scenario: diagram 块 sandbox 渲染
- **WHEN** 文档正文渲染 diagram 块(自包含 HTML 图源)
- **THEN** 图以 sandbox iframe(无 allow-scripts)内联呈现,高度按内容自适应,暖纸面底色随图自带,不注入平台主题
#### Scenario: 存量 mermaid 图降级提示
- **WHEN** 文档正文渲染 text 非 HTML 形态的 diagram 块(存量 mermaid 源码)
- **THEN** 降级显示源码并提示「存量 mermaid 图,待迭代重画为 diagram-design」,不报错不空白
