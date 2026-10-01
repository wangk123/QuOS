# server/tests/test_cards.py
import pytest
from app.storage.profiles import save_profile, load_profile, export_doc, Profile, ProfileRule
from app.storage import clarifications as cl

def _card(node="放款/重试", **kw):
    data = dict(node=node, goal="不重复放款", entry="回调超时30s",
                flow="入队→重发→最多3次",
                rules=[ProfileRule(id="R1", text="上限3次", src="retry.py:42", conf="实证")],
                states="待放款→…", boundaries="", note="", deps="", unconfirmed=[])
    data.update(kw)
    return Profile(**data)

def test_slug_and_roundtrip(tmp_path):
    p = save_profile(tmp_path, "放款/重试", _card())
    assert "重试" in p.name and "/" not in p.name
    assert load_profile(tmp_path, "放款/重试").rules[0].id == "R1"

def test_duplicate_name_suffix(tmp_path):
    save_profile(tmp_path, "放款/重试", _card())
    p2 = save_profile(tmp_path, "放款/重试", _card(note="第二张"))
    assert p2.name != "重试.md"

def test_export_doc(tmp_path):
    save_profile(tmp_path, "放款/重试", _card())
    doc = export_doc(tmp_path)
    assert "R1" in doc and "放款/重试" in doc

def test_slug_special_chars(tmp_path):
    p = save_profile(tmp_path, "放款/重 试!", _card(node="放款/重 试!"))
    assert "/" not in p.name and " " not in p.name and "!" not in p.name
    assert load_profile(tmp_path, "放款/重 试!").rules[0].id == "R1"

def test_duplicate_latest_wins(tmp_path):
    save_profile(tmp_path, "放款/重试", _card(goal="v1"))
    save_profile(tmp_path, "放款/重试", _card(goal="v2"))
    save_profile(tmp_path, "放款/重试", _card(goal="v3"))
    assert load_profile(tmp_path, "放款/重试").goal == "v3"
    doc = export_doc(tmp_path)
    assert "v3" in doc and "v1" not in doc and "v2" not in doc

def test_roundtrip_full(tmp_path):
    card = Profile(node="还款/扣款", goal="准确扣款", entry="到期日触发",
                flow="计算→扣款→记账",
                rules=[ProfileRule(id="R2", text="金额取整", src="pay.py:10", conf="推测")],
                states="待扣→已扣", boundaries="余额不足退卡", note="按日计息",
                deps="账务核心", unconfirmed=["币种舍入规则"])
    save_profile(tmp_path, "还款/扣款", card)
    assert load_profile(tmp_path, "还款/扣款") == card

@pytest.mark.asyncio
async def test_clarification_lifecycle(tmp_path):
    c = await cl.add(tmp_path, "重试上限是几次？", ["3次", "5次"], ref="profiles/重试.md")
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

def test_kind_roundtrip(tmp_path):
    p = Profile(node="__root__", kind="root", goal="总览一句话")
    f = save_profile(tmp_path, "__root__", p)
    back = load_profile(tmp_path, "__root__")
    assert back.kind == "root" and back.goal == "总览一句话"

def test_kind_default_leaf(tmp_path):
    save_profile(tmp_path, "支付/重试", Profile(node="支付/重试", goal="g"))
    assert load_profile(tmp_path, "支付/重试").kind == "leaf"

def test_export_root_first(tmp_path):
    save_profile(tmp_path, "__root__", Profile(node="__root__", kind="root", goal="总览G", flow="主线"))
    save_profile(tmp_path, "支付/重试", Profile(node="支付/重试", kind="leaf", goal="重试G"))
    open(tmp_path / "tree.md", "w").write("- 支付\n  - 重试\n")
    doc = export_doc(tmp_path)
    assert doc.index("## 需求总览") < doc.index("支付/重试") and "总览G" in doc and "主线" in doc

def test_export_module_profile(tmp_path):
    save_profile(tmp_path, "支付", Profile(node="支付", kind="module", goal="支付职责", boundaries="不碰清结算"))
    save_profile(tmp_path, "支付/重试", Profile(node="支付/重试", kind="leaf", goal="重试G"))
    open(tmp_path / "tree.md", "w").write("- 支付\n  - 重试\n")
    doc = export_doc(tmp_path)
    assert "### 支付" in doc and "- 职责：支付职责" in doc and "- 边界：不碰清结算" in doc

def test_export_root_not_orphan(tmp_path):
    save_profile(tmp_path, "__root__", Profile(node="__root__", kind="root", goal="总览G"))
    open(tmp_path / "tree.md", "w").write("- 支付\n  - 重试\n")
    doc = export_doc(tmp_path)
    assert "__root__" not in doc and doc.count("总览G") == 1

def test_export_all_empty_chapters_skipped(tmp_path):
    # 全空 root 画像：不输出空壳「## 需求总览」章
    save_profile(tmp_path, "__root__", Profile(node="__root__", kind="root"))
    # 全空 module 画像：树标题仍在，但不输出空壳「### 模块」段
    save_profile(tmp_path, "支付", Profile(node="支付", kind="module"))
    save_profile(tmp_path, "支付/重试", Profile(node="支付/重试", kind="leaf", goal="重试G"))
    open(tmp_path / "tree.md", "w").write("- 支付\n  - 重试\n")
    doc = export_doc(tmp_path)
    assert "## 需求总览" not in doc
    assert "### 支付\n" not in doc and "## 支付\n" in doc and "重试G" in doc
