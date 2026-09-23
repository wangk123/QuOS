# server/app/ai/tasks.py
from pydantic import BaseModel

from app.ai.runner import complete
from app.core.models import Assertion, Conflict, Gap
from app.storage.cards import Card


class AssembleBlocked(Exception):
    def __init__(self, unqualified: list[Assertion]):
        self.unqualified = unqualified
        super().__init__(f"{len(unqualified)} 条断言未核验或待实证")


class ExtractOut(BaseModel):
    assertions: list[Assertion]


class VerifyOut(BaseModel):
    results: list[dict]


class ConflictOut(BaseModel):
    conflicts: list[Conflict]


class GapOut(BaseModel):
    gaps: list[Gap]


class AssembleOut(BaseModel):
    card: Card


class ImpactOut(BaseModel):
    nodes: list[str]


def _fmt_assertions(assertions: list[Assertion]) -> str:
    return "\n".join(f"- {a.id} | {a.text} | 出处: {a.src} | conf: {a.conf}" for a in assertions)


async def extract(evidence_content: str, evidence_type: str) -> list[Assertion]:
    out = await complete(
        "extract",
        {"material": evidence_content, "evidence_type": evidence_type},
        ExtractOut,
    )
    return out.assertions


async def verify(assertions: list[Assertion], evidence_content: str) -> VerifyOut:
    return await complete(
        "verify",
        {"assertions": _fmt_assertions(assertions), "material": evidence_content},
        VerifyOut,
    )


async def conflict(assertions: list[Assertion]) -> list[Conflict]:
    out = await complete(
        "conflict",
        {"assertions": _fmt_assertions(assertions)},
        ConflictOut,
    )
    return out.conflicts


async def gaps(card_summary: str, dims: list[str]) -> list[Gap]:
    out = await complete(
        "gap",
        {"card_summary": card_summary, "dims": "、".join(dims)},
        GapOut,
    )
    return out.gaps


async def assemble(assertions: list[Assertion], node_name: str, note: str) -> Card:
    unqualified = [a for a in assertions if not (a.verified and a.conf != "待实证")]
    if unqualified:
        raise AssembleBlocked(unqualified)
    out = await complete(
        "assemble",
        {"assertions": _fmt_assertions(assertions), "node": node_name, "note": note},
        AssembleOut,
    )
    return out.card


async def impact(diff_text: str, tree_dump: str, card_list: list[str]) -> list[str]:
    out = await complete(
        "impact",
        {
            "diff": diff_text,
            "tree": tree_dump,
            "cards": "\n".join(f"- {c}" for c in card_list),
        },
        ImpactOut,
    )
    return out.nodes
