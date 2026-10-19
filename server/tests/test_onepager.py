"""需求一页纸伴生契约测试:携带/覆盖清空/finalize 复制/baseline 带出/超长拒收。"""
from tests.test_materials import make_pdf_bytes, _upload

OP = "# X · 需求一页纸\n\n> draft-v1 · 2026-10-15 · 待裁 1 题\n"

MD = """# 测试文档

## 1 背景与目标

测试背景。

## 2 接入

- R1 规则一的内容。
"""


def _setup(client, quote="Hello QuOS"):
    pid = client.post("/api/v1/projects", json={"name": "P"}).json()["id"]
    mid = _upload(client, pid, "m.pdf", make_pdf_bytes(quote)).json()["id"]
    return pid, mid


def _payload(material_id):
    rules = {"R1": {"no": "R1", "text": "规则一的内容", "violation": "违反的标准描述",
                    "quote": "Hello QuOS", "material_id": material_id,
                    "status": "active", "replaced_by": None}}
    return {"meta": {"version": "draft", "date": "2026-10-14", "scope": "s"},
            "chapters": [{"id": "c1", "title": "接入", "pri": "P0", "rule_nos": ["R1"]}],
            "rules": rules}


def test_import_with_one_pager_and_read_back(client):
    pid, _ = _setup(client)
    r = client.post(f"/api/v1/projects/{pid}/doc/draft/import", data={"one_pager_md": OP},
                    files=[("md", ("doc.md", MD.encode(), "text/markdown"))])
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/projects/{pid}/doc/draft").json()
    assert got["one_pager_md"] == OP


def test_reimport_without_one_pager_clears(client):
    pid, _ = _setup(client)
    client.post(f"/api/v1/projects/{pid}/doc/draft/import", data={"one_pager_md": OP},
                    files=[("md", ("doc.md", MD.encode(), "text/markdown"))])
    r = client.post(f"/api/v1/projects/{pid}/doc/draft/import", files=[("md", ("doc.md", MD.encode(), "text/markdown"))])
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/projects/{pid}/doc/draft").json()
    assert got["one_pager_md"] is None  # 覆盖语义:不带=清空,防陈旧画像


def test_submit_draft_with_one_pager(client):
    pid, mid = _setup(client)
    body = _payload(mid)
    body["one_pager_md"] = OP
    r = client.post(f"/api/v1/projects/{pid}/doc/draft", json=body)
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/projects/{pid}/doc/draft").json()
    assert got["one_pager_md"] == OP


def test_finalize_copies_one_pager_to_version(client):
    pid, mid = _setup(client)
    client.post(f"/api/v1/projects/{pid}/doc/draft/import", data={"one_pager_md": OP},
                    files=[("md", ("doc.md", MD.encode(), "text/markdown"))])
    draft = client.get(f"/api/v1/projects/{pid}/doc/draft").json()
    r = client.post(f"/api/v1/projects/{pid}/doc/finalize",
                    json={"draft_id": draft["draft_id"], "version": "v1", "note": ""})
    assert r.status_code == 200, r.text
    base = client.get(f"/api/v1/projects/{pid}/doc/baseline").json()
    assert base["empty"] is False and base["one_pager_md"] == OP  # 定稿后入口不消失


def test_oversized_one_pager_rejected(client):
    pid, mid = _setup(client)
    body = _payload(mid)
    body["one_pager_md"] = "x" * 65537
    r = client.post(f"/api/v1/projects/{pid}/doc/draft", json=body)
    assert r.status_code == 422
    assert any(e["code"] == "ONE_PAGER_TOO_LARGE" for e in r.json()["detail"]["hard_errors"])
    got = client.get(f"/api/v1/projects/{pid}/doc/draft").json()
    assert got.get("empty", False) is True or got.get("one_pager_md") is None  # 草案未入库


def test_one_pager_wrong_type_rejected(client):
    pid, mid = _setup(client)
    body = _payload(mid)
    body["one_pager_md"] = 123  # 非字符串:类型闸,不是 500
    r = client.post(f"/api/v1/projects/{pid}/doc/draft", json=body)
    assert r.status_code == 422
    assert any(e["code"] == "ONE_PAGER_TOO_LARGE" for e in r.json()["detail"]["hard_errors"])
