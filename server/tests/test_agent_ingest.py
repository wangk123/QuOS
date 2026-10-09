# server/tests/test_agent_ingest.py
import json

from app.ai.agent import ingest
from app.core.models import Clarification, Rule
from app.storage import rules as rule_store
from app.storage import tree as tree_store
from app.storage.profiles import ROOT_NODE, load_profile

DATA = {"nodes": [{"name": "支付", "goal": "收款", "cite": {"ev_id": "文档a1", "section": "4.1"},
                   "children": [{"name": "放款重试", "goal": "重试",
                                 "cite": {"ev_id": "编造的", "section": "x"}, "children": []}]}],
        "root": {"goal": "g", "entry": "e", "flow": "f", "boundaries": "b", "note": ""}}


def _dir(tmp_path, manifest=None, texts=None):
    d = tmp_path / "agent"
    (d / "materials").mkdir(parents=True)
    manifest = manifest or [{"id": "文档a1", "type": "文档", "name": "a.md", "file": "文档a1.md"}]
    (d / "materials" / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")
    for ev_id, t in (texts or {"文档a1": "支付模块负责收款与放款重试。"}).items():
        f = next(m["file"] for m in manifest if m["id"] == ev_id)
        (d / "materials" / f).write_text(t, "utf-8")
    return d


async def test_tree_roundtrip(tmp_path):
    d = _dir(tmp_path)
    warns = await ingest.ingest_tree(tmp_path, DATA, d)
    assert any("放款重试" in w or "1 个节点" in w for w in warns)  # cite 失配产生告警
    nodes = tree_store.load(tmp_path)
    assert nodes[0].name == "支付" and nodes[0].children[0].name == "放款重试"
    assert load_profile(tmp_path, ROOT_NODE).goal == "g"
    assert load_profile(tmp_path, "支付").goal == "收款"
    assert load_profile(tmp_path, "支付/放款重试").goal == "重试"


async def test_extract_quote_mismatch(tmp_path):
    d = _dir(tmp_path)
    data = {"rules": [{"text": "系统应支持放款重试", "node": "支付/放款重试", "conf": "文档",
                       "verified": True, "quote": "材料里根本不存在的话"},
                      {"text": "系统应支持收款", "node": "不存在的路径", "conf": "文档",
                       "verified": True, "quote": "支付模块负责收款"}]}
    ev = type("Ev", (), {"id": "文档a1", "name": "需求.md"})()
    n = await ingest.ingest_extract(tmp_path, ev, data, d)
    assert n == 2
    items = rule_store.load(tmp_path)
    by_text = {a.text: a for a in items}
    assert by_text["系统应支持放款重试"].verified is False            # quote 定位失败回落
    assert by_text["系统应支持放款重试"].nb == "引用无法定位"
    assert by_text["系统应支持收款"].node == ""                        # 白名单失配置空
    assert all(a.src_id == "文档a1" for a in items)                    # 替换语义


async def test_extract_replaces_previous_batch(tmp_path):
    d = _dir(tmp_path)
    ev = type("Ev", (), {"id": "文档a1", "name": "需求.md"})()
    await ingest.ingest_extract(tmp_path, ev, {"rules": []}, d)  # 先落一条存量（别的材料）
    rule_store.save(tmp_path, [Rule(id="R1", text="旧材料条目", src="旧", conf="文档", src_id="别的材料")])
    n = await ingest.ingest_extract(tmp_path, ev, {"rules": [
        {"text": "新条目", "node": "", "conf": "文档", "verified": False, "quote": ""}]}, d)
    assert n == 1
    items = rule_store.load(tmp_path)
    assert [a.id for a in items] == ["R1", "R2"]  # 续编号 + 旧材料条目保留
    assert items[1].src_id == "文档a1"


def test_verify_paths(tmp_path):
    d = _dir(tmp_path)
    items = [Rule(id="R1", text="旧文本", src="a", conf="文档"),
             Rule(id="R2", text="推测的", src="a", conf="推测")]
    data = {"results": [{"id": "R1", "ok": True, "quote": "支付模块负责收款"},
                        {"id": "R2", "ok": False, "reason": "材料中无对应依据"},
                        {"id": "R9", "ok": True}]}
    stat = ingest.ingest_verify(items, data, d)
    assert stat == {"ok": 1, "corrected": 0, "nobasis": 1}
    assert items[0].verified is True and items[1].nb == "材料中无对应依据"


def test_verify_quote_mismatch_falls_to_nobasis(tmp_path):
    d = _dir(tmp_path)
    items = [Rule(id="R1", text="旧文本", src="a", conf="文档")]
    data = {"results": [{"id": "R1", "ok": True, "quote": "编造的引用"}]}
    stat = ingest.ingest_verify(items, data, d)
    assert stat["ok"] == 0 and stat["nobasis"] == 1
    assert items[0].verified is False and items[0].nb == "引用无法定位"


def test_clar_paths(tmp_path):
    d = _dir(tmp_path)
    waits = [Clarification(no=1, q="支持哪些格式?", opts=["PDF/图片", "仅 PDF"], kind="choice"),
             Clarification(no=2, q="入口在哪?", opts=[], kind="open")]
    data = {"results": [
        {"no": 1, "answered": True, "answer": "第三个选项", "quote": "支付模块", "conf": "high"},
        {"no": 2, "answered": True, "answer": "上传页", "quote": "编造的引用", "conf": "high"},
        {"no": 7, "answered": True, "answer": "x", "quote": "", "conf": "high"}]}
    n = ingest.ingest_clar(waits, data, d, ev_ids=["文档a1"])
    assert n == 1                                     # choice 未命中丢弃、未知 no 丢弃
    assert waits[1].ai.quote_ok is False and waits[1].ai.conf == "low"
    assert waits[0].ai is None                        # choice 丢弃 → 不落 ai
