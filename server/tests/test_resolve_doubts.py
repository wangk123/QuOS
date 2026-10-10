# server/tests/test_resolve_doubts.py —— resolve-doubts 落库校验：auto/close 须 winner∈parties 且 quote 定位成功
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.models import Conflict, Gap, Rule
from app.main import app
from app.storage import findings, rules as rule_store
from app.storage import tree as tree_store
from app.storage.project import ensure_root


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _seed(root):
    tree_store.save(root, [tree_store.Node(name="支付", children=[])])
    rule_store.save(root, [
        Rule(id="R1", text="重试3次", src="a", conf="文档", verified=True, node="支付"),
        Rule(id="R2", text="重试5次", src="b", conf="文档", verified=True, node="支付"),
    ])
    findings.save_conflicts(root, [Conflict(id="C1", parties=["R1", "R2"], q="重试几次？")])
    findings.save_gaps(root, [Gap(id="G1", dim="边界", text="上限触发后行为未说明", node="支付")])


def _out(items):
    from app.ai.tasks import ResolveDoubtsOut
    return ResolveDoubtsOut.model_validate({"items": items})


@pytest.mark.asyncio
async def test_resolve_bad_winner_or_quote_keeps(tmp_path):
    """winner 越界 / quote 编造 → 全部 keep，不落库"""
    from app.api.router import _apply_resolve
    root = ensure_root("收编项目")
    _seed(root)
    items = [
        {"kind": "conflict", "id": "C1", "action": "auto", "winner": "R9", "quote": "固定重试 2 次"},
        {"kind": "conflict", "id": "C1", "action": "auto", "winner": "R1", "quote": "材料没有的话"},
        {"kind": "gap", "id": "G1", "action": "close", "quote": ""},
    ]
    stat = await _apply_resolve(root, _out(items), "材料……固定重试 2 次……")
    assert stat == {"auto_resolved": [], "auto_closed": []}
    assert findings.load_conflicts(root)[0].st == "open"
    assert findings.load_gaps(root)[0].st == "open"


@pytest.mark.asyncio
async def test_resolve_auto_applies(tmp_path):
    """winner∈parties 且 quote 定位成功 → 自动裁决（st=done 信胜方）；gap close → st=answered"""
    from app.api.router import _apply_resolve
    root = ensure_root("收编项目")
    _seed(root)
    items = [
        {"kind": "conflict", "id": "C1", "action": "auto", "winner": "R2", "quote": "固定重试 2 次"},
        {"kind": "gap", "id": "G1", "action": "close", "quote": "固定重试 2 次"},
    ]
    stat = await _apply_resolve(root, _out(items), "材料……固定重试 2 次……")
    assert stat == {"auto_resolved": ["C1"], "auto_closed": ["G1"]}
    c = findings.load_conflicts(root)[0]
    assert c.st == "done" and c.resolution == "R2"
    assert findings.load_gaps(root)[0].st == "answered"


@pytest.mark.asyncio
async def test_resolve_unknown_id_ignored(tmp_path):
    """未知 id / 非 open 状态 → 忽略不炸"""
    from app.api.router import _apply_resolve
    root = ensure_root("收编项目")
    _seed(root)
    items = [
        {"kind": "conflict", "id": "C9", "action": "auto", "winner": "R1", "quote": "固定重试 2 次"},
        {"kind": "gap", "id": "G9", "action": "close", "quote": "固定重试 2 次"},
    ]
    stat = await _apply_resolve(root, _out(items), "材料……固定重试 2 次……")
    assert stat == {"auto_resolved": [], "auto_closed": []}


async def test_off_engine_task(client, monkeypatch):
    """off 链：tasks.resolve_doubts 走 complete（prompt 任务存在即可被编排调用）"""
    from app.ai import tasks
    root = ensure_root("收编项目")
    _seed(root)
    await client.post("/api/projects/收编项目/evidence", json={"raw": "固定重试 2 次。"})
    monkeypatch.setattr(tasks, "complete", _fake_complete)
    out = await tasks.resolve_doubts("冲突清单", "材料")
    assert isinstance(out, tasks.ResolveDoubtsOut)


async def _fake_complete(task, variables, schema, images=None):
    from app.ai import tasks
    return tasks.ResolveDoubtsOut(items=[])


async def test_agent_engine_flow(tmp_path, monkeypatch):
    """agent 链：FAKE registry 注入 resolve-doubts 产物 → flow.resolve_doubts 走 ATD + 落库"""
    import json as _json
    import pathlib as _pl
    import app.ai.agent.export as ex
    from app.ai.agent import flow as agent_flow
    root = ensure_root("收编项目")
    _seed(root)
    from app.storage import evidence as ev_store
    await ev_store.add(root, {"type": "文档", "name": "新材料.md", "ext": "md", "stars": 2},
                       content="新材料：固定重试 2 次。".encode("utf-8"))
    monkeypatch.setattr(ex, "_TMP_BASE", tmp_path / "agentdir")
    fake = _pl.Path(__file__).parent / "fake_dsh.py"
    monkeypatch.setenv("QUOS_DSH_CMD", f"python3 {fake}")
    reg = {"resolve-doubts": {"result": {"items": [
        {"kind": "conflict", "id": "C1", "action": "auto", "winner": "R2", "quote": "固定重试 2 次"},
        {"kind": "gap", "id": "G1", "action": "close", "quote": "固定重试 2 次"}]}}}
    real_build = ex.build_task_dir

    async def wrapped(r, evs, task, body):
        d = await real_build(r, evs, task, body)
        if task in reg:
            (d / "FAKE.json").write_text(_json.dumps(reg[task], ensure_ascii=False), "utf-8")
        return d

    monkeypatch.setattr(ex, "build_task_dir", wrapped)
    await agent_flow.resolve_doubts(root, jid=None)
    assert findings.load_conflicts(root)[0].st == "done"
    assert findings.load_gaps(root)[0].st == "answered"
