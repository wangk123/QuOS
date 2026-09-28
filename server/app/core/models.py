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


class Assertion(BaseModel):
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


class Clarification(BaseModel):
    no: int
    q: str
    opts: list[str]
    st: str = "open"
    answer: Optional[str] = None
    ref: Optional[str] = None
