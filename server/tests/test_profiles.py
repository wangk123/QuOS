# server/tests/test_cards.py
import pytest
from app.storage.profiles import save_profile, load_profile, export_doc, Profile, ProfileRule

def _card(node="放款/重试", **kw):
    data = dict(node=node, goal="不重复放款", entry="回调超时30s",
                flow="入队→重发→最多3次",
                rules=[ProfileRule(id="R1", text="上限3次", src="retry.py:42", conf="实证")],
                states="待放款→…", boundaries="", note="", deps="")
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
                deps="账务核心")
    save_profile(tmp_path, "还款/扣款", card)
    assert load_profile(tmp_path, "还款/扣款") == card


def test_legacy_unconfirmed_section_ignored(tmp_path):
    """unconfirmed 已退役（assemble 读后感，游离于「核验通过/待处理」两分流外）：
    存量画像的「## 未确认项」段静默忽略，其余字段正常读；重存后该段消失"""
    d = tmp_path / "profiles"; d.mkdir()
    (d / "旧节点.md").write_text("""---
node: 旧节点
kind: leaf
goal: g
entry: e
---

# 旧节点

## 未确认项

- 某某待确认（历史遗留读后感）

## 主流程

1. 步骤一

## 规则

| ID | 规则 | 来源 | 置信度 |
|---|---|---|---|
| R1 | 旧规则 | a.md | 文档 |
""", "utf-8")
    p = load_profile(tmp_path, "旧节点")
    assert p.goal == "g" and p.flow.strip().startswith("1.")
    assert len(p.rules) == 1
    save_profile(tmp_path, "旧节点", p)
    assert "未确认项" not in (d / "旧节点-2.md").read_text("utf-8")


