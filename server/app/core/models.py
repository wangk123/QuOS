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
