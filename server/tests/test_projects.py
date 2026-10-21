"""项目 API 测试:CRUD、删除级联、总览。"""
from sqlmodel import select

from app.models import Baseline, ChangeLog, DocDraft, DocVersion, Material, Question, Rule, Term

CHILD_TABLES = [Material, DocDraft, DocVersion, Baseline, ChangeLog, Question, Rule, Term]


def test_create_project_requires_name(client):
    r = client.post("/api/v1/projects", json={"name": ""})
    assert r.status_code == 422


def test_create_and_patch(client):
    r = client.post("/api/v1/projects", json={"name": "多模态", "description": "解析域"})
    assert r.status_code == 200
    pid = r.json()["id"]
    assert r.json()["name"] == "多模态"

    r = client.patch(f"/api/v1/projects/{pid}", json={"name": "多模态v2", "description": "更新"})
    assert r.status_code == 200 and r.json()["name"] == "多模态v2"


def test_list_returns_all_without_archived_field(client):
    client.post("/api/v1/projects", json={"name": "A"})
    items = client.get("/api/v1/projects").json()
    assert len(items) == 1 and "archived" not in items[0]


def test_archive_endpoints_removed(client):
    pid = client.post("/api/v1/projects", json={"name": "X"}).json()["id"]
    assert client.post(f"/api/v1/projects/{pid}/archive").status_code == 404
    assert client.post(f"/api/v1/projects/{pid}/restore").status_code == 404


def test_empty_project_stats(client):
    r = client.post("/api/v1/projects", json={"name": "空"}).json()
    pid = r["id"]
    stats = client.get(f"/api/v1/projects/{pid}").json()["stats"]
    assert stats == {"materials": 0, "pending_annos": 0, "version": None,
                     "draft_status": None, "requirement_status": "idle"}


def test_404_on_missing_project(client):
    assert client.get("/api/v1/projects/9999").status_code == 404


def _enable_fk(engine):
    """生产库 foreign_keys=ON,测试引擎默认 OFF:显式开启,让删表顺序错误在测试中暴露。"""
    raw = engine.raw_connection()
    raw.cursor().execute("PRAGMA foreign_keys=ON")
    raw.close()


def _seed_tree(db, tmp_path, pid):
    draft = DocDraft(project_id=pid, payload={}, status="finalized")
    db.add(draft)
    db.commit()
    db.refresh(draft)
    mat_dir = tmp_path / str(pid) / "materials"
    mat_dir.mkdir(parents=True)
    (mat_dir / "a.md").write_text("# a")
    db.add_all([
        DocVersion(project_id=pid, version="v1", snapshot={}, draft_id=draft.id),
        Baseline(project_id=pid, version="v1"),
        ChangeLog(project_id=pid, version="v1", rule_no="R1", kind="added"),
        Question(project_id=pid, kind="confirm", payload={}, anchor={}),
        Rule(project_id=pid, no="R1", text="t"),
        Term(project_id=pid, name="术语"),
        Material(project_id=pid, filename="a.md", path=str(mat_dir / "a.md"), sha256="x"),
    ])
    db.commit()


def test_delete_project_cascades(client, db, engine, tmp_path):
    _enable_fk(engine)
    pid = client.post("/api/v1/projects", json={"name": "D"}).json()["id"]
    _seed_tree(db, tmp_path, pid)

    r = client.delete(f"/api/v1/projects/{pid}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get(f"/api/v1/projects/{pid}").status_code == 404
    for T in CHILD_TABLES:
        assert db.exec(select(T).where(T.project_id == pid)).all() == []
    assert not (tmp_path / str(pid)).exists()


def test_delete_project_without_files_ok(client, tmp_path):
    pid = client.post("/api/v1/projects", json={"name": "空"}).json()["id"]
    assert not (tmp_path / str(pid)).exists()
    assert client.delete(f"/api/v1/projects/{pid}").status_code == 200


def test_delete_twice_second_404(client):
    pid = client.post("/api/v1/projects", json={"name": "T"}).json()["id"]
    assert client.delete(f"/api/v1/projects/{pid}").status_code == 200
    assert client.delete(f"/api/v1/projects/{pid}").status_code == 404


def test_delete_missing_project_404(client):
    assert client.delete("/api/v1/projects/9999").status_code == 404


# ── 需求状态五态派生(derive_requirement_status) ──
def _mk_draft(db, pid, status="reviewing"):
    d = DocDraft(project_id=pid, payload={}, status=status)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _mk_q(db, pid, draft_id, status):
    q = Question(project_id=pid, kind="confirm", payload={"q": "x"}, anchor={},
                 status=status, source="auto", draft_id=draft_id)
    db.add(q)
    db.commit()
    return q


def test_stats_requirement_status_lifecycle(client, db):
    pid = client.post("/api/v1/projects", json={"name": "状态流转"}).json()["id"]

    def st():
        return client.get(f"/api/v1/projects/{pid}").json()["stats"]["requirement_status"]

    assert st() == "idle"  # 无草案无基线
    d1 = _mk_draft(db, pid)
    q = _mk_q(db, pid, d1.id, "pending")
    assert st() == "in_review"  # 有 pending 批注
    q.status = "answered"
    db.add(q)
    db.commit()
    assert st() == "await_resubmit"  # 全答完,答案待 agent 消费
    d1.status = "superseded"  # agent 重交:先置 superseded(部分唯一索引约束同真实覆盖顺序)
    db.add(d1)
    db.commit()
    d2 = _mk_draft(db, pid)  # 旧 answered(draft_id=d1)不计入新草案口径
    assert st() == "await_finalize"  # 新草案零批注零新答
    d2.status = "finalized"
    db.add(d2)
    db.add(Baseline(project_id=pid, version="1.0.0"))
    db.commit()
    assert st() == "finalized"  # 无草案有基线


def test_proj_out_carries_project_status_and_version(client):
    r = client.post("/api/v1/projects", json={"name": "治理"}).json()
    assert r["status"] == "in_progress"
    assert r["version"] == "1.0.0"


# ── 名称唯一 + PATCH 扩展(status/version) ──
def _code(r):
    return r.json()["detail"]["code"]


def test_create_duplicate_name_blocked(client):
    client.post("/api/v1/projects", json={"name": "多模态"})
    r = client.post("/api/v1/projects", json={"name": " 多模态 "})  # trim 后同名
    assert r.status_code == 409 and _code(r) == "DUP_NAME"


def test_patch_duplicate_name_blocked_except_self(client):
    pid = client.post("/api/v1/projects", json={"name": "A"}).json()["id"]
    client.post("/api/v1/projects", json={"name": "B"})
    r = client.patch(f"/api/v1/projects/{pid}", json={"name": "B"})
    assert r.status_code == 409 and _code(r) == "DUP_NAME"
    r = client.patch(f"/api/v1/projects/{pid}", json={"name": "A"})  # 不改自身名
    assert r.status_code == 200


def test_patch_version_format(client):
    pid = client.post("/api/v1/projects", json={"name": "版本"}).json()["id"]
    for bad in ("1.2", "v1.2.0", "1.2.3.4", "1.2.x"):
        r = client.patch(f"/api/v1/projects/{pid}", json={"version": bad})
        assert r.status_code == 422 and _code(r) == "VERSION_FORMAT", bad
    r = client.patch(f"/api/v1/projects/{pid}", json={"version": "1.2.3"})
    assert r.status_code == 200 and r.json()["version"] == "1.2.3"


def test_patch_status_transitions(client):
    pid = client.post("/api/v1/projects", json={"name": "状态"}).json()["id"]
    r = client.patch(f"/api/v1/projects/{pid}", json={"status": "paused"})
    assert r.status_code == 200 and r.json()["status"] == "paused"
    r = client.patch(f"/api/v1/projects/{pid}", json={"status": "closed"})
    assert r.status_code == 200
    r = client.patch(f"/api/v1/projects/{pid}", json={"status": "paused"})  # closed→paused 非法
    assert r.status_code == 409 and _code(r) == "INVALID_STATUS_TRANSITION"
    r = client.patch(f"/api/v1/projects/{pid}", json={"status": "in_progress"})  # 重开
    assert r.status_code == 200
    r = client.patch(f"/api/v1/projects/{pid}", json={"status": "hmm"})
    assert r.status_code == 422


def test_paused_patch_governance_ok_content_blocked(client, db):
    pid = client.post("/api/v1/projects", json={"name": "治理"}).json()["id"]
    from sqlalchemy import update
    from app.models import Project as M

    def _set(status):  # update 语句直写:session 缓存的脏对象赋同值不触发 UPDATE
        db.execute(update(M).where(M.id == pid).values(status=status))
        db.commit()

    _set("paused")
    r = client.patch(f"/api/v1/projects/{pid}", json={"status": "in_progress"})  # 只读态可切状态
    assert r.status_code == 200
    _set("paused")
    r = client.patch(f"/api/v1/projects/{pid}", json={"description": "x"})  # 只读态拦内容修改
    assert r.status_code == 409 and _code(r) == "PROJECT_READ_ONLY"


def test_patch_combined_governance_and_content(client, db):
    """组合请求(前端编辑弹窗真实形态):治理+内容同批;守卫以进入时状态为准,不被本请求的 status 赋值毒化。"""
    pid = client.post("/api/v1/projects", json={"name": "组合"}).json()["id"]
    r = client.patch(f"/api/v1/projects/{pid}", json={"status": "paused", "name": "组合改名", "version": "1.1.0"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paused" and r.json()["name"] == "组合改名"
    r = client.patch(f"/api/v1/projects/{pid}", json={"status": "in_progress", "description": "恢复并改描述"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    assert r.json()["description"] == "恢复并改描述"
    # 只读态纯内容修改仍被拦(进入时状态)
    from sqlalchemy import update as _upd
    from app.models import Project as M
    db.execute(_upd(M).where(M.id == pid).values(status="paused"))
    db.commit()
    r = client.patch(f"/api/v1/projects/{pid}", json={"description": "又改"})
    assert r.status_code == 409 and _code(r) == "PROJECT_READ_ONLY"
