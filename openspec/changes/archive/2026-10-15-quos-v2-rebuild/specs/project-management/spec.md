# project-management 能力 delta

## ADDED Requirements

### Requirement: 项目生命周期管理
平台 SHALL 支持项目的创建、改名、描述编辑与归档;项目是材料、文档、题目、版本的容器。
#### Scenario: 创建项目
- **WHEN** 用户在项目页新建项目并填写名称与描述
- **THEN** 项目入库并在列表展示,后续材料/文档/题目均归属该项目
#### Scenario: 归档项目
- **WHEN** 用户对项目执行归档
- **THEN** 项目从默认列表隐藏(可在归档视图查看并恢复),其数据保持完整

### Requirement: 项目内状态可见
平台 SHALL 对每个项目展示:材料数、待答题目数、当前文档版本号与是否存在 reviewing 草案。
#### Scenario: 工作台总览
- **WHEN** 用户打开项目页
- **THEN** 每个项目行显示材料数、待答题目数、当前版本号与草案状态徽章
