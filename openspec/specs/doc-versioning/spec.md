# doc-versioning Specification

## Purpose
TBD - created by archiving change quos-v2-rebuild. Update Purpose after archive.

## Requirements

### Requirement: 人拍板定稿发版(自定义版本号)
平台 SHALL 仅允许人在评审页执行定稿发版(POST /api/v1/projects/{pid}/doc/finalize):版本号由人**自定义输入**(非自增,平台给建议值;与历史版本重复则拦截),发版说明选填(写入版本历史);确认后生成 DocVersion 快照。agent 无发版权限,只能反馈建议。
#### Scenario: 自定义版本号发版
- **WHEN** 用户将建议的 v3 改为 v2.1 并填写发版说明后确认
- **THEN** 生成 v2.1 版本快照,时间线顶部出现 v2.1(带发版说明)
#### Scenario: 重复版本号拦截
- **WHEN** 用户输入与历史版本重复的版本号并确认
- **THEN** 平台拦截并提示版本号重复,不发版

### Requirement: 版本回退(版本页)
版本管理 SHALL 提供回退:对任一已定稿版本执行「回退到此版」= 设为当前基线,后续草案基于该版加工;之后的版本保留在历史中不删除。评审页**不提供打回**——草案不满意的处置方式为不发版,由 agent 继续收敛或新草案覆盖。
#### Scenario: 回退基线
- **WHEN** 用户在版本页对 v2 确认回退
- **THEN** 当前基线变为 v2,v3 之后版本保留在历史中

### Requirement: 条款级变更记录
平台 SHALL 在定稿时与上一版逐规则比对自动生成 ChangeLog:新增/修改/作废(作废以草案的 voided 显式声明为准,不靠规则消失推断),含编号、旧文、新文、原因(reason 优先取对应题目的人答,缺省取草案附带说明)、批准人;定稿同时由快照 glossary 全量重建 Term 表(表=当前态,快照=历史)。
#### Scenario: 首版变更记录
- **WHEN** 项目产生第一个定稿版本
- **THEN** 全部规则记为新增,reason 记录材料来源摘要
#### Scenario: 修改条款留痕
- **WHEN** v2 中规则 R13 文本相对 v1 有修改
- **THEN** ChangeLog 记录 old_text/new_text/reason/approver,两版快照均可独立完整查看

### Requirement: 规则编号稳定与作废留痕
平台 SHALL 保证规则编号项目内唯一且跨版本稳定:内容小改编号不变;规则作废时置 voided 并以 replaced_by 指向替代编号,不物理删除。
#### Scenario: 作废替代
- **WHEN** 草案显式声明 R9 作废并由 R15 替代,定稿通过
- **THEN** R9 置 voided、replaced_by=R15,ChangeLog 记录该作废关系

### Requirement: 版本查看与切换
平台 SHALL 支持在文档页切换任意历史版本查看完整快照,并按版本查看变更记录。
#### Scenario: 切换历史版本
- **WHEN** 用户在文档页从 v3 切换到 v2
- **THEN** 页面完整渲染 v2 快照(章节+规则全文自包含,不依赖其他版本)
