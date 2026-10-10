# server/tests/test_conflict_parties.py —— Conflict 多方模型：读侧迁移 / 信 N 方 / 其他手输落实证规则
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.models import Conflict, Rule
from app.main import app
from app.storage import findings, rules as rule_store
from app.storage.project import ensure_root

BASE = "/api/projects/多方项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _seed(root):
    from app.storage import tree as tree_store
    tree_store.save(root, [tree_store.Node(name="支付", children=[
        tree_store.Node(name="放款重试", children=[])])])
    rule_store.save(root, [
        Rule(id="R1", text="重试3次", src="a", conf="文档", verified=True, node="支付/放款重试"),
        Rule(id="R2", text="重试5次", src="b", conf="文档", verified=True, node="支付/放款重试"),
        Rule(id="R3", text="不重试", src="c", conf="文档", verified=True, node="支付/放款重试"),
    ])
    findings.save_conflicts(root, [Conflict(id="C1", parties=["R1", "R2", "R3"], q="重试几次？")])


def test_legacy_ab_migrated(tmp_path):
    """旧 a/b 数据读侧自动转 parties；st=clar 归一 done（直写 json 造旧格式）"""
    import json
    root = ensure_root("多方项目")
    (root / "conflicts.json").write_text(json.dumps(
        [{"id": "C9", "a": "R1", "b": "R2", "q": "旧冲突", "st": "clar"}], ensure_ascii=False), "utf-8")
    cs = findings.load_conflicts(root)
    assert cs[0].parties == ["R1", "R2"] and cs[0].st == "done"


async def test_code_side_multi(client):
    """信指定一方（side=索引）：胜方保留，其余各方全部作废"""
    root = ensure_root("多方项目")
    _seed(root)
    r = await client.post(f"{BASE}/conflicts", json={"id": "C1", "action": "code", "side": 1})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["st"] == "done" and out["resolution"] == "R2"
    from app.api.router import _void_ids
    assert _void_ids(root) == {"R1", "R3"}
    # 规则列表同口径过滤：规则 tab 只剩胜方（未裁决前 open 冲突各方仍在列表，由前端归待处理）
    ids = [a["id"] for a in (await client.get(f"{BASE}/rules")).json()]
    assert ids == ["R2"]


async def test_code_bad_side_422(client):
    root = ensure_root("多方项目")
    _seed(root)
    r = await client.post(f"{BASE}/conflicts", json={"id": "C1", "action": "code", "side": 5})
    assert r.status_code == 422


async def test_manual_resolve_creates_rule(client):
    """其他+手输：全方作废 + 生成人工确认实证规则（绑定归属节点，续编号）"""
    root = ensure_root("多方项目")
    _seed(root)
    r = await client.post(f"{BASE}/conflicts",
                          json={"id": "C1", "action": "manual", "text": "固定重试 2 次后转人工"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["st"] == "done" and out["resolution"] == "manual"
    assert out["manual_text"] == "固定重试 2 次后转人工"
    added = [a for a in rule_store.load(root) if a.text == "固定重试 2 次后转人工"]
    assert added and added[0].id == "R4" and added[0].conf == "实证"
    assert added[0].verified is True and added[0].node == "支付/放款重试"
    assert "人工确认" in added[0].src
    from app.api.router import _void_ids
    assert _void_ids(root) == {"R1", "R2", "R3"}
    # 规则列表只剩新增的实证规则——互斥三选一，不是三方全留
    ids = [a["id"] for a in (await client.get(f"{BASE}/rules")).json()]
    assert ids == ["R4"]


async def test_manual_empty_text_422(client):
    root = ensure_root("多方项目")
    _seed(root)
    r = await client.post(f"{BASE}/conflicts", json={"id": "C1", "action": "manual", "text": " "})
    assert r.status_code == 422


async def test_legacy_code_state_migrated(client):
    """存量 st='code' 已裁决冲突读侧迁移 done——败方 void 不复活（防静默数据回归）"""
    import json as _json
    root = ensure_root("多方项目")
    _seed(root)
    (root / "conflicts.json").write_text(_json.dumps(
        [{"id": "C8", "parties": ["R1", "R2"], "q": "旧裁决", "st": "code", "resolution": "R1"}],
        ensure_ascii=False), "utf-8")
    cs = findings.load_conflicts(root)
    c8 = next(c for c in cs if c.id == "C8")
    assert c8.st == "done" and c8.resolution == "R1"
    from app.api.router import _void_ids
    assert "R2" in _void_ids(root)


async def test_confirm_rule_endpoint_ok(client):
    """人工核过端点不因 Rule.clar 退役残留赋值 500"""
    root = ensure_root("多方项目")
    _seed(root)
    r = await client.post(f"{BASE}/rules/R3/confirm")
    assert r.status_code == 204, r.text
    rules = {a.id: a for a in rule_store.load(root)}
    assert rules["R3"].verified is True
