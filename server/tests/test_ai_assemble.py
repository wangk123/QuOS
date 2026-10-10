# server/tests/test_ai_assemble.py
import pytest
from app.ai import tasks
from app.core.models import Rule
from app.ai.tasks import AssembleBlocked
from app.storage.profiles import Profile, ProfileRule


async def test_blocked_when_unverified():
    a = Rule(id="R1", text="x", src="s", conf="待实证")
    with pytest.raises(AssembleBlocked) as e:
        await tasks.assemble([a], "放款重试", "")
    assert a.id in [x.id for x in e.value.unqualified]


async def test_blocked_when_not_verified_flag():
    a = Rule(id="R2", text="x", src="s", conf="实证", verified=False)
    with pytest.raises(AssembleBlocked):
        await tasks.assemble([a], "放款重试", "")


async def test_assemble_success(monkeypatch):
    card = Profile(node="放款重试", goal="验证重试正确",
                rules=[ProfileRule(id="R1", text="超时重试3次", src="retry.py:15", conf="实证")])
    fake = tasks.AssembleOut(profile=card)
    seen = {}

    async def mock(task, variables, schema):
        seen.update(variables)
        return fake

    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.assemble(
        [Rule(id="R1", text="超时重试3次", src="retry.py:15", conf="实证", verified=True)],
        "放款重试", "补充：需覆盖幂等",
    )
    assert isinstance(out, tasks.AssembleOut)
    assert out.profile.node == "放款重试"
    assert out.profile.rules[0].id == "R1" and out.profile.rules[0].conf == "实证"
    assert out.findings == []  # 无补充发现时为空列表（不再有 unconfirmed 字段）
    assert seen["node"] == "放款重试"
    assert "幂等" in seen["note"]
    assert seen["parent_goal"] == ""  # 默认不传父职责时 prompt 变量仍齐全


async def test_assemble_passes_parent_goal(monkeypatch):
    card = Profile(node="文字输入", goal="输入企业名称")
    seen = {}

    async def mock(task, variables, schema):
        seen.update(variables)
        return tasks.AssembleOut(profile=card)

    monkeypatch.setattr(tasks, "complete", mock)
    await tasks.assemble(
        [Rule(id="R1", text="输入企业名称自动开网页", src="材料实证", conf="实证", verified=True)],
        "文字输入", "", parent_goal="接收并解析用户输入",
    )
    assert seen["parent_goal"] == "接收并解析用户输入"


async def test_impact_analysis_success(monkeypatch):
    fake = tasks.ImpactOut(nodes=["感知/文字输入"], rule_ids=["R1"], clar_nos=["Q1"],
                           mode="partial", reason="新材料仅修正该节点")
    seen = {}

    async def mock(task, variables, schema):
        seen.update(variables)
        return fake

    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.impact_analysis("当输入企业名称时自动开网页", "- R1 | 感知/文字输入 | 开网页", "- Q1 | 可配置？")
    assert out is fake
    assert "自动开网页" in seen["new_text"] and "R1" in seen["rules_text"]
