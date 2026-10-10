# server/tests/test_agent_orchestr.py —— 编排层四处分流：on 态走 flow、不碰旧 tasks 链路
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai import tasks
from app.main import app
from app.storage.project import ensure_root

BASE = "/api/projects/分流项目"


async def _wait_job_done(client, jid):
    for _ in range(100):
        rows = await client.get(f"{BASE}/jobs")
        j = next(x for x in rows.json() if x["id"] == jid)
        if j["status"] != "running":
            return j
        await asyncio.sleep(0.05)
    raise TimeoutError


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _engine_on(monkeypatch):
    from app.ai.agent import flow as agent_flow

    async def _boom(*a, **k):
        raise AssertionError("engine=on 不得走旧 tasks 链路")

    calls = {"gen_tree": 0, "extract_one": 0, "verify_all": 0}

    async def gen_tree(proj, root, jid):
        calls["gen_tree"] += 1
        from app.storage import tree as tree_store
        tree_store.save(root, [tree_store.Node(name="支付", children=[])])
        return []

    async def extract_one(root, ev, jid=None):
        calls["extract_one"] += 1
        return 1

    async def verify_all(root, ids, only_doc, jid):
        calls["verify_all"] += 1
        from app.storage import jobs
        jobs.finish(jid)

    for mod in ("app.api.generate", "app.api.router"):
        monkeypatch.setattr(f"{mod}.engine_on", lambda: True, raising=False)
    monkeypatch.setattr(agent_flow, "gen_tree", gen_tree)
    monkeypatch.setattr(agent_flow, "extract_one", extract_one)
    monkeypatch.setattr(agent_flow, "verify_all", verify_all)
    # 旧链路全炸（understand/extract/verify 三任务不得被触碰）
    for name in ("understand", "extract", "verify"):
        monkeypatch.setattr(tasks, name, _boom)
    return calls


def _mock_rest_pipeline(monkeypatch):
    """非 agent 任务（conflict/gaps/assemble）照常 mock——generate 后半段要跑"""

    async def cf(rules):
        return []

    async def gp(summary, dims):
        return []

    async def asb(rules, node_name, note, parent_goal=""):
        from app.storage.profiles import Profile
        return Profile(node=node_name, goal="假画像")

    for name, fn in (("conflict", cf), ("gaps", gp), ("assemble", asb)):
        monkeypatch.setattr(tasks, name, fn)


async def test_generate_phase1_routes_to_agent(client, monkeypatch):
    ensure_root("分流项目")
    await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    calls = _engine_on(monkeypatch)
    _mock_rest_pipeline(monkeypatch)
    r = await client.post(f"{BASE}/generate")
    assert r.status_code == 200
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "done"
    assert calls["gen_tree"] == 1 and calls["extract_one"] >= 1
    tree = (await client.get(f"{BASE}/tree")).json()
    assert tree and tree[0]["name"] == "支付", "树来自 agent flow"


async def test_extract_verify_route_to_agent(client, monkeypatch):
    from app.core.models import Rule
    from app.storage import rules as rule_store
    from app.storage.project import project_root

    ensure_root("分流项目")
    root = project_root("分流项目")
    ev = await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    ev_id = ev.json()["id"]
    calls = _engine_on(monkeypatch)
    from app.storage import tree as tree_store
    tree_store.save(root, [tree_store.Node(name="支付", children=[])])

    r = await client.post(f"{BASE}/evidence/extract-job")
    assert r.status_code == 200
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "done" and calls["extract_one"] == 1

    # extract 完成后再落未核验规则（真实时序）——verify 分支的前置
    rule_store.save(root, [Rule(id="R1", text="旧文本", src="a", conf="文档")])

    r = await client.post(f"{BASE}/rules/verify-job")
    assert r.status_code == 200
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "done" and calls["verify_all"] == 1
