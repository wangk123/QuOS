"""发版/变更记录/回退测试(Review Focus 4-6)。"""
import threading

from tests.test_materials import make_pdf_bytes, _upload


def _setup(client, quote="Hello QuOS"):
    pid = client.post("/api/v1/projects", json={"name": "P"}).json()["id"]
    m = _upload(client, pid, "overview.pdf", make_pdf_bytes(quote)).json()
    return pid, m["id"]


def _payload(material_id, r1_text="规则一的内容", extra=None):
    rules = {"R1": {"no": "R1", "text": r1_text, "violation": "违反的标准描述",
                    "quote": "Hello QuOS", "material_id": material_id,
                    "status": "active", "replaced_by": None}}
    if extra:
        rules.update(extra)
    return {"meta": {"version": "draft", "date": "2026-10-14", "scope": "s"},
            "glossary": [{"name": "幂等键", "definition": "写操作令牌"}],
            "chapters": [{"id": "c1", "title": "接入", "pri": "P0",
                          "background": "初衷文本", "rule_nos": list(rules)}],
            "rules": rules}


def _finalize(client, pid, version, note=""):
    draft = client.get(f"/api/v1/projects/{pid}/doc/draft").json()
    return client.post(f"/api/v1/projects/{pid}/doc/finalize",
                       json={"draft_id": draft["draft_id"], "version": version, "note": note})


def test_first_release_all_added_with_material_reason(client):
    pid, mid = _setup(client)
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(mid))
    r = _finalize(client, pid, "v1", "首版")
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "v1"

    rows = client.get(f"/api/v1/projects/{pid}/doc/changes?version=v1").json()
    assert len(rows) == 1 and rows[0]["kind"] == "added"
    assert rows[0]["reason"] == "overview.pdf"  # 首版 reason=材料文件名
    assert rows[0]["approver"] == "owner"

    base = client.get(f"/api/v1/projects/{pid}/doc/baseline").json()
    assert base["version"] == "v1" and base["snapshot"]["rules"]["R1"]["no"] == "R1"


def test_duplicate_version_409(client):
    pid, mid = _setup(client)
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(mid))
    _finalize(client, pid, "v1")
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(mid, "第二版文本"))
    r = _finalize(client, pid, "v1")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "DUP_VERSION"


def test_custom_version_and_modify_changelog_reason_from_answer(client):
    pid, mid = _setup(client)
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(mid))
    _finalize(client, pid, "v1")

    # 第二轮草案:修改 R1;agent 批注已答(挂旧草案)提供 reason
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(mid, "修改后的规则文本"))
    draft = client.get(f"/api/v1/projects/{pid}/doc/draft").json()
    from app.models import Question
    # 直插一条 answered 批注(rule_no=R1,挂在被覆盖前的语义上)
    # 通过 API 造:提交后作答
    qs = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "fill", "payload": {"q": "R1 为何改?"}, "anchor": {"chapter_id": "c1", "rule_no": "R1"}}]).json()
    client.post(f"/api/v1/questions/{qs[0]['id']}/answer", json={"answer": {"text": "纪要对齐"}})

    r = _finalize(client, pid, "v2.1", "自定义号")
    assert r.status_code == 200 and r.json()["version"] == "v2.1"

    rows = client.get(f"/api/v1/projects/{pid}/doc/changes?version=v2.1").json()
    mod = [c for c in rows if c["kind"] == "modified"]
    assert mod and mod[0]["old_text"] == "规则一的内容"
    assert mod[0]["new_text"] == "修改后的规则文本"
    assert mod[0]["reason"] == "纪要对齐"  # 取 answered 批注答案


def test_finalize_withdraws_auto_pending_keeps_agent_pending(client, db):
    pid, mid = _setup(client)
    # 草案带软警告(new_terms → auto pending)
    payload = _payload(mid)
    payload["new_terms"] = [{"name": "幂等键"}]
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=payload)
    qs = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "fill", "payload": {"q": "agent 的问题"}, "anchor": {}}]).json()

    _finalize(client, pid, "v1")

    allq = client.get(f"/api/v1/projects/{pid}/questions").json()
    by_q = {q["payload"].get("q"): q["status"] for q in allq}
    assert by_q["agent 的问题"] == "pending"      # agent 提交批注保留
    assert "幂等键" not in [k for k, v in by_q.items() if v == "pending"]  # auto 未答撤回
    auto = [q for q in allq if q["source"] == "auto"][0]
    assert auto["status"] == "withdrawn"


def test_finalize_draft_finalized_and_terms_rebuilt(client):
    pid, mid = _setup(client)
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(mid))
    _finalize(client, pid, "v1")
    assert client.get(f"/api/v1/projects/{pid}/doc/draft").json() == {"empty": True}

    r = client.get(f"/api/v1/projects/{pid}/doc/baseline")
    assert r.json()["snapshot"]["glossary"][0]["name"] == "幂等键"


def test_revert_switches_baseline_keeps_history(client):
    pid, mid = _setup(client)
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(mid))
    _finalize(client, pid, "v1")
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(mid, "v2 文本"))
    _finalize(client, pid, "v2")

    r = client.post(f"/api/v1/projects/{pid}/doc/revert", json={"version": "v1"})
    assert r.status_code == 200
    base = client.get(f"/api/v1/projects/{pid}/doc/baseline").json()
    assert base["version"] == "v1"
    vers = [v["version"] for v in client.get(f"/api/v1/projects/{pid}/doc/versions").json()]
    assert set(vers) == {"v1", "v2"}  # 历史不删

    # 回退后新草案与 v1 比对(与当前基线比,非最新版)
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(mid, "v3 文本"))
    _finalize(client, pid, "v3")
    rows = client.get(f"/api/v1/projects/{pid}/doc/changes?version=v3").json()
    mod = [c for c in rows if c["kind"] == "modified"]
    assert mod and mod[0]["old_text"] == "规则一的内容"  # v1 的文本


def test_changelog_rule_level_only(client):
    pid, mid = _setup(client)
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(mid))
    _finalize(client, pid, "v1")
    # 第二版只改章节背景文本(规则不动)
    payload = _payload(mid)
    payload["chapters"][0]["background"] = "全新的初衷说明"
    client.post(f"/api/v1/projects/{pid}/doc/draft", json=payload)
    _finalize(client, pid, "v2")
    rows = client.get(f"/api/v1/projects/{pid}/doc/changes?version=v2").json()
    assert rows == []  # 章节文本变更不进 ChangeLog


def test_concurrent_draft_single_reviewing(client):
    pid, mid = _setup(client)
    results = []

    def submit(tag: str):
        r = client.post(f"/api/v1/projects/{pid}/doc/draft",
                        json=_payload(mid, f"并发草案 {tag}"))
        results.append(r.status_code)

    ts = [threading.Thread(target=submit, args=(t,)) for t in ("A", "B")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(code in (200, 422, 409) for code in results)
    # 不变量:并发后要么恰有一个 reviewing,要么空(全失败)——不得出现两个
    drafts = client.get(f"/api/v1/projects/{pid}/doc/draft").json()
    assert drafts.get("empty") is True or drafts.get("status") == "reviewing"


def test_finalize_missing_draft_404(client):
    pid, _ = _setup(client)
    r = client.post(f"/api/v1/projects/{pid}/doc/finalize",
                    json={"draft_id": 999, "version": "v1", "note": ""})
    assert r.status_code == 404


# ── 终审修复:C1 并发不变量(文件库+双连接,直查 DB) ──
def test_concurrent_draft_exactly_one_reviewing(client_factory):
    pid = client_factory.client.post("/api/v1/projects", json={"name": "P"}).json()["id"]
    from tests.test_materials import make_pdf_bytes, _upload
    mid = _upload(client_factory.client, pid, "m.pdf", make_pdf_bytes()).json()["id"]
    import threading
    codes = []
    def submit(tag):
        r = client_factory.client.post(f"/api/v1/projects/{pid}/doc/draft",
                                       json=_payload(material_id=mid, r1_text=f"并发 {tag}"))
        codes.append(r.status_code)
    ts = [threading.Thread(target=submit, args=(t,)) for t in ("A", "B")]
    for t in ts: t.start()
    for t in ts: t.join()
    assert sorted(codes) == [200, 409]  # 恰一个成功,一个被唯一索引拒
    with client_factory.session() as s:
        from app.models import DocDraft
        from sqlmodel import select as sel
        n = len(s.exec(sel(DocDraft).where(DocDraft.project_id == pid, DocDraft.status == "reviewing")).all())
    assert n == 1


def test_concurrent_finalize_same_version_409_not_500(client_factory):
    c = client_factory.client
    pid = c.post("/api/v1/projects", json={"name": "P"}).json()["id"]
    from tests.test_materials import make_pdf_bytes, _upload
    mid = _upload(c, pid, "m.pdf", make_pdf_bytes()).json()["id"]
    c.post(f"/api/v1/projects/{pid}/doc/draft", json=_payload(material_id=mid))
    import threading
    codes = []
    did = c.get(f"/api/v1/projects/{pid}/doc/draft").json()["draft_id"]

    def fin():
        fc = client_factory.make_client()  # 独立 client,真实双入口
        r = fc.post(f"/api/v1/projects/{pid}/doc/finalize",
                    json={"draft_id": did, "version": "v1", "note": ""})
        codes.append(r.status_code)
    ts = [threading.Thread(target=fin) for _ in range(2)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert 500 not in codes
    assert sorted(codes) == [200, 409]
