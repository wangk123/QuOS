# server/tests/test_manual_actions.py —— 人工处置三端点：缺口补写 / 规则修正 / 手动记规则
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.models import Gap, Rule
from app.main import app
from app.storage import findings, rules as rule_store
from app.storage import tree as tree_store
from app.storage.project import ensure_root

BASE = "/api/projects/人工项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _seed(root):
    tree_store.save(root, [tree_store.Node(name="支付", children=[
        tree_store.Node(name="放款重试", children=[])])])
    rule_store.save(root, [
        Rule(id="R1", text="旧表述", src="a", conf="文档", verified=False, node="支付/放款重试")])
    findings.save_gaps(root, [Gap(id="G1", dim="边界", text="上限后行为未说明", node="支付/放款重试")])


async def test_gap_note_creates_rule_and_closes(client):
    """缺口补写：手输实际行为 → 实证规则（绑缺口节点）+ 缺口闭环 answered"""
    root = ensure_root("人工项目")
    _seed(root)
    r = await client.post(f"{BASE}/gaps", json={"id": "G1", "action": "note",
                                                "text": "上限触发后转人工工单"})
    assert r.status_code == 200, r.text
    assert r.json()["st"] == "answered"
    added = [a for a in rule_store.load(root) if a.text == "上限触发后转人工工单"]
    assert added and added[0].id == "R2" and added[0].conf == "实证"
    assert added[0].verified is True and added[0].node == "支付/放款重试"
    assert "人工补写" in added[0].src


async def test_gap_note_empty_422(client):
    root = ensure_root("人工项目")
    _seed(root)
    r = await client.post(f"{BASE}/gaps", json={"id": "G1", "action": "note", "text": " "})
    assert r.status_code == 422
    assert findings.load_gaps(root)[0].st == "open"  # 不闭环不落规则


async def test_rule_correct(client):
    """规则人工修正：文本替换 + 标黄留痕（suspect）+ 核过"""
    root = ensure_root("人工项目")
    _seed(root)
    r = await client.post(f"{BASE}/rules/R1/correct", json={"text": "修正后的实际行为"})
    assert r.status_code == 200, r.text
    a = next(x for x in rule_store.load(root) if x.id == "R1")
    assert a.text == "修正后的实际行为" and a.suspect is True and a.verified is True


async def test_rule_manual_add(client):
    """自定义开放：手动记规则（问题+答案文本）→ 实证规则绑指定节点"""
    root = ensure_root("人工项目")
    _seed(root)
    r = await client.post(f"{BASE}/rules", json={"text": "回调地址支持 HTTP 与 HTTPS",
                                                 "node": "支付/放款重试"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["id"] == "R2" and out["conf"] == "实证" and out["verified"] is True
    assert out["node"] == "支付/放款重试" and "人工记录" in out["src"]


async def test_rule_manual_bad_node_422(client):
    root = ensure_root("人工项目")
    _seed(root)
    r = await client.post(f"{BASE}/rules", json={"text": "x", "node": "不存在的节点"})
    assert r.status_code == 422
