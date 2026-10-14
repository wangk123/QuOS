"""项目 API 测试:CRUD、归档恢复、总览。"""


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


def test_archive_hides_from_default_and_restore(client):
    pid = client.post("/api/v1/projects", json={"name": "X"}).json()["id"]
    assert client.post(f"/api/v1/projects/{pid}/archive").status_code == 200

    names = [p["name"] for p in client.get("/api/v1/projects").json()]
    assert "X" not in names
    names_archived = [p["name"] for p in client.get("/api/v1/projects?archived=1").json()]
    assert "X" in names_archived

    assert client.post(f"/api/v1/projects/{pid}/restore").status_code == 200
    names = [p["name"] for p in client.get("/api/v1/projects").json()]
    assert "X" in names


def test_empty_project_stats(client):
    r = client.post("/api/v1/projects", json={"name": "空"}).json()
    pid = r["id"]
    stats = client.get(f"/api/v1/projects/{pid}").json()["stats"]
    assert stats == {"materials": 0, "pending_annos": 0, "version": None, "draft_status": None}


def test_404_on_missing_project(client):
    assert client.get("/api/v1/projects/9999").status_code == 404
