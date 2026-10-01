# server/tests/test_impact.py（T15：材料级影响分析 + _safe_mode 白名单）
import pytest
from httpx import ASGITransport, AsyncClient

from app.ai import tasks
from app.core.models import Rule
from app.main import app
from app.storage import clarifications as cl
from app.storage import rules as rule_store
from app.storage import tree as tree_store
from app.storage.project import ensure_root
from app.storage.tree import Node

BASE = "/api/projects/影响项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _seed_assets():
    """树：感知/文字输入；条目 R1 挂该节点；wait 题 Q1——impact 输出的合法值域"""
    root = ensure_root("影响项目")
    tree_store.save(root, [Node(name="感知", children=[Node(name="文字输入")])])
    rule_store.save(root, [Rule(id="R1", text="当输入企业名称时系统应自动开网页",
                                src="材料实证", conf="文档", node="感知/文字输入")])
    await cl.add(root, "自动开网页是否可配置？", [])
    return root


async def test_impact_endpoint(client, monkeypatch):
    root = await _seed_assets()
    r = await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    ev_id = r.json()["id"]

    async def fake_impact(new_text, rules_text, clars_text):
        assert "自动启动网页" in new_text
        assert "R1" in rules_text and "Q1" in clars_text, "清单喂给 AI"
        return tasks.ImpactOut(nodes=["感知/文字输入"], rule_ids=["R1"], clar_nos=["Q1"], mode="partial")

    monkeypatch.setattr(tasks, "impact_analysis", fake_impact)
    r = await client.post(f"{BASE}/regen/impact", json={"ev_ids": [ev_id]})
    assert r.status_code == 200
    body = r.json()
    assert body["recommend"] == "partial" and body["nodes"] == ["感知/文字输入"]
    assert body["rule_ids"] == ["R1"] and body["clar_nos"] == ["Q1"]


async def test_impact_drops_hallucinations(client, monkeypatch):
    """防幻觉：编造的节点/条目/题号一律丢弃；mode 编造落 partial"""
    await _seed_assets()
    r = await client.post(f"{BASE}/evidence", json={"raw": "新材料"})
    ev_id = r.json()["id"]

    async def fake_impact(new_text, rules_text, clars_text):
        return tasks.ImpactOut(nodes=["不存在的节点"], rule_ids=["R9"], clar_nos=["Q9"], mode="全量重跑")

    monkeypatch.setattr(tasks, "impact_analysis", fake_impact)
    body = (await client.post(f"{BASE}/regen/impact", json={"ev_ids": [ev_id]})).json()
    assert body["nodes"] == [] and body["rule_ids"] == [] and body["clar_nos"] == []
    assert body["recommend"] == "partial"


async def test_impact_guards(client):
    """空材料列表→422；材料不存在→404"""
    ensure_root("影响项目")
    r = await client.post(f"{BASE}/regen/impact", json={"ev_ids": []})
    assert r.status_code == 422
    r = await client.post(f"{BASE}/regen/impact", json={"ev_ids": ["NOPE"]})
    assert r.status_code == 404


def test_impact_mode_whitelist():
    from app.api.generate import _safe_mode
    assert _safe_mode("全量重跑") == "partial"   # AI 编造值落回 partial
    assert _safe_mode("rescan") == "rescan"
    assert _safe_mode("full") == "full"
