# server/tests/test_api.py
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai import tasks
from app.ai.runner import AITaskError
from app.core.models import Assertion, Conflict, Gap
from app.main import app
from app.storage.cards import Card, Rule
from app.storage.project import ensure_root

BASE = "/api/projects/演示项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_end_to_end(client, monkeypatch):
    root = ensure_root("演示项目")

    # ① 入池：raw 文本走 classify
    r = await client.post(f"{BASE}/evidence",
                          json={"raw": "当请求超时，客户端应重试3次；当余额不足，系统应拒绝放款并提示。"})
    assert r.status_code == 200
    ev = r.json()
    assert ev["type"] == "文本" and ev["state"] == "pending"
    ev_id = ev["id"]

    # 树：建节点供后续组装
    r = await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "放款"})
    assert r.status_code == 200
    r = await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
    assert r.status_code == 200 and len(r.json()) == 1

    # ② 提取：mock ai.extract 返回 2 断言落库
    async def mock_extract(content, evidence_type, tree_text):
        assert "重试" in content and evidence_type == "文本"
        return [Assertion(id="E1", text="当请求超时，客户端应重试3次", src="retry.py:15", conf="实证",
                          node="放款/放款重试"),
                Assertion(id="E2", text="当余额不足，系统应拒绝放款", src="loan.py:30", conf="文档",
                          node="放款/放款重试")]

    monkeypatch.setattr(tasks, "extract", mock_extract)
    r = await client.post(f"{BASE}/evidence/{ev_id}/extract")
    assert r.status_code == 200 and r.json()["added"] == 2
    r = await client.get(f"{BASE}/assertions")
    assert [a["id"] for a in r.json()] == ["A1", "A2"]
    assert all(not a["verified"] for a in r.json())
    r = await client.get(f"{BASE}/evidence")
    assert r.json()[0]["state"] == "extracted" and r.json()[0]["count"] == 2

    # ③ 组装被阻断：409 + 未核验清单
    r = await client.post(f"{BASE}/cards/assemble", json={"node_path": "0,0", "note": ""})
    assert r.status_code == 409
    assert set(r.json()["detail"]["unqualified"]) == {"A1", "A2"}

    # ④ 核验置位
    async def mock_verify(assertions, material):
        assert "重试" in material
        return tasks.VerifyOut(results=[{"id": a.id, "ok": True, "corrected_text": None,
                                         "reason": "与材料一致"} for a in assertions])

    monkeypatch.setattr(tasks, "verify", mock_verify)
    r = await client.post(f"{BASE}/assertions/verify", json={})
    assert r.status_code == 200
    r = await client.get(f"{BASE}/assertions")
    assert all(a["verified"] and not a["suspect"] for a in r.json())

    # ⑤ 组装成功：卡片落盘
    async def mock_assemble(assertions, node_name, note):
        assert node_name == "放款重试" and "幂等" in note
        return Card(node=node_name, goal="验证放款重试行为正确",
                    rules=[Rule(id="R1", text="超时后重试3次", src="retry.py:15", conf="实证")],
                    note=note)

    monkeypatch.setattr(tasks, "assemble", mock_assemble)
    r = await client.post(f"{BASE}/cards/assemble", json={"node_path": "0,0", "note": "补充幂等"})
    assert r.status_code == 200
    assert r.json()["card"]["node"] == "放款/放款重试"
    assert list((root / "cards").glob("*.md"))
    r = await client.get(f"{BASE}/cards/0,0")
    assert r.status_code == 200 and r.json()["rules"][0]["id"] == "R1"

    # ⑥ 导出文档含 R1
    r = await client.get(f"{BASE}/doc")
    assert r.status_code == 200 and "R1" in r.text and "放款/放款重试" in r.text

    # ⑦ 基线：tag v1 + 独立 git 仓库
    r = await client.post(f"{BASE}/baseline", json={"note": "首个基线"})
    assert r.status_code == 200
    first = r.json()
    assert first["tag"] == "v1" and first["v"] == 1 and len(first["commit"]) >= 7
    assert (root / ".git").is_dir()
    r = await client.get(f"{BASE}/baseline")
    assert r.json() == [{"tag": "v1", "commit": first["commit"]}]

    # ⑧ 树操作：add / rename / del
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "额度"})
    r = await client.post(f"{BASE}/tree", json={"op": "rename", "path": "1", "name": "额度校验"})
    assert r.json()[1]["name"] == "额度校验"
    r = await client.post(f"{BASE}/tree", json={"op": "del", "path": "1"})
    assert len(r.json()) == 1

    # ⑨ conflict/gap 路由 smoke
    async def mock_conflict(assertions):
        return [Conflict(id="C1", a="A1", b="A2", q="重试次数：代码3次 vs 文档5次")]

    monkeypatch.setattr(tasks, "conflict", mock_conflict)
    r = await client.post(f"{BASE}/conflicts/rescan")
    assert r.status_code == 200
    r = await client.get(f"{BASE}/conflicts")
    assert [c["id"] for c in r.json()] == ["C1"]

    # 裁决：信代码侧
    r = await client.post(f"{BASE}/conflicts", json={"id": "C1", "action": "code", "side": "a"})
    assert r.status_code == 200 and r.json()["resolution"] == "A1" and r.json()["st"] == "code"

    async def mock_gaps(summary, dims):
        assert "放款" in summary
        return [Gap(id="G1", dim="幂等", text="未说明重复提交的幂等键"),
                Gap(id="G2", dim="编造维度", text="应被过滤")]

    monkeypatch.setattr(tasks, "gaps", mock_gaps)
    r = await client.post(f"{BASE}/gaps/rescan")
    assert r.status_code == 200
    r = await client.get(f"{BASE}/gaps")
    assert [g["id"] for g in r.json()] == ["G1"]  # 自造维度被过滤
    r = await client.post(f"{BASE}/gaps", json={"id": "G1", "action": "ok"})
    assert r.json()["st"] == "ok"

    # 问人链：gap 转问人 → answer → verify
    monkeypatch.setattr(tasks, "gaps", mock_gaps)
    await client.post(f"{BASE}/gaps/rescan")
    r = await client.post(f"{BASE}/gaps", json={"id": "G1", "action": "clar"})
    assert r.status_code == 200
    r = await client.get(f"{BASE}/clarifications")
    assert len(r.json()) == 1
    no = r.json()[0]["no"]
    r = await client.post(f"{BASE}/clarifications", json={"no": no, "action": "answer", "idx": 0})
    assert r.json()["st"] == "answered"
    r = await client.post(f"{BASE}/clarifications", json={"no": no, "action": "verify"})
    assert r.json()["st"] == "verified"


async def test_evidence_file_upload(client):
    ensure_root("演示项目")
    r = await client.post(f"{BASE}/evidence", content=b"%PDF-1.4",
                          headers={"content-type": "application/octet-stream", "x-filename": "spec v1.pdf"})
    assert r.status_code == 200
    assert r.json()["type"] == "文档" and r.json()["name"] == "spec v1.pdf"


async def test_evidence_filename_urlencoded(client):
    ensure_root("演示项目")
    # 前端 encodeURIComponent 后传入，入库应还原原文（中文/空格不落 %XX）
    from urllib.parse import quote
    r = await client.post(f"{BASE}/evidence", content=b"PK\x03\x04",
                          headers={"content-type": "application/octet-stream",
                                   "x-filename": quote("需求 文档.docx")})
    assert r.status_code == 200
    assert r.json()["name"] == "需求 文档.docx"


async def test_evidence_invalid_input(client):
    ensure_root("演示项目")
    assert (await client.post(f"{BASE}/evidence", json={"raw": ""})).status_code == 422
    assert (await client.post(f"{BASE}/evidence", content=b"")).status_code == 422
    r = await client.post(f"{BASE}/evidence/NOPE/extract")
    assert r.status_code == 404


async def test_verify_correction_written_back(client, monkeypatch):
    ensure_root("演示项目")
    await client.post(f"{BASE}/evidence", json={"raw": "材料内容"})

    async def mock_extract(content, evidence_type, tree_text):
        return [Assertion(id="E1", text="固定60s重试", src="retry.py:15", conf="实证"),
                Assertion(id="E2", text="重试上限5次", src="spec.md#3", conf="文档")]

    monkeypatch.setattr(tasks, "extract", mock_extract)
    ev_id = (await client.get(f"{BASE}/evidence")).json()[0]["id"]
    await client.post(f"{BASE}/evidence/{ev_id}/extract")

    async def mock_verify(assertions, material):
        return tasks.VerifyOut(results=[
            {"id": "A1", "ok": False, "corrected_text": "指数退避重试（base 30s）", "reason": "代码为指数退避"},
            {"id": "A2", "ok": False, "corrected_text": None, "reason": "材料中无对应依据"},
        ])

    monkeypatch.setattr(tasks, "verify", mock_verify)
    await client.post(f"{BASE}/assertions/verify", json={})
    rows = {a["id"]: a for a in (await client.get(f"{BASE}/assertions")).json()}
    assert rows["A1"]["text"] == "指数退避重试（base 30s）"
    assert rows["A1"]["suspect"] and rows["A1"]["verified"]
    assert not rows["A2"]["verified"]


async def test_dims_get_put(client):
    ensure_root("演示项目")
    r = await client.get(f"{BASE}/dims")
    assert r.status_code == 200 and "幂等" in r.json()
    r = await client.put(f"{BASE}/dims", json={"dims": ["状态", "审计留痕"]})
    assert r.status_code == 200 and r.json() == ["状态", "审计留痕"]
    assert (await client.put(f"{BASE}/dims", json={"dims": []})).status_code == 422
    assert (await client.put(f"{BASE}/dims", json={"dims": ["状态", 1]})).status_code == 422
    assert (await client.put(f"{BASE}/dims", json={"dims": "状态"})).status_code == 422


async def test_tree_validation(client):
    ensure_root("演示项目")
    r = await client.post(f"{BASE}/tree", json={"op": "add", "name": ""})
    assert r.status_code == 422
    r = await client.post(f"{BASE}/tree", json={"op": "add", "name": "a\nb"})
    assert r.status_code == 422
    assert (await client.post(f"{BASE}/tree", json={"op": "rename", "path": "x", "name": "n"})).status_code == 422
    assert (await client.post(f"{BASE}/tree", json={"op": "del", "path": "5"})).status_code == 422
    assert (await client.post(f"{BASE}/tree", json={"op": "noop"})).status_code == 422


async def test_node_addressing_errors(client):
    ensure_root("演示项目")
    r = await client.post(f"{BASE}/cards/assemble", json={"node_path": "7", "note": ""})
    assert r.status_code == 404
    r = await client.post(f"{BASE}/cards/assemble", json={"node_path": "a,b", "note": ""})
    assert r.status_code == 422
    assert (await client.get(f"{BASE}/cards/9")).status_code == 404
    assert (await client.get(f"{BASE}/cards/x")).status_code == 422


async def test_baseline_without_changes(client):
    ensure_root("演示项目")
    await client.post(f"{BASE}/evidence", json={"raw": "x"})
    b1 = (await client.post(f"{BASE}/baseline", json={"note": "一"})).json()
    b2 = (await client.post(f"{BASE}/baseline", json={"note": "二"})).json()
    assert b2["tag"] == "v2" and b2["v"] == 2 and b2["commit"] == b1["commit"]  # 无变更跳过 commit
    tags = (await client.get(f"{BASE}/baseline")).json()
    assert [t["tag"] for t in tags] == ["v1", "v2"]


async def test_ai_error_maps_to_502(client, monkeypatch):
    ensure_root("演示项目")
    async def boom(*args, **kwargs):
        raise AITaskError("extract", "输出校验失败")

    monkeypatch.setattr(tasks, "extract", boom)
    await client.post(f"{BASE}/evidence", json={"raw": "材料"})
    ev_id = (await client.get(f"{BASE}/evidence")).json()[0]["id"]
    r = await client.post(f"{BASE}/evidence/{ev_id}/extract")
    assert r.status_code == 502


async def test_binary_evidence_extract_rejected(client):
    ensure_root("演示项目")
    # 截图/压缩包不做 AI 提取，M1.x 才支持解析
    for fname in ("shot.png", "bundle.zip"):
        r = await client.post(f"{BASE}/evidence", content=b"\x89PNG",
                              headers={"content-type": "application/octet-stream", "x-filename": fname})
        ev_id = r.json()["id"]
        r = await client.post(f"{BASE}/evidence/{ev_id}/extract")
        assert r.status_code == 422
        assert "不支持 AI 提取" in r.json()["detail"]


async def test_assemble_excludes_voided_assertions(client, monkeypatch):
    # 裁决 C1 信 A2 后，A3 为作废断言，不得进入组装入参
    from app.storage import findings as finding_store
    from app.storage import assertions as assert_store

    root = ensure_root("演示项目")
    assert_store.save(root, [
        Assertion(id="A1", text="回调超时 30s", src="retry.py:15", conf="实证", verified=True, node="放款"),
        Assertion(id="A2", text="重试上限 3 次", src="retry.py:42", conf="实证", verified=True, node="放款"),
        Assertion(id="A3", text="重试上限 5 次", src="设计文档§2", conf="文档", verified=True, node="放款"),
    ])
    finding_store.save_conflicts(root, [Conflict(id="C1", a="A2", b="A3", q="重试几次？", st="code", resolution="A2")])
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "放款"})

    seen = {}

    async def mock_assemble(assertions, node_name, note):
        seen["ids"] = [a.id for a in assertions]
        return Card(node=node_name, goal="不重复放款",
                    rules=[Rule(id="R1", text="重试上限 3 次", src="retry.py:42", conf="实证")])

    monkeypatch.setattr(tasks, "assemble", mock_assemble)
    r = await client.post(f"{BASE}/cards/assemble", json={"node_path": "0", "note": ""})
    assert r.status_code == 200
    assert "A3" not in seen["ids"] and "A2" in seen["ids"]


async def test_assemble_filters_by_node(client, monkeypatch):
    from app.storage import assertions as assert_store
    root = ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "风控"})
    assert_store.save(root, [
        Assertion(id="A1", text="重试3次", src="r.py:1", conf="实证", verified=True, node="支付/放款重试"),
        Assertion(id="A2", text="风控拦截", src="r.py:2", conf="实证", verified=True, node="风控"),
        Assertion(id="A3", text="未归类规则", src="r.py:3", conf="实证", verified=True, node=""),
    ])
    seen = {}
    async def mock_assemble(assertions, node_name, note):
        seen["ids"] = [a.id for a in assertions]
        return Card(node=node_name, goal="g")
    monkeypatch.setattr(tasks, "assemble", mock_assemble)

    r = await client.post(f"{BASE}/cards/assemble", json={"node_path": "0,0", "note": ""})
    assert r.status_code == 200 and seen["ids"] == ["A1"]  # 只吃本节点规则

    r = await client.post(f"{BASE}/cards/assemble", json={"node_path": "0", "note": ""})
    assert r.status_code == 200 and seen["ids"] == ["A1"]  # 选父节点「支付」= 包含子节点规则


async def test_assemble_no_rules_blocked(client, monkeypatch):
    # 节点无任何归属规则 → 409 阻断：空规则集只会生成空画像（上线验证证伪了「AI 产出框架」假设）
    ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    async def mock_assemble(assertions, node_name, note):
        raise AssertionError("空规则集不应进入 AI 组装")
    monkeypatch.setattr(tasks, "assemble", mock_assemble)
    r = await client.post(f"{BASE}/cards/assemble", json={"node_path": "0", "note": ""})
    assert r.status_code == 409 and "没有已挂载的规则" in r.json()["detail"]


async def test_project_name_traversal_rejected(client):
    # proj=".."（URL 编码 %2e%2e）slugify 后为空 → root 解析为文件系统根，必须 422 拒绝
    r = await client.get("/api/projects/%2e%2e/evidence")
    assert r.status_code == 422
    r = await client.post("/api/projects/%2e%2e/baseline", json={"note": "x"})
    assert r.status_code == 422
    # 混入可清洗字符的变体同样拒绝
    r = await client.get("/api/projects/%2e%2e%2e%2e/evidence")
    assert r.status_code == 422


async def test_gaps_scan_scoped_to_node(client, monkeypatch):
    from app.storage import cards as card_store
    from app.storage.cards import Card, Rule
    root = ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "风控"})
    card_store.save_card(root, "支付/放款重试", Card(node="支付/放款重试", goal="不重复放款"))
    card_store.save_card(root, "风控", Card(node="风控", goal="额度不超限"))

    seen = {}
    async def mock_gaps(summary, dims):
        seen["summary"] = summary
        return []
    monkeypatch.setattr(tasks, "gaps", mock_gaps)

    r = await client.post(f"{BASE}/gaps/rescan", params={"node_path": "0,0"})
    assert r.status_code == 200
    assert "不重复放款" in seen["summary"] and "额度不超限" not in seen["summary"]

    r = await client.post(f"{BASE}/gaps/rescan", params={"node_path": "0"})
    assert r.status_code == 200  # 选父节点「支付」：聚合子树卡片（支付自身无卡但子节点有）
    assert "不重复放款" in seen["summary"] and "额度不超限" not in seen["summary"]

    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "空模块"})
    r = await client.post(f"{BASE}/gaps/rescan", params={"node_path": "2"})
    assert r.status_code == 422 and "子树" in r.json()["detail"]

    await client.post(f"{BASE}/gaps/rescan")  # 不带参：旧行为全部卡片
    assert "额度不超限" in seen["summary"]


async def test_extract_binds_node_and_sanitizes(client, monkeypatch):
    ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
    await client.post(f"{BASE}/evidence", json={"raw": "重试材料"})

    async def mock_extract(content, evidence_type, tree_text):
        assert "支付/放款重试" in tree_text
        return [Assertion(id="E1", text="当超时重试3次", src="retry.py:15", conf="实证",
                          node="支付/放款重试"),
                Assertion(id="E2", text="当失败告警", src="log.py:3", conf="实证",
                          node="支付/编造的节点")]  # AI 编造路径
    monkeypatch.setattr(tasks, "extract", mock_extract)

    ev_id = (await client.get(f"{BASE}/evidence")).json()[0]["id"]
    r = await client.post(f"{BASE}/evidence/{ev_id}/extract")
    assert r.status_code == 200
    rows = {a["id"]: a for a in (await client.get(f"{BASE}/assertions")).json()}
    assert rows["A1"]["node"] == "支付/放款重试"
    assert rows["A2"]["node"] == ""  # 编造路径被白名单置空


async def test_legacy_assertions_without_node_load(client):
    # 存量 assertions.json 无 node 字段 → 默认 ""，不炸
    import json
    from app.storage import assertions as assert_store
    root = ensure_root("演示项目")
    (root / "assertions.json").write_text(
        json.dumps([{"id": "A1", "text": "t", "src": "s", "conf": "实证"}], ensure_ascii=False), "utf-8")
    rows = (await client.get(f"{BASE}/assertions")).json()
    assert rows[0]["node"] == ""


async def test_baseline_tag_after_deletion(client):
    import subprocess

    root = ensure_root("演示项目")
    await client.post(f"{BASE}/evidence", json={"raw": "x"})
    await client.post(f"{BASE}/baseline", json={"note": "一"})
    await client.post(f"{BASE}/baseline", json={"note": "二"})
    subprocess.run(["git", "tag", "-d", "v1"], cwd=root, check=True, capture_output=True)
    b3 = (await client.post(f"{BASE}/baseline", json={"note": "三"})).json()
    assert b3["tag"] == "v3" and b3["v"] == 3  # max+1，不与残留 v2 撞号


async def test_set_assertion_node(client):
    from app.storage import assertions as assert_store
    root = ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    assert_store.save(root, [Assertion(id="A1", text="t", src="s", conf="实证")])

    r = await client.put(f"{BASE}/assertions/A1/node", json={"node": "支付"})
    assert r.status_code == 204
    assert (await client.get(f"{BASE}/assertions")).json()[0]["node"] == "支付"

    assert (await client.put(f"{BASE}/assertions/A1/node", json={"node": "不存在"})).status_code == 422
    assert (await client.put(f"{BASE}/assertions/A1/node", json={"node": ""})).status_code == 204  # 清空回未归类
    assert (await client.put(f"{BASE}/assertions/NOPE/node", json={"node": "支付"})).status_code == 404


async def test_tree_scaffold(client, monkeypatch):
    ensure_root("演示项目")
    await client.post(f"{BASE}/evidence", json={"raw": "支付模块支持放款重试与回调处理。"})
    await client.post(f"{BASE}/evidence", content=b"\x89PNG",
                      headers={"content-type": "application/octet-stream", "x-filename": "s.png"})

    async def mock_outline(material):
        assert "放款重试" in material  # 拼接的是文本材料，截图只有文件名不入正文
        return [tasks.OutlineNode(name="支付", children=[
            tasks.OutlineNode(name="放款重试", children=[])])]
    monkeypatch.setattr(tasks, "outline", mock_outline)

    r = await client.post(f"{BASE}/tree/scaffold")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "支付"
    assert (ensure_root("演示项目") / "tree.md").exists()

    r = await client.post(f"{BASE}/tree/scaffold")  # 树已非空：拒绝覆盖
    assert r.status_code == 409


async def test_tree_scaffold_empty_pool(client):
    ensure_root("演示项目")
    r = await client.post(f"{BASE}/tree/scaffold")
    assert r.status_code == 422 and "可提取" in r.json()["detail"]


async def _wait_job_done(client, jid, timeout=5.0):
    import asyncio
    for _ in range(int(timeout / 0.05)):
        rows = (await client.get(f"{BASE}/jobs")).json()
        j = next(x for x in rows if x["id"] == jid)
        if j["status"] != "running":
            return j
        await asyncio.sleep(0.05)
    raise AssertionError("job 未在超时内完成")


async def test_assemble_batch_job_lifecycle(client, monkeypatch):
    root = ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "风控"})
    from app.storage import assertions as assert_store
    assert_store.save(root, [
        Assertion(id="A1", text="重试3次", src="r.py:1", conf="实证", verified=True, node="支付/放款重试"),
    ])

    async def mock_assemble(assertions, node_name, note):
        return Card(node=node_name, goal="g")
    monkeypatch.setattr(tasks, "assemble", mock_assemble)

    r = await client.post(f"{BASE}/cards/assemble-batch", json={"node_path": ""})
    assert r.status_code == 200
    jid, total = r.json()["job_id"], r.json()["total"]
    assert total == 2  # 叶子：支付/放款重试、风控
    j = await _wait_job_done(client, jid)
    assert j["ok"] == 1 and j["skipped"] == ["风控"]  # 风控无规则 → 409 → 跳过
    assert (root / "cards").exists()  # 支付/放款重试 画像落盘


async def test_assemble_batch_scoped_and_conflicts(client, monkeypatch):
    ensure_root("演示项目")
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "风控"})

    async def slow_assemble(assertions, node_name, note):
        import asyncio
        await asyncio.sleep(0.3)
        return Card(node=node_name, goal="g")
    monkeypatch.setattr(tasks, "assemble", slow_assemble)

    r = await client.post(f"{BASE}/cards/assemble-batch", json={"node_path": "0"})  # 支付子树：1 叶
    assert r.status_code == 200 and r.json()["total"] == 1
    r2 = await client.post(f"{BASE}/cards/assemble-batch", json={})  # 运行中重复发起 → 409
    assert r2.status_code == 409 and "进行中" in r2.json()["detail"]
    await _wait_job_done(client, r.json()["job_id"])
    # 运行中任务查询可见 running→done 流转（上面等待已覆盖），空树拒绝：
    r3 = await client.post(f"{BASE}/tree", json={"op": "del", "path": "0"})
    r4 = await client.post(f"{BASE}/tree", json={"op": "del", "path": "0"})
    r5 = await client.post(f"{BASE}/cards/assemble-batch", json={})
    assert r5.status_code == 422


async def test_jobs_requires_valid_project(client):
    ensure_root("演示项目")
    r = await client.get(f"{BASE}/jobs")
    assert r.status_code == 200 and isinstance(r.json(), list)
    assert (await client.get("/api/projects/%2e%2e/jobs")).status_code == 422
