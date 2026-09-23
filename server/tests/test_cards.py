# server/tests/test_cards.py
import pytest
from app.storage.cards import save_card, load_card, export_doc, Card, Rule
from app.storage import clarifications as cl

def _card(node="放款/重试", **kw):
    data = dict(node=node, goal="不重复放款", entry="回调超时30s",
                flow="入队→重发→最多3次",
                rules=[Rule(id="R1", text="上限3次", src="retry.py:42", conf="实证")],
                states="待放款→…", boundaries="", note="", deps="", unconfirmed=[])
    data.update(kw)
    return Card(**data)

def test_slug_and_roundtrip(tmp_path):
    p = save_card(tmp_path, "放款/重试", _card())
    assert "重试" in p.name and "/" not in p.name
    assert load_card(tmp_path, "放款/重试").rules[0].id == "R1"

def test_duplicate_name_suffix(tmp_path):
    save_card(tmp_path, "放款/重试", _card())
    p2 = save_card(tmp_path, "放款/重试", _card(note="第二张"))
    assert p2.name != "重试.md"

def test_export_doc(tmp_path):
    save_card(tmp_path, "放款/重试", _card())
    doc = export_doc(tmp_path)
    assert "R1" in doc and "放款/重试" in doc

def test_roundtrip_full(tmp_path):
    card = Card(node="还款/扣款", goal="准确扣款", entry="到期日触发",
                flow="计算→扣款→记账",
                rules=[Rule(id="R2", text="金额取整", src="pay.py:10", conf="推测")],
                states="待扣→已扣", boundaries="余额不足退卡", note="按日计息",
                deps="账务核心", unconfirmed=["币种舍入规则"])
    save_card(tmp_path, "还款/扣款", card)
    assert load_card(tmp_path, "还款/扣款") == card

@pytest.mark.asyncio
async def test_clarification_lifecycle(tmp_path):
    c = await cl.add(tmp_path, "重试上限是几次？", ["3次", "5次"], ref="cards/重试.md")
    assert c.no == 1 and c.st == "wait"
    c2 = await cl.add(tmp_path, "回调超时多久？", ["30s", "60s"])
    assert c2.no == 2 and c2.ref is None
    assert len(await cl.list_all(tmp_path)) == 2
    ans = await cl.answer(tmp_path, 1, 0)
    assert ans.answer == "3次" and ans.st == "answered"
    v = await cl.verify(tmp_path, 1)
    assert v.st == "verified"
    assert (tmp_path / "clarifications.json").exists()

@pytest.mark.asyncio
async def test_clarification_errors(tmp_path):
    await cl.add(tmp_path, "q", ["a", "b"])
    with pytest.raises(ValueError):
        await cl.answer(tmp_path, 99, 0)
    with pytest.raises(ValueError):
        await cl.answer(tmp_path, 1, 5)
