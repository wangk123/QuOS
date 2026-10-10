# server/tests/test_ai_conflict.py
from app.ai import tasks
from app.core.models import Rule, Conflict, Gap
from app.storage import dims


async def test_conflict(monkeypatch):
    fake = tasks.ConflictOut(conflicts=[tasks.ConflictDraft(q="重试次数：代码3次 vs 文档5次", parties=["A1", "A2"])])
    async def mock(task, variables, schema): return fake
    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.conflict([
        Rule(id="R1", text="当超时应重试3次", src="retry.py:15", conf="实证"),
        Rule(id="R2", text="当超时应重试5次", src="spec.md#3", conf="文档"),
    ])
    assert out[0].id == ""  # 归组扫描不产 id——merge_conflicts 落库时续 C{n}
    assert out[0].parties == ["A1", "A2"]
    assert "重试" in out[0].q


async def test_gap(monkeypatch):
    fake = tasks.GapOut(gaps=[Gap(id="G1", dim="幂等", text="未说明重复提交时的幂等行为")])
    async def mock(task, variables, schema): return fake
    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.gaps("用户画像摘要", ["状态", "幂等"])
    assert out[0].id == "G1"
    assert out[0].dim == "幂等"
    assert "幂等" in out[0].text


def test_dims_roundtrip(tmp_path):
    assert dims.get_dims(tmp_path) == ["状态", "异常", "边界", "幂等", "数据", "依赖"]
    dims.set_dims(tmp_path, ["性能", "安全"])
    assert dims.get_dims(tmp_path) == ["性能", "安全"]
