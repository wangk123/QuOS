# server/tests/test_generate.py（fixture/client 模式照 test_api.py；BASE 前缀 /api/projects）
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai import tasks
from app.main import app
from app.storage.project import ensure_root

BASE = "/api/projects/生成项目"


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


def _mock_pipeline(monkeypatch):
    async def u(material, images=None):
        return tasks.UnderstandOut(
            root=tasks.UnderstandRoot(goal="假需求", entry="客户经理"),
            nodes=[tasks.OutlineNode(name="感知", goal="输入", children=[
                tasks.OutlineNode(name="文字输入", goal="输入企业名称", children=[])])])

    async def ex(content, evidence_type, tree_text, images=None):
        from app.core.models import Rule
        return [Rule(id="", text="当输入企业名称时系统应自动开网页", src="材料实证",
                     conf="推测", node="感知/文字输入")]

    async def vf(rules, material):
        return type("V", (), {"results": []})()

    async def cf(rules):
        return []

    async def gp(summary, dims):
        return []

    async def asb(rules, node_name, note, parent_goal=""):
        from app.storage.profiles import Profile
        return tasks.AssembleOut(profile=Profile(node=node_name, goal="假画像"))

    for name, fn in (("understand", u), ("extract", ex), ("verify", vf),
                     ("conflict", cf), ("gaps", gp), ("assemble", asb)):
        monkeypatch.setattr(tasks, name, fn)


async def test_generate_rejected_without_evidence(client):
    ensure_root("生成项目")
    r = await client.post(f"{BASE}/generate")
    assert r.status_code == 422


async def test_generate_runs_pipeline(client, monkeypatch):
    ensure_root("生成项目")
    await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    _mock_pipeline(monkeypatch)
    r = await client.post(f"{BASE}/generate")
    assert r.status_code == 200 and "job_id" in r.json()
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "done" and j["ok"] >= 1
    tree = (await client.get(f"{BASE}/tree")).json()
    assert tree and tree[0]["name"] == "感知", "understand 落了树"
    profs = (await client.get(f"{BASE}/profiles")).json()
    assert "__root__" in profs and "感知/文字输入" in profs
    assert "感知" in profs, "R2：模块节点也落初始画像"


async def test_generate_empty_skeleton_fails_without_dirty_tree(client, monkeypatch):
    ensure_root("生成项目")
    await client.post(f"{BASE}/evidence", json={"raw": "一句话"})
    async def u(material, images=None):
        return tasks.UnderstandOut(root=tasks.UnderstandRoot(goal="g"), nodes=[])
    monkeypatch.setattr(tasks, "understand", u)
    r = await client.post(f"{BASE}/generate")
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "failed"
    assert not (await client.get(f"{BASE}/tree")).json(), "空骨架不得落树"


async def test_generate_ai_failure_marks_failed_and_frees_slot(client, monkeypatch):
    ensure_root("生成项目")
    await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})

    async def boom(material, images=None):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(tasks, "understand", boom)
    r = await client.post(f"{BASE}/generate")
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "failed" and "生成失败" in j["label"]
    r2 = await client.post(f"{BASE}/generate")  # failed 不占并发位：可再次发起
    assert r2.status_code == 200 and "job_id" in r2.json()


async def test_generate_cancel_keeps_finished(client, monkeypatch):
    ensure_root("生成项目")
    await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    _mock_pipeline(monkeypatch)
    async def slow_extract(content, evidence_type, tree_text, images=None):
        await asyncio.sleep(5)
        return []
    monkeypatch.setattr(tasks, "extract", slow_extract)
    r = await client.post(f"{BASE}/generate")
    jid = r.json()["job_id"]
    await asyncio.sleep(0.3)  # 等 outline 落树、进入 extract
    await client.post(f"{BASE}/generate/cancel")
    j = await _wait_job_done(client, jid)
    assert j["status"] == "cancelled"
    assert (await client.get(f"{BASE}/tree")).json(), "已完成的大纲保留"


async def test_generate_extract_all_failed_marks_failed_no_fake_done(client, monkeypatch):
    """提取全军覆没：job 置 failed 且流水线停——不得产出「树有骨架、条目全 0」的假完成"""
    ensure_root("生成项目")
    await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    _mock_pipeline(monkeypatch)
    async def boom(content, evidence_type, tree_text, images=None):
        raise RuntimeError("ReadTimeout")
    monkeypatch.setattr(tasks, "extract", boom)
    r = await client.post(f"{BASE}/generate")
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "failed" and "提取全部失败" in j["label"]
    assert j["failed"] >= 1
    rules = (await client.get(f"{BASE}/rules")).json()
    assert rules == [], "失败提取不得落规则"
