# server/app/core/models.py
from typing import Literal, Optional  # noqa: F401（Optional 仍被 Conflict 使用）

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


class Conflict(BaseModel):
    id: str
    parties: list[str] = []  # 参与规则 id（2~N 同主题说法）；存量 a/b 由 findings 读侧迁移
    q: str
    st: str = "open"  # open | done（裁决即终态）
    resolution: Optional[str] = None  # 胜方规则 id | "manual"
    manual_text: str = ""  # 选「其他」手输的实际行为（同时生成人工确认规则）


class Gap(BaseModel):
    id: str
    dim: str
    text: str
    st: str = "open"
    node: str = ""  # 归属功能点全路径；__root__ = 根级；空 = 全局/旧数据（未绑定）





