# server/tests/test_clar_types.py —— 问人池类型化：type 字段 / 惰性推断 / extra 校验
import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.storage import clarifications
from app.storage.project import ensure_root

BASE = "/api/projects/类型项目"
PROJ = "类型项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _seed_legacy(root):
    """旧数据无 type 字段：手写落盘（模拟存量项目）"""
    rows = [
        {"no": 1, "q": "推测1一致吗？", "opts": ["确认一致", "与实际不符", "不清楚"], "kind": "choice",
         "st": "wait", "answer": None, "ref": "R1", "ai": None, "ans": None},
        {"no": 2, "q": "重试几次？", "opts": ["a文", "b文"], "kind": "choice",
         "st": "wait", "answer": None, "ref": "C1", "ai": None, "ans": None},
        {"no": 3, "q": "未说明幂等键？", "opts": [], "kind": "open",
         "st": "wait", "answer": None, "ref": "G1", "ai": None, "ans": None},
        {"no": 4, "q": "自己问的", "opts": [], "kind": "open",
         "st": "wait", "answer": None, "ref": None, "ai": None, "ans": None},
    ]
    (root / "clarifications.json").write_text(json.dumps(rows, ensure_ascii=False), "utf-8")


async def test_legacy_type_inferred_from_ref(client):
    root = ensure_root(PROJ)
    _seed_legacy(root)
    rows = await clarifications.list_all(root)
    assert [c.type for c in rows] == ["confirm", "choose", "supply", "custom"]


async def test_confirm_mismatch_requires_extra(client):
    root = ensure_root(PROJ)
    await clarifications.add(root, "推测一致吗？", ["确认一致", "与实际不符", "不清楚"],
                             ref="R1", type="confirm")
    r = await client.post(f"{BASE}/clarifications", json={"no": 1, "action": "answer", "idx": 1})
    assert r.status_code == 422 and "实际行为" in r.json()["detail"]
    r = await client.post(f"{BASE}/clarifications",
                          json={"no": 1, "action": "answer", "idx": 1, "extra": "   "})
    assert r.status_code == 422  # 空白串同样拒绝
    r = await client.post(f"{BASE}/clarifications",
                          json={"no": 1, "action": "answer", "idx": 1, "extra": "实际是静默跳过"})
    assert r.status_code == 200
    assert r.json()["ans"]["extra"] == "实际是静默跳过"
    assert r.json()["answer"] == "与实际不符"


async def test_entries_create_typed_questions(client):
    from app.core.models import Conflict, Gap, Rule
    from app.storage import findings, rules as rule_store
    root = ensure_root(PROJ)
    rule_store.save(root, [
        Rule(id="R1", text="当文档为空时系统应拒绝并提示", src="a.md", conf="推测"),
        Rule(id="R2", text="重试 3 次", src="b.py:1", conf="实证"),
        Rule(id="R3", text="重试 5 次", src="b.md#2", conf="文档"),
    ])
    findings.save_conflicts(root, [Conflict(id="C1", a="R2", b="R3", q="重试几次？")])
    findings.save_gaps(root, [Gap(id="G1", dim="状态", text="未说明幂等行为", node="")])

    await client.post(f"{BASE}/rules/R1/ask")  # 默认问法 → confirm
    await client.post(f"{BASE}/rules/R2/ask", json={"q": "压缩包加密实际怎么处理？"})  # 自定义 → custom 开放
    await client.post(f"{BASE}/conflicts", json={"id": "C1", "action": "clar"})  # → choose
    await client.post(f"{BASE}/gaps", json={"id": "G1", "action": "clar"})  # → supply 开放

    rows = await clarifications.list_all(root)
    by_type = {c.type: c for c in rows}
    assert by_type["confirm"].opts == ["确认一致", "与实际不符", "不清楚"]
    assert by_type["confirm"].q.endswith("该推测与实际系统一致吗？")
    assert by_type["custom"].opts == [] and by_type["custom"].kind == "open"
    assert by_type["choose"].opts == ["重试 3 次", "重试 5 次"]
    assert by_type["supply"].opts == [] and by_type["supply"].kind == "open"
    # 规则占用联动：R1/R2 的 clar 指向各自题号
    assert {a.id: a.clar for a in rule_store.load(root)}["R1"] == by_type["confirm"].no


async def _seed_rule(root, rid, text):
    from app.core.models import Rule
    from app.storage import rules as rule_store
    items = [a for a in rule_store.load(root) if a.id != rid]
    items.append(Rule(id=rid, text=text, src="a.md", conf="推测"))
    rule_store.save(root, items)


async def _ask(root, rid, no, qtype="confirm"):
    await clarifications.add(root, f"{rid} 的推测一致吗？", ["确认一致", "与实际不符", "不清楚"],
                             ref=rid, type=qtype)


async def test_confirm_answer_linkage_branches(client):
    root = ensure_root(PROJ)
    from app.storage import rules as rule_store

    await _seed_rule(root, "R1", "原推测1")
    await _ask(root, "R1", 1)
    await client.post(f"{BASE}/clarifications", json={"no": 1, "action": "answer", "idx": 0})
    a1 = next(a for a in rule_store.load(root) if a.id == "R1")
    assert a1.verified is True and a1.clar is None  # 一致 → 核过

    await _seed_rule(root, "R2", "原推测2")
    await _ask(root, "R2", 2)
    await client.post(f"{BASE}/clarifications",
                      json={"no": 2, "action": "answer", "idx": 1, "extra": "实际是生成失败 Run 可重试"})
    a2 = next(a for a in rule_store.load(root) if a.id == "R2")
    assert a2.text == "实际是生成失败 Run 可重试"  # 改写
    assert a2.suspect is True and a2.verified is True and a2.nb == ""  # 黄标修正 + 核过

    await _seed_rule(root, "R3", "原推测3")
    await _ask(root, "R3", 3)
    await client.post(f"{BASE}/clarifications", json={"no": 3, "action": "answer", "idx": 2})
    a3 = next(a for a in rule_store.load(root) if a.id == "R3")
    assert a3.verified is False and a3.text == "原推测3" and a3.clar is None  # 不清楚 → 不动但解除占用

    await _seed_rule(root, "R4", "原推测4")
    await _ask(root, "R4", 4, qtype="custom")
    await client.post(f"{BASE}/clarifications", json={"no": 4, "action": "answer", "text": "问过了，差不多"})
    a4 = next(a for a in rule_store.load(root) if a.id == "R4")
    assert a4.verified is False and a4.text == "原推测4" and a4.clar is None  # custom → 无联动仅解除占用


async def test_confirm_linkage_covers_ai_answer_texts(client):
    """收窄前存量的 confirm+ai 被 adopt：答案文本分流，不符无 extra 不改写"""
    root = ensure_root(PROJ)
    from app.storage import rules as rule_store
    await _seed_rule(root, "R1", "原推测1")
    rows = [{"no": 1, "q": "q", "opts": ["确认一致", "与实际不符", "不清楚"], "kind": "choice",
             "type": "confirm", "st": "wait", "answer": None, "ref": "R1",
             "ai": {"answer": "与实际不符", "quote": "x", "ev_ids": [], "conf": "low", "quote_ok": False},
             "ans": None}]
    (root / "clarifications.json").write_text(json.dumps(rows, ensure_ascii=False), "utf-8")
    await client.post(f"{BASE}/clarifications", json={"no": 1, "action": "adopt"})
    a1 = next(a for a in rule_store.load(root) if a.id == "R1")
    assert a1.verified is False and a1.text == "原推测1"  # 不符且无 extra：不改写不核过


async def test_supply_answer_saved_as_clar_evidence(client):
    root = ensure_root(PROJ)
    from app.storage import evidence
    await clarifications.add(root, "未说明幂等键？", [], ref="G1", type="supply")
    await clarifications.add(root, "自己问的", [], ref="R1", type="custom")
    r = await client.post(f"{BASE}/clarifications",
                          json={"no": 1, "action": "answer", "text": "幂等键为受理单号+文档指纹", "ev_ids": []})
    assert r.status_code == 200
    evs = await evidence.list_all(root)
    assert len(evs) == 1 and evs[0].source == "clar"
    await client.post(f"{BASE}/clarifications", json={"no": 2, "action": "answer", "text": "口头答案"})
    evs = await evidence.list_all(root)
    assert len(evs) == 1  # custom 不入池


async def test_review_skips_confirm_questions(client, monkeypatch):
    from app.ai import tasks
    from app.storage import evidence
    root = ensure_root(PROJ)
    await client.post(f"{BASE}/evidence", json={"raw": "材料：相似度阈值 0.85 时进入人工复核。"})
    ev_id = (await evidence.list_all(root))[0].id
    await clarifications.add(root, "推测一致吗？", ["确认一致", "与实际不符", "不清楚"], ref="R1", type="confirm")
    await clarifications.add(root, "阈值边界行为是什么？", [], ref="G1", type="supply")

    seen = {}

    async def mock_review(qs, materials, images=None):
        seen["qs"] = qs
        from app.core.models import AiReview  # noqa: F401（构造见 _apply_review 契约）
        return type("R", (), {"results": [{"no": 2, "answered": True, "answer": "阈值取等号判为命中",
                                           "quote": "", "conf": "med"}]})()

    monkeypatch.setattr(tasks, "clar_review", mock_review)
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": [ev_id]})
    assert r.status_code == 200
    for _ in range(100):  # 等 job 收尾
        jobs = (await client.get(f"{BASE}/jobs")).json()
        if next(j for j in jobs if j["id"] == r.json()["job_id"])["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert "阈值边界" in seen["qs"] and "推测一致吗" not in seen["qs"]


async def test_review_all_confirm_returns_explanatory_422(client):
    from app.storage import evidence
    root = ensure_root(PROJ)
    await client.post(f"{BASE}/evidence", json={"raw": "材料"})
    ev_id = (await evidence.list_all(root))[0].id
    await clarifications.add(root, "推测一致吗？", ["确认一致", "与实际不符", "不清楚"], ref="R1", type="confirm")
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": [ev_id]})
    assert r.status_code == 422 and "确认题" in r.json()["detail"]
