# server/tests/test_agent_review_fixes.py —— Final review findings 的修复测试（C1/I1/I2/I3/I4）
import asyncio
import json
import pathlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.storage.project import ensure_root, project_root

BASE = "/api/projects/修复项目"
_FAKE = pathlib.Path(__file__).parent / "fake_dsh.py"
_FAKE_REG: dict[str, dict] = {}  # task → FAKE.json 控制内容（目录唯一化后不能预建目录，改为 build 时注入）


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    import app.ai.agent.export as ex
    real = ex.build_task_dir

    async def wrapped(root, evs, task, body):
        d = await real(root, evs, task, body)
        if task in _FAKE_REG:
            (d / "FAKE.json").write_text(json.dumps(_FAKE_REG[task], ensure_ascii=False), "utf-8")
        return d

    monkeypatch.setattr(ex, "build_task_dir", wrapped)
    _FAKE_REG.clear()
    yield
    _FAKE_REG.clear()


async def _wait_job_settled(client, jid):
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _seed(root, task, ctrl):
    _FAKE_REG[task] = ctrl  # registry 注入：build_task_dir 包装时写入任务目录


# ---- I1：任务目录唯一命名——同项目同任务两次构造不得同目录（防脏读旧 result.json）----

async def test_task_dir_unique_per_run(tmp_path, monkeypatch):
    import app.ai.agent.export as ex
    monkeypatch.setattr(ex, "_TMP_BASE", tmp_path)
    from app.storage.evidence import Evidence
    ev = Evidence(id="a", name="a.md", ext="md", type="文档", stars=2, reg="", path="")
    d1 = await ex.build_task_dir(tmp_path, [ev], "extract", "x")
    await asyncio.sleep(0.01)
    d2 = await ex.build_task_dir(tmp_path, [ev], "extract", "x")
    assert d1 != d2, "两次运行必须不同目录——失败现场保留 + 防读旧产物"


# ---- I4：ingest_extract 无 schema 校验——缺 text/坏 conf 应 AgentRunError 且不落库----

async def test_extract_bad_payload_raises_clean(tmp_path):
    from app.ai.agent import ingest
    from app.ai.agent.runner import AgentRunError
    from app.storage import tree as tree_store
    tree_store.save(tmp_path, [tree_store.Node(name="支付", children=[])])
    manifest = [{"id": "文档a1", "type": "文档", "name": "a", "file": "文档a1.md"}]
    mdir = tmp_path / "m" / "materials"
    mdir.mkdir(parents=True)
    (mdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")
    (mdir / "文档a1.md").write_text("支付模块负责收款", "utf-8")
    ev = type("Ev", (), {"id": "文档a1", "name": "a.md"})()
    with pytest.raises(AgentRunError):
        await ingest.ingest_extract(tmp_path, ev, {"rules": [{"text": "", "conf": "bad"}]}, mdir.parent)
    with pytest.raises(AgentRunError):
        await ingest.ingest_extract(tmp_path, ev, {"rules": [{"conf": "文档"}]}, mdir.parent)  # 缺 text


# ---- I3：quote 定位图片池豁免（spec §4.4：无文本材料 quote_ok 恒 True，conf 承载可信度）----

async def test_extract_image_pool_quote_exempt(tmp_path):
    from app.ai.agent import ingest
    from app.storage import tree as tree_store
    tree_store.save(tmp_path, [tree_store.Node(name="支付", children=[])])
    manifest = [{"id": "图片b2", "type": "图片", "name": "b.png", "file": "图片b2.jpg"}]
    mdir = tmp_path / "m2" / "materials"
    mdir.mkdir(parents=True)
    (mdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")
    (mdir / "图片b2.jpg").write_bytes(b"x")
    ev = type("Ev", (), {"id": "图片b2", "name": "b.png"})()
    data = {"rules": [{"text": "当点击提交时，系统应弹确认框", "node": "支付", "conf": "实证",
                       "verified": True, "quote": "截图弹窗中可见确认按钮"}]}  # 图片描述性 quote
    n = await ingest.ingest_extract(tmp_path, ev, data, mdir.parent)
    assert n == 1
    from app.storage import rules as rule_store
    a = rule_store.load(tmp_path)[0]
    assert a.verified is True and not a.nb, "纯图片材料 quote 豁免——实证级规则核过"


def test_verify_image_pool_quote_exempt(tmp_path):
    from app.ai.agent import ingest
    from app.core.models import Rule
    manifest = [{"id": "图片b2", "type": "图片", "name": "b.png", "file": "图片b2.jpg"}]
    mdir = tmp_path / "m3" / "materials"
    mdir.mkdir(parents=True)
    (mdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")
    (mdir / "图片b2.jpg").write_bytes(b"x")
    items = [Rule(id="R1", text="截图实证规则", src="b", conf="实证")]
    data = {"results": [{"id": "R1", "ok": True, "quote": "截图描述性引用"}]}
    stat = ingest.ingest_verify(items, data, mdir.parent)
    assert stat["ok"] == 1 and items[0].verified is True


# ---- C1：verify/clar agent 失败 → job 落 failed 不卡 running ----

async def test_clar_review_agent_fail_marks_job_failed(client):
    from app.storage import clarifications
    ensure_root("修复项目")
    root = project_root("修复项目")
    ev = await client.post(f"{BASE}/evidence", json={"raw": "支付模块负责收款。"})
    await clarifications.add(root, "入口在哪?", [], kind="open")
    _seed(root, "clar-review", {"fail": True})
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": [ev.json()["id"]]})
    assert r.status_code == 200
    j = await _wait_job_settled(client, r.json()["job_id"])
    assert j["status"] == "failed", "agent 失败必须落终态，不得占死并发位"


async def test_verify_agent_fail_marks_job_failed(client):
    from app.core.models import Rule
    from app.storage import rules as rule_store
    ensure_root("修复项目")
    root = project_root("修复项目")
    await client.post(f"{BASE}/evidence", json={"raw": "支付模块负责收款。"})
    rule_store.save(root, [Rule(id="R1", text="旧文本", src="a", conf="文档")])
    _seed(root, "verify", {"fail": True})
    r = await client.post(f"{BASE}/rules/verify-job")
    assert r.status_code == 200
    j = await _wait_job_settled(client, r.json()["job_id"])
    assert j["status"] == "failed"


# ---- I2：generate phase2 核验段接 agent（_run_extract_verify 尾部不得走旧分批链路）----

async def test_generate_verify_phase_routes_to_agent(client, monkeypatch):
    from app.ai import tasks
    ensure_root("修复项目")
    root = project_root("修复项目")

    async def boom_verify(rules, material):  # 旧链路核验=爆炸，agent 模式不得触碰
        raise AssertionError("engine=on 不得走旧 verify 分批链路")

    monkeypatch.setattr(tasks, "verify", boom_verify)

    async def cf(rules):
        return []

    async def gp(summary, dims):
        return []

    async def asb(rules, node_name, note, parent_goal=""):
        from app.storage.profiles import Profile
        return Profile(node=node_name, goal="修复画像")

    for name, fn in (("conflict", cf), ("gaps", gp), ("assemble", asb)):
        monkeypatch.setattr(tasks, name, fn)

    await client.post(f"{BASE}/evidence", json={"raw": "支付模块负责收款。"})
    # extract 产物含 quote 失败条目 → verify 队列非空 → 核验段必经
    _seed(root, "tree-gen", {"result": {
        "root": {"goal": "g", "entry": "", "flow": "", "boundaries": "", "note": ""},
        "nodes": [{"name": "支付", "goal": "收款", "cite": {"ev_id": "", "section": ""}, "children": []}]}})
    _seed(root, "extract", {"result": {"rules": [
        {"text": "当收款时，系统应入账", "node": "支付", "conf": "文档",
         "verified": True, "quote": "定位不到的引用"}]}})  # quote 失败 → 未核验 → 进核验队列
    _seed(root, "verify", {"result": {"results": [
        {"id": "R1", "ok": True, "quote": "支付模块负责收款"}]}})
    r = await client.post(f"{BASE}/generate")
    assert r.status_code == 200, r.text
    j = await _wait_job_settled(client, r.json()["job_id"])
    assert j["status"] == "done", j
    from app.storage import rules as rule_store
    assert rule_store.load(root)[0].verified is True, "核验走了 agent 分支（FAKE verify 结果生效）"
