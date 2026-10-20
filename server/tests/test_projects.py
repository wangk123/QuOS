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
    assert stats == {"materials": 0, "pending_annos": 0, "version": None, "draft_status": None}


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
