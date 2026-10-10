# server/tests/test_findings_flow.py —— 组装补充发现（findings）自证分流收编：
# AI 补充无第三分类——quote 在材料中定位成功 → 核验通过规则；否则/没说清 → 缺口（待处理）
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.models import Rule
from app.main import app
from app.storage import findings as finding_store
from app.storage import rules as rule_store
from app.storage.project import ensure_root

BASE = "/api/projects/收编项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _seed_findings(client, monkeypatch, findings_out):
    """建树+两条已核验规则+一份含原文的材料；patch tasks.assemble 返回指定 findings。
    返回项目 root（异步调用：先 await 再用）"""

    async def _do():
        from app.ai import tasks
        root = ensure_root("收编项目")
        await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
        await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
        await client.post(f"{BASE}/evidence", json={"raw": "重试 3 次均失败后置为失败终态。人工介入路径未定义。"})

        async def fake_assemble(rules, node_name, note, parent_goal=""):
            from app.storage.profiles import Profile, ProfileRule
            return tasks.AssembleOut(
                profile=Profile(node=node_name, goal="不重复放款", rules=[
                    ProfileRule(id=r.id, text=r.text, src=r.src, conf=r.conf) for r in rules]),
                findings=[tasks.Finding.model_validate(f) for f in findings_out])

        monkeypatch.setattr(tasks, "assemble", fake_assemble)
        return root

    return _do


async def test_findings_split_rule_and_gap(client, monkeypatch):
    """自证分流：quote 定位成功→核验通过规则（续号/绑节点）；没说清→缺口；
    quote 编造→强制降为缺口；与现有规则文本重复→丢弃"""
    findings = [
        {"kind": "rule", "text": "当重试全部失败时，系统应把流水置为终态失败",
         "quote": "重试 3 次均失败后置为失败终态"},
        {"kind": "gap", "text": "重试上限触发后是否人工介入未说明"},
        {"kind": "rule", "text": "当编造依据时，系统应拒绝", "quote": "材料里根本没有这句话"},
        {"kind": "rule", "text": "超时后重试 3 次", "quote": "重试 3 次均失败后置为失败终态"},  # 与 R1 重复
    ]
    root = await _seed_findings(client, monkeypatch, findings)()
    rule_store.save(root, [
        Rule(id="R1", text="超时后重试 3 次", src="材料", conf="文档", verified=True, node="支付/放款重试"),
        Rule(id="R2", text="原流水号重发", src="材料", conf="文档", verified=True, node="支付/放款重试"),
    ])
    r = await client.post(f"{BASE}/profiles/assemble", json={"node_path": "0,0", "note": ""})
    assert r.status_code == 200, r.text

    rules = rule_store.load(root)
    added = [a for a in rules if a.id not in ("R1", "R2")]
    assert len(added) == 1 and added[0].id == "R3"  # 仅 quote 真实且不重复的那条成规则
    assert added[0].verified is True and added[0].node == "支付/放款重试"
    assert added[0].conf == "文档" and "画像组装" in added[0].src

    gaps = finding_store.load_gaps(root)
    texts = {g.text for g in gaps}
    assert "重试上限触发后是否人工介入未说明" in texts            # gap 类落缺口
    assert "当编造依据时，系统应拒绝" in texts                     # quote 编造 → 强制降为缺口
    assert all(g.node == "支付/放款重试" for g in gaps)           # 全部绑定当前节点
    assert all(g.st == "open" for g in gaps)


async def test_findings_gap_dedup_on_reassemble(client, monkeypatch):
    """重复组装同批 findings：缺口 (dim,text,node) 去重、规则文本去重——不产生重复条目"""
    findings = [{"kind": "gap", "text": "重试上限触发后是否人工介入未说明"}]
    root = await _seed_findings(client, monkeypatch, findings)()
    rule_store.save(root, [
        Rule(id="R1", text="超时后重试 3 次", src="材料", conf="文档", verified=True, node="支付/放款重试"),
        Rule(id="R2", text="原流水号重发", src="材料", conf="文档", verified=True, node="支付/放款重试"),
    ])
    for _ in range(2):
        r = await client.post(f"{BASE}/profiles/assemble", json={"node_path": "0,0", "note": ""})
        assert r.status_code == 200
    gaps = [g for g in finding_store.load_gaps(root)
            if g.text == "重试上限触发后是否人工介入未说明"]
    assert len(gaps) == 1
