# server/tests/test_regen.py（T16：regen 三模式 + summary 聚合重生成）
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai import tasks
from app.core.models import Rule
from app.main import app
from app.storage.project import ensure_root

BASE = "/api/projects/重生成项目"


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


async def _seed(client):
    """已有需求：树两叶工商查询/负面排查、材料一份（初态走 regen full 建立——/generate 在树非空时 409）"""
    root = ensure_root("重生成项目")
    for op in ("/tree|add||支付", "/tree|add|0|工商查询", "/tree|add|0|负面排查"):
        _, p, path, name = op.split("|")
        await client.post(f"{BASE}/tree", json={"op": p, "path": path or None, "name": name})
    r = await client.post(f"{BASE}/evidence", json={"raw": "当输入企业名称时，系统应自动启动网页。"})
    return root, r.json()["id"]


def _mock_pipeline(monkeypatch):  # 与 tests/test_generate.py 同款（tests 非包，各文件自持一份）+ summary
    async def u(material, images=None):
        return tasks.UnderstandOut(
            root=tasks.UnderstandRoot(goal="假需求", entry="客户经理"),
            nodes=[tasks.OutlineNode(name="支付", goal="支付", children=[
                tasks.OutlineNode(name="工商查询", goal="查询", children=[])])])

    async def ex(content, evidence_type, tree_text, images=None):
        return [Rule(id="", text="当输入企业名称时系统应自动开网页", src="材料实证",
                     conf="推测", node="支付/工商查询")]

    async def vf(rules, material):
        return type("V", (), {"results": []})()

    async def cf(rules):
        return []

    async def gp(summary, dims):
        return []

    async def asb(rules, node_name, note, parent_goal=""):
        from app.storage.profiles import Profile
        return tasks.AssembleOut(profile=Profile(node=node_name, goal="假画像"))

    async def sm(parts, kind):
        return tasks.SummaryOut(goal="假聚合", entry="客户经理")

    for name, fn in (("understand", u), ("extract", ex), ("verify", vf),
                     ("conflict", cf), ("gaps", gp), ("assemble", asb), ("summary", sm)):
        monkeypatch.setattr(tasks, name, fn)




async def test_regen_full_reruns_pipeline(client, monkeypatch):
    _, ev_id = await _seed(client)
    _mock_pipeline(monkeypatch)
    r = await client.post(f"{BASE}/regen", json={"mode": "full", "ev_ids": [ev_id]})
    assert r.status_code == 200, "树已非空时 full 不 409"
    j = await _wait_job_done(client, r.json()["job_id"])
    assert j["status"] == "done"


async def test_regen_guards(client):
    ensure_root("重生成项目")
    r = await client.post(f"{BASE}/regen", json={"mode": "partial", "ev_ids": []})
    assert r.status_code == 422
    r = await client.post(f"{BASE}/regen", json={"mode": "partial", "ev_ids": ["NOPE"]})
    assert r.status_code == 404


async def test_summary_regen_updates_root_and_modules(client, monkeypatch):
    """根卡 ↻：同步重聚合 root+全部 module 画像（leaf 不动）；job 并发位被占时 409"""
    from app.storage import profiles as profile_store
    from app.storage import jobs as jobs_store
    root, ev_id = await _seed(client)
    profile_store.save_profile(root, "支付/工商查询", profile_store.Profile(
        node="支付/工商查询", goal="查工商", flow="输入名称\n出报告", kind="leaf"))
    profile_store.save_profile(root, profile_store.ROOT_NODE, profile_store.Profile(
        node=profile_store.ROOT_NODE, kind="root", goal="旧总览"))

    async def sm(parts, kind):
        assert kind in ("module", "root") and parts
        return tasks.SummaryOut(goal=f"聚合·{kind}", entry="客户经理")
    monkeypatch.setattr(tasks, "summary", sm)

    r = await client.post(f"{BASE}/summary/regen")
    assert r.status_code == 200 and profile_store.ROOT_NODE in r.json()["updated"]
    rp = (await client.get(f"{BASE}/wb/summary")).json()["root"]
    assert rp["goal"] == "聚合·root", "根 goal 被聚合更新"
    leaf = profile_store.load_profile(root, "支付/工商查询")
    assert leaf.goal == "查工商", "leaf 画像不动"
    assert profile_store.load_profile(root, profile_store.ROOT_NODE).entry == "客户经理", "entry 一并写回"

    monkeypatch.setattr(jobs_store, "running", lambda: {"label": "生成需求", "cur": 1, "total": 6})
    assert (await client.post(f"{BASE}/summary/regen")).status_code == 409


