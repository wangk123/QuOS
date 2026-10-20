# project-management Specification

## Purpose
TBD - created by archiving change quos-v2-rebuild. Update Purpose after archive.

## Requirements

### Requirement: 项目生命周期管理
平台 SHALL 支持项目的创建、改名、描述编辑与删除;项目是材料、文档、题目、版本的容器。删除为物理删除且不可逆,连带清除该项目全部从属数据(材料、草案、版本、基线、变更记录、批注、规则、术语)与磁盘上的项目目录。不提供归档:项目列表始终展示全部项目。
#### Scenario: 创建项目
- **WHEN** 用户在项目页新建项目并填写名称与描述
- **THEN** 项目入库并在列表展示,后续材料/文档/题目均归属该项目
#### Scenario: 删除项目
- **WHEN** 用户在项目页对项目执行删除并在弹窗二次确认
- **THEN** 项目及其全部从属数据与项目目录被清除,列表不再显示,再次访问该项目返回 404

### Requirement: 项目内状态可见
平台 SHALL 对每个项目展示:材料数、待答题目数、当前文档版本号与是否存在 reviewing 草案。
#### Scenario: 工作台总览
- **WHEN** 用户打开项目页
- **THEN** 每个项目行显示材料数、待答题目数、当前版本号与草案状态徽章
