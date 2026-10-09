# server/tests/test_agent_flow.py
import json
import pathlib

import pytest

from app.ai.agent import flow
from app.storage import tree as tree_store
from app.storage import evidence as ev_store
from app.storage.profiles import ROOT_NODE, load_profile

_FAKE = pathlib.Path(__file__).parent / "fake_dsh.py"


@pytest.fixture(autouse=True)
def _fake(monkeypatch, tmp_path):
    import app.ai.agent.export as ex
    monkeypatch.setattr(ex, "_TMP_BASE", tmp_path / "agentdir")
    monkeypatch.setenv("QUOS_DSH_CMD", f"python3 {_FAKE}")


async def _mk_ev(root: pathlib.Path, ev_id="文档a1", name="需求.md",
                 content="# 需求\n支付模块负责收款。"):
    # 走真实 evidence.add 入 index——flow 经 list_all 取材料
    return await ev_store.add(root, {"id": ev_id, "type": "文档", "name": name,
                                     "ext": name.rsplit(".", 1)[-1], "stars": 2},
                              content=content.encode("utf-8"))


async def _seed_tree(tmp_path):
    tree_store.save(tmp_path, [tree_store.Node(name="支付", children=[])])
    return tmp_path


async def test_gen_tree_end_to_end(tmp_path):
    ev = await _mk_ev(tmp_path)
    import app.ai.agent.flow as f
    import app.ai.agent.export as ex
    d_holder = {}

    real_build = ex.build_task_dir

    async def spy_build(root, evs, task, body):
        d = await real_build(root, evs, task, body)
        d_holder["d"] = d
        (d / "FAKE.json").write_text(json.dumps({
            "result": {"root": {"goal": "g", "entry": "", "flow": "", "boundaries": "", "note": ""},
                       "nodes": [{"name": "支付", "goal": "收款",
                                  "cite": {"ev_id": ev.id, "section": "1"},
                                  "children": []}]}}, ensure_ascii=False), "utf-8")
        return d

    import app.ai.agent.ingest  # flow 经 export.build_task_dir 间接调用——monkeypatch export 层
    monkeypatch_holder = pytest.MonkeyPatch()
    monkeypatch_holder.setattr(f.export, "build_task_dir", spy_build)
    try:
        warns = await flow.gen_tree("p", tmp_path, jid=None)
        assert warns == []
        assert tree_store.load(tmp_path)[0].name == "支付"
        assert load_profile(tmp_path, ROOT_NODE).goal == "g"
        assert not d_holder["d"].exists()  # 成功路径 cleanup 删除任务目录
    finally:
        monkeypatch_holder.undo()


async def test_gen_tree_empty_nodes_raises(tmp_path):
    await _mk_ev(tmp_path)
    import app.ai.agent.export as ex

    real_build = ex.build_task_dir

    async def spy_build(root, evs, task, body):
        d = await real_build(root, evs, task, body)
        (d / "FAKE.json").write_text(json.dumps({
            "result": {"root": {"goal": "", "entry": "", "flow": "", "boundaries": "", "note": ""},
                       "nodes": []}}), "utf-8")
        return d

    from app.ai.agent.runner import AgentRunError
    mp = pytest.MonkeyPatch()
    mp.setattr(flow.export, "build_task_dir", spy_build)
    try:
        with pytest.raises(AgentRunError):
            await flow.gen_tree("p", tmp_path, jid=None)
    finally:
        mp.undo()


async def test_extract_one_marks_extracted(tmp_path):
    ev = await _mk_ev(tmp_path)
    await _seed_tree(tmp_path)
    import app.ai.agent.export as ex
    from app.storage import evidence as ev_store

    real_build = ex.build_task_dir

    async def spy_build(root, evs, task, body):
        d = await real_build(root, evs, task, body)
        assert "支付" in body  # TASK.md 带树白名单
        (d / "FAKE.json").write_text(json.dumps({
            "result": {"rules": [{"text": "当收款时，系统应入账", "node": "支付", "conf": "文档",
                                  "verified": True, "quote": "支付模块负责收款"}]}},
            ensure_ascii=False), "utf-8")
        return d

    mp = pytest.MonkeyPatch()
    mp.setattr(flow.export, "build_task_dir", spy_build)
    try:
        n = await flow.extract_one(tmp_path, ev)
        assert n == 1
        after = await ev_store.get(tmp_path, ev.id)
        assert after.state == "extracted" and after.count == 1
    finally:
        mp.undo()


async def test_verify_all_and_clar_review(tmp_path):
    from app.core.models import Clarification, Rule
    from app.storage import clarifications, jobs
    from app.storage import rules as rule_store

    await _mk_ev(tmp_path, ev_id="文档a1")
    await _seed_tree(tmp_path)
    rule_store.save(tmp_path, [Rule(id="R1", text="旧文本", src="a", conf="文档")])
    await clarifications.add(tmp_path, "入口在哪?", [], kind="open")
    import app.ai.agent.export as ex
    real_build = ex.build_task_dir
    results = {"verify": {"results": [{"id": "R1", "ok": True, "quote": "支付模块负责收款"}]},
               "clar-review": {"results": [{"no": 1, "answered": True, "answer": "上传页",
                                            "quote": "支付模块负责收款", "conf": "high"}]}}

    async def spy_build(root, evs, task, body):
        d = await real_build(root, evs, task, body)
        (d / "FAKE.json").write_text(json.dumps({"result": results[task]},
                                                ensure_ascii=False), "utf-8")
        return d

    mp = pytest.MonkeyPatch()
    mp.setattr(flow.export, "build_task_dir", spy_build)
    try:
        jv = jobs.create("verify-batch", "核验", 1)
        await flow.verify_all(tmp_path, ["R1"], only_doc=False, jid=jv)
        assert rule_store.load(tmp_path)[0].verified is True
        jc = jobs.create("clar-review", "重检", 1)
        waits = await clarifications.list_all(tmp_path)
        n = await flow.clar_review_all(tmp_path, waits, ["文档a1"], jid=jc)
        assert n == 1
        w = (await clarifications.list_all(tmp_path))[0]
        assert w.ai is not None and w.ai.answer == "上传页"
        assert jobs.get(jv)["status"] == "done" and jobs.get(jc)["status"] == "done"
    finally:
        mp.undo()
