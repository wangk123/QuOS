# server/tests/test_projects_db.py
import os
import shutil

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QUOS_DB_TEST") != "1", reason="仅 QUOS_DB_TEST=1 跑真库")

from app.storage import db, project


def test_reconcile_real_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "DATA_DIR", tmp_path)
    monkeypatch.setattr(project, "ARCHIVE_DIR", tmp_path / ".archived")
    row = project.create("真库验证项目")
    extra = db.reconcile([{**row, "status": "active"}])
    assert extra.get("真库验证项目") is not None
    db.touch_opened("真库验证项目")
    extra = db.reconcile([{**row, "status": "active"}])
    assert extra["真库验证项目"]["last_opened_at"] is not None
    # 幽灵行清除（限 status 域）：目录删除后，以另一活跃行对账应删幽灵行
    shutil.rmtree(tmp_path / "真库验证项目")
    other = project.create("陪跑项目")
    db.reconcile([{**other, "status": "active"}])
    conn = db.connect()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM projects WHERE slug='真库验证项目'")
        assert cur.fetchone()[0] == 0
    conn.close()
    shutil.rmtree(tmp_path / "陪跑项目")
    db.delete_row("陪跑项目")


def test_reconcile_single_side_keeps_other_side(tmp_path, monkeypatch):
    # 单侧对账不互删另一侧：交替调用两列表后两侧 last_opened_at 均保留
    monkeypatch.setattr(project, "DATA_DIR", tmp_path)
    monkeypatch.setattr(project, "ARCHIVE_DIR", tmp_path / ".archived")
    a = project.create("活跃甲")
    b = project.create("归档乙")
    project.archive("归档乙")
    db.reconcile([{**a, "status": "active"}, {**b, "status": "archived"}])
    db.touch_opened("活跃甲")
    db.touch_opened("归档乙")
    db.reconcile([{**a, "status": "active"}])  # 模拟 GET /api/projects
    db.reconcile([{**b, "status": "archived"}])  # 模拟 GET /api/projects/archived
    conn = db.connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slug, last_opened_at IS NULL FROM projects"
            " WHERE slug IN ('活跃甲','归档乙')")
        got = dict(cur.fetchall())
    conn.close()
    assert set(got) == {"活跃甲", "归档乙"} and not any(got.values())
    shutil.rmtree(tmp_path / "活跃甲")
    shutil.rmtree(tmp_path / ".archived/归档乙")
    db.delete_row("活跃甲")
    db.delete_row("归档乙")
