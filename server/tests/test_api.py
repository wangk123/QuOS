# server/tests/test_api.py
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai import tasks
from app.ai.runner import AITaskError
from app.core.models import Assertion, Conflict, Gap
from app.main import app
from app.storage.cards import Card, Rule
from app.storage.project import project_root

BASE = "/api/projects/演示项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_end_to_end(client, monkeypatch):
    root = project_root("演示项目")

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
    async def mock_extract(content, evidence_type):
        assert "重试" in content and evidence_type == "文本"
        return [Assertion(id="E1", text="当请求超时，客户端应重试3次", src="retry.py:15", conf="实证"),
                Assertion(id="E2", text="当余额不足，系统应拒绝放款", src="loan.py:30", conf="文档")]

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
    r = await client.post(f"{BASE}/evidence", content=b"%PDF-1.4",
                          headers={"content-type": "application/octet-stream", "x-filename": "spec v1.pdf"})
    assert r.status_code == 200
    assert r.json()["type"] == "文档" and r.json()["name"] == "spec v1.pdf"


async def test_evidence_filename_urlencoded(client):
    # 前端 encodeURIComponent 后传入，入库应还原原文（中文/空格不落 %XX）
    from urllib.parse import quote
    r = await client.post(f"{BASE}/evidence", content=b"PK\x03\x04",
                          headers={"content-type": "application/octet-stream",
                                   "x-filename": quote("需求 文档.docx")})
    assert r.status_code == 200
    assert r.json()["name"] == "需求 文档.docx"


async def test_evidence_invalid_input(client):
    assert (await client.post(f"{BASE}/evidence", json={"raw": ""})).status_code == 422
    assert (await client.post(f"{BASE}/evidence", content=b"")).status_code == 422
    r = await client.post(f"{BASE}/evidence/NOPE/extract")
    assert r.status_code == 404


async def test_verify_correction_written_back(client, monkeypatch):
    await client.post(f"{BASE}/evidence", json={"raw": "材料内容"})

    async def mock_extract(content, evidence_type):
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
    r = await client.get(f"{BASE}/dims")
    assert r.status_code == 200 and "幂等" in r.json()
    r = await client.put(f"{BASE}/dims", json={"dims": ["状态", "审计留痕"]})
    assert r.status_code == 200 and r.json() == ["状态", "审计留痕"]
    assert (await client.put(f"{BASE}/dims", json={"dims": []})).status_code == 422
    assert (await client.put(f"{BASE}/dims", json={"dims": ["状态", 1]})).status_code == 422
    assert (await client.put(f"{BASE}/dims", json={"dims": "状态"})).status_code == 422


async def test_tree_validation(client):
    r = await client.post(f"{BASE}/tree", json={"op": "add", "name": ""})
    assert r.status_code == 422
    r = await client.post(f"{BASE}/tree", json={"op": "add", "name": "a\nb"})
    assert r.status_code == 422
    assert (await client.post(f"{BASE}/tree", json={"op": "rename", "path": "x", "name": "n"})).status_code == 422
    assert (await client.post(f"{BASE}/tree", json={"op": "del", "path": "5"})).status_code == 422
    assert (await client.post(f"{BASE}/tree", json={"op": "noop"})).status_code == 422


async def test_node_addressing_errors(client):
    r = await client.post(f"{BASE}/cards/assemble", json={"node_path": "7", "note": ""})
    assert r.status_code == 404
    r = await client.post(f"{BASE}/cards/assemble", json={"node_path": "a,b", "note": ""})
    assert r.status_code == 422
    assert (await client.get(f"{BASE}/cards/9")).status_code == 404
    assert (await client.get(f"{BASE}/cards/x")).status_code == 422


async def test_baseline_without_changes(client):
    await client.post(f"{BASE}/evidence", json={"raw": "x"})
    b1 = (await client.post(f"{BASE}/baseline", json={"note": "一"})).json()
    b2 = (await client.post(f"{BASE}/baseline", json={"note": "二"})).json()
    assert b2["tag"] == "v2" and b2["v"] == 2 and b2["commit"] == b1["commit"]  # 无变更跳过 commit
    tags = (await client.get(f"{BASE}/baseline")).json()
    assert [t["tag"] for t in tags] == ["v1", "v2"]


async def test_ai_error_maps_to_502(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise AITaskError("extract", "输出校验失败")

    monkeypatch.setattr(tasks, "extract", boom)
    await client.post(f"{BASE}/evidence", json={"raw": "材料"})
    ev_id = (await client.get(f"{BASE}/evidence")).json()[0]["id"]
    r = await client.post(f"{BASE}/evidence/{ev_id}/extract")
    assert r.status_code == 502


async def test_project_name_traversal_rejected(client):
    # proj=".."（URL 编码 %2e%2e）slugify 后为空 → root 解析为文件系统根，必须 422 拒绝
    r = await client.get("/api/projects/%2e%2e/evidence")
    assert r.status_code == 422
    r = await client.post("/api/projects/%2e%2e/baseline", json={"note": "x"})
    assert r.status_code == 422
    # 混入可清洗字符的变体同样拒绝
    r = await client.get("/api/projects/%2e%2e%2e%2e/evidence")
    assert r.status_code == 422


async def test_baseline_tag_after_deletion(client):
    import subprocess

    await client.post(f"{BASE}/evidence", json={"raw": "x"})
    await client.post(f"{BASE}/baseline", json={"note": "一"})
    await client.post(f"{BASE}/baseline", json={"note": "二"})
    root = project_root("演示项目")
    subprocess.run(["git", "tag", "-d", "v1"], cwd=root, check=True, capture_output=True)
    b3 = (await client.post(f"{BASE}/baseline", json={"note": "三"})).json()
    assert b3["tag"] == "v3" and b3["v"] == 3  # max+1，不与残留 v2 撞号
