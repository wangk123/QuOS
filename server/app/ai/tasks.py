# server/app/ai/tasks.py
from pydantic import BaseModel

from app.ai.runner import complete
from app.core.models import Assertion


class ExtractOut(BaseModel):
    assertions: list[Assertion]


class VerifyOut(BaseModel):
    results: list[dict]


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
