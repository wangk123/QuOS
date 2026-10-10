# server/tests/test_smart_regen.py —— 智能生成编排：六阶段、自动裁决/闭环落 job、空输入安全
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.models import Conflict, Gap, Rule
from app.main import app
from app.storage import findings, rules as rule_store
from app.storage import tree as tree_store
from app.storage.project import ensure_root

BASE = "/api/projects/智能项目"


async def _wait_job_done(client, jid):
    for _ in range(200):
        rows = await client.get(f"{BASE}/jobs")
        j = next(x for x in rows.json() if x["id"] == jid)
        if j["status"] != "running":
            return j
        await asyncio.sleep(0.05)
    raise TimeoutError


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _seed(root, with_doubts=True):
    tree_store.save(root, [tree_store.Node(name="支付", children=[
        tree_store.Node(name="放款重试", children=[])])])
    rule_store.save(root, [
        Rule(id="R1", text="重试3次", src="a", conf="文档", verified=True, node="支付/放款重试"),
        Rule(id="R2", text="重试5次", src="b", conf="文档", verified=True, node="支付/放款重试"),
        Rule(id="R3", text="旧未核规则", src="c", conf="文档", verified=False, node="支付/放款重试"),
    ])
    if with_doubts:
        findings.save_conflicts(root, [Conflict(id="C1", parties=["R1", "R2"], q="重试几次？")])
        findings.save_gaps(root, [Gap(id="G1", dim="边界", text="上限后行为未说明", node="支付/放款重试")])


def _mock_all(monkeypatch, *, resolve_items=None, impact_nodes=("支付/放款重试",)):
    """off 链全 mock：extract/verify/resolve/impact/assemble/summary"""
    from app.ai import tasks

    async def ex(content, evidence_type, tree_text, images=None):
        return []

    async def vf(rules, material):
        return type("V", (), {"results": [{"id": a.id, "ok": True, "quote": "固定重试 2 次"}
                                          for a in rules]})()

    async def rd(doubts, materials):
        return tasks.ResolveDoubtsOut.model_validate(
            {"items": resolve_items or []})

    async def im(new_text, rules_text, clars_text):
        return tasks.ImpactOut(nodes=list(impact_nodes))

    async def asb(rules, node_name, note, parent_goal=""):
        from app.storage.profiles import Profile
        return tasks.AssembleOut(profile=Profile(node=node_name, goal="智能画像"))

    async def sm(parts, kind):
        return tasks.SummaryOut(goal="g", entry="", boundaries="", note="")

    for name, fn in (("extract", ex), ("verify", vf), ("resolve_doubts", rd),
                     ("impact_analysis", im), ("assemble", asb), ("summary", sm)):
        monkeypatch.setattr(tasks, name, fn)


async def test_smart_full_chain(client, monkeypatch):
    """六阶段依序：新材料→重核→疑点直处（自动裁决+闭环落 job）→影响分析→重组→汇总"""
    root = ensure_root("智能项目")
    await _seed(root)
    ev = await client.post(f"{BASE}/evidence", json={"raw": "新材料：固定重试 2 次。"})
    ev_id = ev.json()["id"]
    monkeypatch.setenv("QUOS_AGENT_ENGINE", "off")
    _mock_all(monkeypatch, resolve_items=[
        {"kind": "conflict", "id": "C1", "action": "auto", "winner": "R2", "quote": "固定重试 2 次"},
        {"kind": "gap", "id": "G1", "action": "close", "quote": "固定重试 2 次"}])
    r = await client.post(f"{BASE}/regen", json={"mode": "smart", "ev_ids": [ev_id]})
    assert r.status_code == 200, r.text
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "done", j
    assert j["auto_resolved"] == ["C1"] and j["auto_closed"] == ["G1"]
    assert j["regen_nodes"] == ["支付/放款重试"]
    assert findings.load_conflicts(root)[0].st == "done"
    assert findings.load_gaps(root)[0].st == "answered"


async def test_smart_noop_done(client, monkeypatch):
    """无疑点无未核验：各阶段空输入安全跳过，job 正常 done"""
    ensure_root("智能项目")
    ev = await client.post(f"{BASE}/evidence", json={"raw": "只有材料。"})
    monkeypatch.setenv("QUOS_AGENT_ENGINE", "off")
    _mock_all(monkeypatch, impact_nodes=())
    r = await client.post(f"{BASE}/regen", json={"mode": "smart", "ev_ids": [ev.json()["id"]]})
    assert r.status_code == 200
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "done", j
    assert j["auto_resolved"] == [] and j["auto_closed"] == []


async def test_smart_bad_mode_422(client):
    ensure_root("智能项目")
    ev = await client.post(f"{BASE}/evidence", json={"raw": "材料。"})
    r = await client.post(f"{BASE}/regen", json={"mode": "partial", "ev_ids": [ev.json()["id"]]})
    # 编造 mode 落 full（白名单），partial 已退役不再可用
    assert r.json()["mode"] == "full"


async def test_smart_verify_fail_not_overridden(client, monkeypatch):
    """I2：阶段②核验失败（flow 内置 failed）不得被覆盖回 running 假 done"""
    from app.ai import tasks
    root = ensure_root("智能项目")
    await _seed(root)
    ev = await client.post(f"{BASE}/evidence", json={"raw": "新材料：固定重试 2 次。"})
    monkeypatch.setenv("QUOS_AGENT_ENGINE", "off")

    async def ex(content, evidence_type, tree_text, images=None):
        return []

    async def vf(rules, material):
        raise RuntimeError("核验链路炸了")

    async def im(new_text, rules_text, clars_text):
        raise AssertionError("verify 失败后不得继续跑影响分析")

    monkeypatch.setattr(tasks, "extract", ex)
    monkeypatch.setattr(tasks, "verify", vf)
    monkeypatch.setattr(tasks, "impact_analysis", im)
    r = await client.post(f"{BASE}/regen", json={"mode": "smart", "ev_ids": [ev.json()["id"]]})
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "failed", j
