# server/tests/test_agent_e2e.py —— fake dsh 全链路：/generate 与 /clarifications/review 走真子进程
import asyncio
import json
import pathlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.storage.project import ensure_root, project_root

BASE = "/api/projects/集成项目"
_FAKE = pathlib.Path(__file__).parent / "fake_dsh.py"
_FAKE_REG: dict[str, dict] = {}  # task → FAKE.json 控制内容（目录唯一化后不能预建目录，改为 build 时注入）

TREE_RESULT = {"root": {"goal": "给测试的需求逆向", "entry": "测试工程师 · 网页", "flow": "上传→生成",
                        "boundaries": "0 实证", "note": ""},
               "nodes": [{"name": "支付", "goal": "收款",
                          "cite": {"ev_id": "", "section": "1"}, "children": []}]}
EXTRACT_RESULT = {"rules": [{"text": "当收款时，系统应入账", "node": "支付", "conf": "文档",
                             "verified": True, "quote": "支付模块负责收款"}]}
CLAR_RESULT = {"results": [{"no": 1, "answered": True, "answer": "上传页",
                            "quote": "支付模块负责收款", "conf": "high"}]}


async def _wait_job_done(client, jid):
    for _ in range(200):
        rows = await client.get(f"{BASE}/jobs")
        j = next(x for x in rows.json() if x["id"] == jid)
        if j["status"] != "running":
            return j
        await asyncio.sleep(0.05)
    raise TimeoutError


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    monkeypatch.setenv("QUOS_DSH_CMD", f"python3 {_FAKE}")
    monkeypatch.setenv("QUOS_AGENT_ENGINE", "dsh")
    import app.ai.agent.export as ex
    monkeypatch.setattr(ex, "_TMP_BASE", tmp_path / "agentdir")
    real_build = ex.build_task_dir

    async def wrapped(root, evs, task, body):
        d = await real_build(root, evs, task, body)
        if task in _FAKE_REG:
            (d / "FAKE.json").write_text(json.dumps(_FAKE_REG[task], ensure_ascii=False), "utf-8")
        return d

    monkeypatch.setattr(ex, "build_task_dir", wrapped)
    _FAKE_REG.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    _FAKE_REG.clear()


def _seed(root, task, ctrl):
    _FAKE_REG[task] = ctrl


async def _seed_async(root):
    """registry 模式保底（test_agent_review_fixes 同款）——e2e 内已由 _seed 注入，此处保留空壳防外部引用"""
    return None


async def test_generate_full_chain(client, monkeypatch, tmp_path):
    from app.ai import tasks
    ensure_root("集成项目")
    root = project_root("集成项目")

    async def cf(rules):
        return []

    async def gp(summary, dims):
        return []

    async def asb(rules, node_name, note, parent_goal=""):
        from app.storage.profiles import Profile
        return Profile(node=node_name, goal="集成画像")
    for name, fn in (("conflict", cf), ("gaps", gp), ("assemble", asb)):
        monkeypatch.setattr(tasks, name, fn)  # 非 agent 任务照旧 mock

    ev = await client.post(f"{BASE}/evidence", json={"raw": "支付模块负责收款。"})
    assert ev.status_code == 200
    _seed(root, "tree-gen", {"result": TREE_RESULT}); _seed(root, "extract", {"result": EXTRACT_RESULT}); _seed(root, "verify", {"result": {"results": []}}); _seed(root, "clar-review", {"result": CLAR_RESULT})
    r = await client.post(f"{BASE}/generate")
    assert r.status_code == 200, r.text
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "done", j
    tree = (await client.get(f"{BASE}/tree")).json()
    assert tree and tree[0]["name"] == "支付"
    rules = (await client.get(f"{BASE}/rules")).json()
    assert any(a["text"] == "当收款时，系统应入账" and a["node"] == "支付" for a in rules)
    profs = (await client.get(f"{BASE}/profiles")).json()
    assert "__root__" in profs and "支付" in profs


async def test_clar_review_full_chain(client, tmp_path):
    from app.storage import clarifications
    ensure_root("集成项目")
    root = project_root("集成项目")
    ev = await client.post(f"{BASE}/evidence", json={"raw": "支付模块负责收款。"})
    ev_id = ev.json()["id"]
    await clarifications.add(root, "入口在哪?", [], kind="open")
    _seed(root, "tree-gen", {"result": TREE_RESULT}); _seed(root, "extract", {"result": EXTRACT_RESULT}); _seed(root, "verify", {"result": {"results": []}}); _seed(root, "clar-review", {"result": CLAR_RESULT})
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": [ev_id]})
    assert r.status_code == 200, r.text
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "done", j
    ws = await clarifications.list_all(root)
    assert ws[0].ai is not None and ws[0].ai.answer == "上传页"
    assert ws[0].ai.quote_ok is True and ws[0].ai.ev_ids == [ev_id]
