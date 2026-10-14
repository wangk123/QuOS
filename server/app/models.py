"""v2 数据模型:8 表 + 快照 payload 契约。

字段口径见 openspec/changes/quos-v2-rebuild/design.md §4.2 与 §6 实施决定:
- Question 即批注,anchor 平铺 {chapter_id, rule_no?, seg?, chapter?};
- 「术语确认」归 confirm 题型,payload.klabel 区分展示;
- 全表带 created_at;DocDraft 校验通过即 reviewing(无 submitted 态)。
"""
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Column, Index, UniqueConstraint, text
from sqlmodel import Field as SF
from sqlmodel import SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
    id: int | None = SF(default=None, primary_key=True)
    name: str = SF(index=True)
    description: str = ""
    archived: bool = False
    created_at: datetime = SF(default_factory=_now)


class Material(SQLModel, table=True):
    id: int | None = SF(default=None, primary_key=True)
    project_id: int = SF(foreign_key="project.id", index=True)
    filename: str
    path: str
    sha256: str = SF(index=True)
    mime_type: str = ""
    size: int = 0
    parsed_text: str = ""
    created_at: datetime = SF(default_factory=_now)


class DocDraft(SQLModel, table=True):
    __table_args__ = (
        # 单 reviewing 不变量由数据库兜底(浏览器与 agent 双入口竞态)
        Index("uq_docdraft_reviewing", "project_id", unique=True,
              sqlite_where=text("status = 'reviewing'")),
    )
    id: int | None = SF(default=None, primary_key=True)
    project_id: int = SF(foreign_key="project.id", index=True)
    payload: dict = SF(sa_column=Column(JSON))
    status: str = "reviewing"  # reviewing | finalized | superseded
    check_report: dict = SF(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = SF(default_factory=_now)


class DocVersion(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_version_per_project"),)
    id: int | None = SF(default=None, primary_key=True)
    project_id: int = SF(foreign_key="project.id", index=True)
    version: str = SF(index=True)
    snapshot: dict = SF(sa_column=Column(JSON))
    draft_id: int | None = SF(default=None, foreign_key="docdraft.id")
    note: str = ""
    created_at: datetime = SF(default_factory=_now)


class Baseline(SQLModel, table=True):
    """当前基线指针(revert 只改这里,历史版本不删)。"""

    project_id: int = SF(primary_key=True, foreign_key="project.id")
    version: str = ""


class ChangeLog(SQLModel, table=True):
    id: int | None = SF(default=None, primary_key=True)
    project_id: int = SF(foreign_key="project.id", index=True)
    version: str = SF(index=True)
    rule_no: str
    kind: str  # added | modified | voided
    old_text: str = ""
    new_text: str = ""
    reason: str = ""
    approver: str = "owner"
    created_at: datetime = SF(default_factory=_now)


class Question(SQLModel, table=True):
    """批注:四题型 choice/confirm/fill/scan;anchor 锚定正文。"""

    id: int | None = SF(default=None, primary_key=True)
    project_id: int = SF(foreign_key="project.id", index=True)
    batch_id: str = ""
    kind: str
    payload: dict = SF(sa_column=Column(JSON))
    anchor: dict = SF(sa_column=Column(JSON))
    status: str = "pending"  # pending | answered | withdrawn
    answer: dict | None = SF(default=None, sa_column=Column(JSON))
    answered_at: datetime | None = SF(default=None)
    source: str = "agent"  # agent | auto
    draft_id: int | None = SF(default=None)
    created_at: datetime = SF(default_factory=_now)


class Rule(SQLModel, table=True):
    id: int | None = SF(default=None, primary_key=True)
    project_id: int = SF(foreign_key="project.id", index=True)
    no: str = SF(index=True)
    text: str
    violation: str = ""
    quote: str = ""
    material_id: int | None = SF(default=None)
    status: str = "active"  # active | voided
    replaced_by: str | None = SF(default=None)
    created_at: datetime = SF(default_factory=_now)


class Term(SQLModel, table=True):
    id: int | None = SF(default=None, primary_key=True)
    project_id: int = SF(foreign_key="project.id", index=True)
    name: str = SF(index=True)
    definition: str = ""
    created_at: datetime = SF(default_factory=_now)


# ── 快照 payload 契约(draft 提交与版本快照的统一结构) ──


class RuleInPayload(BaseModel):
    no: str
    text: str = ""
    violation: str = ""
    quote: str = ""
    material_id: int | None = None
    status: str = "active"
    replaced_by: str | None = None


class BlockInChapter(BaseModel):
    """正文块:章节正文由块有序自由组合,不再固定槽位。

    type: para(叙述段落) | states(状态链/流程, → 连接) | table | figure | exceptions(异常路径条目)。
    章节缺什么块由内容决定;表格/图解决参数表与契约清单不得拆散塞规则 text 的问题。
    """
    type: str
    text: str = ""            # para/states 正文
    title: str = ""           # table/figure 标题(表号/图号渲染时自动编)
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    flows: list[str] = Field(default_factory=list)    # figure: 每行一条链路
    items: list[str] = Field(default_factory=list)    # exceptions


class ChapterInPayload(BaseModel):
    id: str
    title: str
    pri: str = "P1"
    parent: str | None = None   # 父章节 id,构成层级;顶层为 None
    background: str = ""        # 本功能为什么存在(动机一两句,非出处引用)
    blocks: list[BlockInChapter] = Field(default_factory=list)
    rule_nos: list[str] = Field(default_factory=list)


class TermInGlossary(BaseModel):
    name: str
    definition: str = ""


class NewTermDecl(BaseModel):
    name: str
    definition: str = ""
    context: str = ""


class MetaInPayload(BaseModel):
    version: str = "draft"
    date: str = ""
    scope: str = ""


class OverviewInPayload(BaseModel):
    intent: str = ""
    boundary: str = ""


class DocPayload(BaseModel):
    meta: MetaInPayload = Field(default_factory=MetaInPayload)
    overview: OverviewInPayload = Field(default_factory=OverviewInPayload)
    glossary: list[TermInGlossary] = Field(default_factory=list)
    new_terms: list[NewTermDecl] = Field(default_factory=list)
    chapters: list[ChapterInPayload] = Field(default_factory=list)
    rules: dict[str, RuleInPayload] = Field(default_factory=dict)
