# server/app/core/models.py
from typing import Literal, Optional

from pydantic import BaseModel


class Evidence(BaseModel):
    id: str
    name: str
    ext: str = ""
    type: str
    stars: int = 2
    reg: str
    state: str = "pending"
    count: int = 0
    path: str
    missing: bool = False
    source: str = ""  # 'clar' = 澄清池补料入口；空 = 证据池入口


class Rule(BaseModel):
    id: str
    text: str
    src: str
    conf: Literal["实证", "文档", "推测", "待实证", "旧文档"]
    st: str = "open"
    verified: bool = False
    suspect: bool = False
    src_id: str = ""  # 来源证据 id；空 = 历史数据，重提/删证据时不清理
    node: str = ""  # 归属功能点全路径；空 = 未归类（树缺枝探伤器入口）
    nb: str = ""  # AI 核验「材料无依据」的原因；空 = 无此结论
    clar: Optional[int] = None  # 已转「问人」的问题编号


class Conflict(BaseModel):
    id: str
    a: str
    b: str
    q: str
    st: str = "open"
    resolution: Optional[str] = None


class Gap(BaseModel):
    id: str
    dim: str
    text: str
    st: str = "open"
    node: str = ""  # 归属功能点全路径；__root__ = 根级；空 = 全局/旧数据（未绑定）


class AiReview(BaseModel):
    answer: str
    quote: str
    ev_ids: list[str] = []
    conf: str  # high | med | low
    quote_ok: bool = True

    def __eq__(self, other: object) -> bool:  # 支持与存储层原始 dict 等值比较
        if isinstance(other, dict):
            return self.model_dump() == other
        return super().__eq__(other)


class ClarAnswer(BaseModel):
    kind: str  # 'opt' | 'text' | 'material'
    text: str
    ev_ids: list[str] = []
    extra: str = ""  # confirm 选「与实际不符」时补充的实际行为


class Clarification(BaseModel):
    no: int
    q: str
    opts: list[str] = []
    kind: str = "choice"  # choice | open（opts 为空即 open；旧数据默认 choice）
    type: str = ""  # confirm 确认 | choose 取舍 | supply 补全 | custom 自定义；空=旧数据（读取时按 ref 推断）
    st: str = "wait"  # wait | answered | verified
    answer: Optional[str] = None
    ref: Optional[str] = None
    ai: AiReview | None = None
    ans: ClarAnswer | None = None
