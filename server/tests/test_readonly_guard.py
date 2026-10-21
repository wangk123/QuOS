"""只读写守卫:非 in_progress 项目拒收全部写操作(治理动作与读不拦)。"""
from app.models import DocDraft, Project, Question


def _pid(client, name="守卫"):
    return client.post("/api/v1/projects", json={"name": name}).json()["id"]


def _set_status(db, pid, status):
    p = db.get(Project, pid)
    p.status = status
    db.add(p)
    db.commit()


def _seed_draft_q(db, pid):
    d = DocDraft(project_id=pid, payload={}, status="reviewing")
    db.add(d)
    db.commit()
    db.refresh(d)
    q = Question(project_id=pid, kind="confirm", payload={"q": "x"}, anchor={},
                 source="auto", draft_id=d.id)
    db.add(q)
    db.commit()
    db.refresh(q)
    return d, q


def _guard(r):
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "PROJECT_READ_ONLY"


def test_write_on_missing_project_404(client):
    assert client.post("/api/v1/projects/9999/doc/draft", json={}).status_code == 404
    assert client.post(
        "/api/v1/projects/9999/doc/finalize",
        json={"draft_id": 1, "version": "1.0.0", "note": ""},
    ).status_code == 404


def test_paused_blocks_every_write_endpoint(client, db):
    pid = _pid(client)
    d, q = _seed_draft_q(db, pid)
    up = client.post(  # 进行中:上传放行,并留 mid 供删除端点
        f"/api/v1/projects/{pid}/materials",
        files={"file": ("a.txt", "正文内容".encode(), "text/plain")})
    assert up.status_code == 200
    mid = up.json()["id"]
    ans = client.post(f"/api/v1/questions/{q.id}/answer", json={"answer": {"text": "ok"}})
    assert ans.status_code == 200  # 进行中:作答放行
    _set_status(db, pid, "paused")

    _guard(client.post(  # ① 材料上传
        f"/api/v1/projects/{pid}/materials",
        files={"file": ("b.txt", "x".encode(), "text/plain")}))
    _guard(client.delete(f"/api/v1/projects/{pid}/materials/{mid}"))  # ② 材料删除
    _guard(client.post(f"/api/v1/projects/{pid}/doc/draft", json={}))  # ③ 草案提交
    _guard(client.post(  # ④ md 导入
        f"/api/v1/projects/{pid}/doc/draft/import",
        files={"md": ("a.md", "# 标题".encode(), "text/markdown")}))
    _guard(client.post(f"/api/v1/projects/{pid}/questions", json=[]))  # ⑤ 批注批量提交
    _guard(client.post(  # ⑥ 人作答(经批注反查 pid)
        f"/api/v1/questions/{q.id}/answer", json={"answer": {"text": "again"}}))
    _guard(client.post(  # ⑦ 定稿
        f"/api/v1/projects/{pid}/doc/finalize",
        json={"draft_id": d.id, "version": "1.0.0", "note": ""}))
    _guard(client.post(  # ⑧ 回退
        f"/api/v1/projects/{pid}/doc/revert", json={"version": "1.0.0"}))

    # 读与治理动作不拦
    assert client.get(f"/api/v1/projects/{pid}/doc/draft").status_code == 200
    assert client.get(f"/api/v1/projects/{pid}/doc/baseline").status_code == 200
    assert client.delete(f"/api/v1/projects/{pid}").status_code == 200


def test_closed_blocks_write_too(client, db):
    pid = _pid(client, "结项")
    _set_status(db, pid, "closed")
    _guard(client.post(f"/api/v1/projects/{pid}/doc/draft", json={}))
