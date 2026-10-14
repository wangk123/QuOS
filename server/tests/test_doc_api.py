"""基线/草案 API 测试:空态、校验闸门、覆盖语义、去重。"""
from types import SimpleNamespace

from app.models import Question
from tests.test_materials import make_pdf_bytes, _upload


def _mk_proj_with_material(client, text_quote="Hello QuOS"):
    pid = client.post("/api/v1/projects", json={"name": "P"}).json()["id"]
    m = _upload(client, pid, "m.pdf", make_pdf_bytes(text_quote)).json()
    return pid, m["id"]


def _payload(quote="Hello QuOS", material_id=1, extra_rules=None):
    rules = {"R1": {"no": "R1", "text": "规则一的内容", "violation": "违反的标准描述",
                    "quote": quote, "material_id": material_id,
                    "status": "active", "replaced_by": None}}
    rules.update(extra_rules or {})
    return {"meta": {"version": "draft", "date": "2026-10-14", "scope": "s"},
            "chapters": [{"id": "c1", "title": "接入", "pri": "P0",
                          "rule_nos": list(rules)}],
            "rules": rules}


def test_baseline_empty(client):
    pid = client.post("/api/v1/projects", json={"name": "P"}).json()["id"]
    r = client.get(f"/api/v1/projects/{pid}/doc/baseline")
    assert r.status_code == 200 and r.json() == {"empty": True}


def test_draft_empty_then_submit_and_read(client):
    pid, mid = _mk_proj_with_material(client)
    assert client.get(f"/api/v1/projects/{pid}/doc/draft").json() == {"empty": True}

    r = client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(material_id=mid))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "reviewing"
    assert "auto_questions" in body["check_report"]

    got = client.get(f"/api/v1/projects/{pid}/doc/draft").json()
    assert got["payload"]["rules"]["R1"]["no"] == "R1"


def test_hard_error_rejected_not_stored(client):
    pid, mid = _mk_proj_with_material(client)
    r = client.post(f"/api/v1/projects/{pid}/doc/draft",
                    json=_payload(quote="材料里根本不存在的引用内容", material_id=mid))
    assert r.status_code == 422
    errs = r.json()["detail"]["hard_errors"]
    assert any(e["code"] == "QUOTE_NOT_FOUND" and e["rule_no"] == "R1" for e in errs)
    assert any(e["detail"].get("nearest") for e in errs if e["code"] == "QUOTE_NOT_FOUND")
    assert client.get(f"/api/v1/projects/{pid}/doc/draft").json() == {"empty": True}


def test_missing_material_single_error_code(client):
    pid, _ = _mk_proj_with_material(client)
    r = client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(material_id=999))
    assert r.status_code == 422
    assert any(e["code"] == "MATERIAL_NOT_FOUND" for e in r.json()["detail"]["hard_errors"])


def test_auto_questions_persisted_with_anchor(client):
    pid, mid = _mk_proj_with_material(client)
    payload = _payload(material_id=mid)
    payload["new_terms"] = [{"name": "幂等键", "context": "接入章"}]
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=payload)
    qs = client.get(f"/api/v1/projects/{pid}/questions?status=pending").json()
    assert any(q["source"] == "auto" and "幂等键" in q["payload"]["q"] for q in qs)


def _insert_answered_question(db, pid: int, draft_id: int, rule_no="R1"):
    q = Question(project_id=pid, kind="fill", payload={"q": "边界?"}, anchor={},
                 status="answered", answer={"text": "60 秒"}, source="agent",
                 draft_id=draft_id)
    db.add(q)
    db.commit()
    return q.id


def test_resubmit_overrides_draft_and_withdraws_pending(client, db):
    pid, mid = _mk_proj_with_material(client)
    first = client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(material_id=mid)).json()
    _insert_answered_question(db, pid, first["draft_id"])

    # agent 一条 pending 批注(旧草案下,直插避免依赖 T6 端点)
    db.add(Question(project_id=pid, kind="fill", payload={"q": "待答问题"},
                    anchor={"chapter_id": "c1"}, status="pending", source="agent",
                    draft_id=first["draft_id"]))
    db.commit()

    # 重交覆盖
    second = client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(material_id=mid)).json()
    assert second["draft_id"] != first["draft_id"]

    qs = client.get(f"/api/v1/projects/{pid}/questions").json()
    pend = [q for q in qs if q["status"] == "pending"]
    ans = [q for q in qs if q["status"] == "answered"]
    wd = [q for q in qs if q["status"] == "withdrawn"]
    assert not pend  # 旧草案 pending 全部撤回
    assert any(q["payload"]["q"] == "待答问题" for q in wd)  # agent 提交题撤回留痕
    assert len(ans) == 1  # answered 跨草案存续


def test_auto_questions_deduped_across_resubmit(client):
    pid, mid = _mk_proj_with_material(client)
    payload = _payload(material_id=mid)
    payload["new_terms"] = [{"name": "幂等键"}]
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=payload)
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=payload)
    qs = client.get(f"/api/v1/projects/{pid}/questions").json()
    term_qs = [q for q in qs if "幂等键" in q["payload"].get("q", "")]
    assert len(term_qs) == 1  # 题型+关键内容去重


def test_versions_list_empty(client):
    pid = client.post("/api/v1/projects", json={"name": "P"}).json()["id"]
    assert client.get(f"/api/v1/projects/{pid}/doc/versions").json() == []
