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


class ConflictOut(BaseModel):
    conflicts: list[Conflict]


class GapOut(BaseModel):
    gaps: list[Gap]


class AssembleOut(BaseModel):
    profile: Profile


class ImpactOut(BaseModel):
    nodes: list[str]


class OutlineNode(BaseModel):
    name: str
    children: list["OutlineNode"] = []


class OutlineOut(BaseModel):
    nodes: list[OutlineNode]


def _fmt_rules(rules: list[Rule]) -> str:
    return "\n".join(f"- {r.id} | {r.text} | 出处: {r.src} | conf: {r.conf}" for r in rules)


async def extract(evidence_content: str, evidence_type: str, tree_text: str) -> list[Rule]:
    out = await complete(
        "extract",
        {"material": evidence_content, "evidence_type": evidence_type, "tree_list": tree_text},
        ExtractOut,
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
    return out.conflicts


async def gaps(profile_summary: str, dims: list[str]) -> list[Gap]:
    out = await complete(
        "gap",
        {"profile_summary": profile_summary, "dims": "、".join(dims)},
        GapOut,
    )
    return out.gaps


async def assemble(rules: list[Rule], node_name: str, note: str) -> Profile:
    unqualified = [r for r in rules if not (r.verified and r.conf != "待实证")]
    if unqualified:
        raise AssembleBlocked(unqualified)
    out = await complete(
        "assemble",
        {"rules": _fmt_rules(rules), "node": node_name, "note": note},
        AssembleOut,
    )
    return out.profile


async def impact(diff_text: str, tree_dump: str, profile_list: list[str]) -> list[str]:
    out = await complete(
        "impact",
        {
            "diff": diff_text,
            "tree": tree_dump,
            "profiles": "\n".join(f"- {p}" for p in profile_list),
        },
        ImpactOut,
    )
    return out.nodes


async def outline(material: str) -> list[OutlineNode]:
    out = await complete("outline", {"material": material}, OutlineOut)
    return out.nodes
