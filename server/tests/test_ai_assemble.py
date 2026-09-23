# server/tests/test_ai_assemble.py
import pytest
from app.ai import tasks
from app.core.models import Assertion
from app.ai.tasks import AssembleBlocked
from app.storage.cards import Card, Rule


async def test_blocked_when_unverified():
    a = Assertion(id="A1", text="x", src="s", conf="待实证")
    with pytest.raises(AssembleBlocked) as e:
        await tasks.assemble([a], "放款重试", "")
    assert a.id in [x.id for x in e.value.unqualified]


async def test_blocked_when_not_verified_flag():
    a = Assertion(id="A2", text="x", src="s", conf="实证", verified=False)
    with pytest.raises(AssembleBlocked):
        await tasks.assemble([a], "放款重试", "")


async def test_assemble_success(monkeypatch):
    card = Card(node="放款重试", goal="验证重试正确",
                rules=[Rule(id="R1", text="超时重试3次", src="retry.py:15", conf="实证")])
    fake = tasks.AssembleOut(card=card)
    seen = {}

    async def mock(task, variables, schema):
        seen.update(variables)
        return fake

    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.assemble(
        [Assertion(id="A1", text="超时重试3次", src="retry.py:15", conf="实证", verified=True)],
        "放款重试", "补充：需覆盖幂等",
    )
    assert isinstance(out, Card)
    assert out.node == "放款重试"
    assert out.rules[0].id == "R1" and out.rules[0].conf == "实证"
    assert seen["node"] == "放款重试"
    assert "幂等" in seen["note"]


async def test_impact_success(monkeypatch):
    fake = tasks.ImpactOut(nodes=["放款重试"])

    async def mock(task, variables, schema):
        return fake

    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.impact("diff --git a/retry.py", "放款重试", ["放款重试", "额度校验"])
    assert out == ["放款重试"]
