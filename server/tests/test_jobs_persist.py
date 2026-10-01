import json

from app.storage import jobs

def test_cancel_and_persist(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_PERSIST", tmp_path / "jobs.json")
    jid = jobs.create("generate", "生成需求", 10)
    jobs.update(jid, phase="extract", current_node="0", cur=3)
    jobs.cancel(jid)
    assert jobs.is_cancelled(jid) is True
    assert (tmp_path / "jobs.json").exists()   # cancel 必已落盘
    jobs.load(tmp_path / "jobs.json")           # 模拟重启恢复
    j = jobs.get(jid)
    assert j["status"] == "cancelled" and j["phase"] == "extract" and j["cur"] == 3

def test_cancelled_is_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_PERSIST", tmp_path / "jobs.json")
    jid = jobs.create("generate", "x", 5)
    jobs.cancel(jid)
    assert jobs.running() is None               # cancelled 不占 running 位


def test_finish_does_not_overwrite_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_PERSIST", tmp_path / "jobs.json")
    jid = jobs.create("generate", "x", 5)
    jobs.cancel(jid)
    jobs.finish(jid)                             # 取消落在后台链执行窗口：链尾 finish 不得覆写
    assert jobs.get(jid)["status"] == "cancelled"

def test_load_marks_zombie_running_cancelled(tmp_path):
    p = tmp_path / "jobs.json"
    p.write_text(json.dumps([{"id": "J9", "kind": "generate", "label": "生成需求", "cur": 2, "total": 5,
                              "status": "running", "ok": 1, "skipped": [], "blocked": [], "failed": 0,
                              "started_at": 0.0, "phase": "extract", "current_node": "n1", "done_nodes": []}],
                             ensure_ascii=False), "utf-8")
    jobs.load(p)                                # 不洁退出后重启：僵尸 running 处置
    j = jobs.get("J9")
    assert j["status"] == "cancelled" and "中断" in j["label"]
    assert jobs.running() is None               # 不永久占用唯一并发位
