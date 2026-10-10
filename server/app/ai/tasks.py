# server/app/ai/tasks.py
from pydantic import BaseModel

from app.ai.runner import complete
from app.core.models import Conflict, Gap, Rule
from app.storage.profiles import Profile


class AssembleBlocked(Exception):
    def __init__(self, unqualified: list[Rule]):
        self.unqualified = unqualified
        super().__init__(f"{len(unqualified)} 条规则未核验或待实证")


class ExtractOut(BaseModel):
    rules: list[Rule]


class VerifyOut(BaseModel):
    results: list[dict]


class ConflictDraft(BaseModel):
    q: str
    parties: list[str]  # 同主题 2~N 条规则 id（多方归组）


class ConflictOut(BaseModel):
    conflicts: list[ConflictDraft]


class GapOut(BaseModel):
    gaps: list[Gap]


class AssembleOut(BaseModel):
    profile: Profile
    findings: list["Finding"] = []


class Finding(BaseModel):
    """组装补充发现：AI 只许经此通道补充——自证分流后要么成规则要么成缺口，无第三分类"""
    kind: str  # 'rule'=材料有依据(须带 quote 自证) | 'gap'=材料没说清
    text: str
    quote: str = ""
    dim: str = "组装补充"


class ImpactOut(BaseModel):
    nodes: list[str] = []
    rule_ids: list[str] = []
    clar_nos: list[str] = []
    mode: str = "partial"
    reason: str = ""


class OutlineNode(BaseModel):
    name: str
    goal: str = ""
    children: list["OutlineNode"] = []


class OutlineOut(BaseModel):
    nodes: list[OutlineNode]


class UnderstandRoot(BaseModel):
    goal: str = ""
    entry: str = ""
    flow: str = ""
    boundaries: str = ""
    note: str = ""


class UnderstandOut(BaseModel):
    root: UnderstandRoot
    nodes: list[OutlineNode]


class ResolveItem(BaseModel):
    kind: str  # conflict | gap
    id: str
    action: str  # conflict: auto|keep；gap: close|keep
    winner: str = ""  # conflict auto 时的胜方规则 id
    quote: str = ""  # 材料原文依据（自动处理必附，落库时定位校验）


class ResolveDoubtsOut(BaseModel):
    items: list[ResolveItem]


class SummaryOut(BaseModel):
    goal: str = ""
    entry: str = ""
    boundaries: str = ""
    note: str = ""


def _fmt_rules(rules: list[Rule]) -> str:
    return "\n".join(f"- {r.id} | {r.text} | 出处: {r.src} | conf: {r.conf}" for r in rules)


async def extract(evidence_content: str, evidence_type: str, tree_text: str,
                  images: list[bytes] | None = None) -> list[Rule]:
    out = await complete(
        "extract",
        {"material": evidence_content, "evidence_type": evidence_type, "tree_list": tree_text},
        ExtractOut,
        images=images,
    )
    return out.rules


async def verify(rules: list[Rule], evidence_content: str) -> VerifyOut:
    return await complete(
        "verify",
        {"rules": _fmt_rules(rules), "material": evidence_content},
        VerifyOut,
    )


async def conflict(rules: list[Rule]) -> list[Conflict]:
    out = await complete(
        "conflict",
        {"rules": _fmt_rules(rules)},
        ConflictOut,
    )
    return [Conflict(id="", q=d.q, parties=d.parties) for d in out.conflicts]


async def gaps(profile_summary: str, dims: list[str]) -> list[Gap]:
    out = await complete(
        "gap",
        {"profile_summary": profile_summary, "dims": "、".join(dims)},
        GapOut,
    )
    return out.gaps


async def assemble(rules: list[Rule], node_name: str, note: str,
                   parent_goal: str = "") -> AssembleOut:
    unqualified = [r for r in rules if not (r.verified and r.conf != "待实证")]
    if unqualified:
        raise AssembleBlocked(unqualified)
    out = await complete(
        "assemble",
        {"rules": _fmt_rules(rules), "node": node_name, "note": note,
         "parent_goal": parent_goal},
        AssembleOut,
    )
    return out


async def impact_analysis(new_text: str, rules_text: str, clars_text: str) -> ImpactOut:
    """材料级影响分析：新材料 × 现有条目/待确认 → 受影响范围 + 重生成方案建议"""
    return await complete(
        "impact",
        {"new_text": new_text, "rules_text": rules_text, "clars_text": clars_text},
        ImpactOut,
    )


async def outline(material: str) -> list[OutlineNode]:
    out = await complete("outline", {"material": material}, OutlineOut)
    return out.nodes


async def understand(material: str, images: list[bytes] | None = None) -> UnderstandOut:
    return await complete("understand", {"material": material}, UnderstandOut, images=images)


async def resolve_doubts(doubts_text: str, materials_text: str) -> ResolveDoubtsOut:
    """遗留疑点直处（智能生成 ③ 阶段）：疑点清单 × 材料 → 逐项 auto/close（附 quote）/keep"""
    return await complete("resolve-doubts",
                          {"doubts": doubts_text, "materials": materials_text},
                          ResolveDoubtsOut)


async def summary(parts: str, kind: str) -> SummaryOut:
    """模块/根概要聚合：子节点画像清单 → 只覆写 goal/entry/boundaries/note 四字段"""
    return await complete("summary", {"parts": parts, "kind": kind}, SummaryOut)
