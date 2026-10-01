# server/app/storage/jobs.py
# 后台任务登记：批量画像等长任务的进度源，前端轮询 GET /jobs。
# 单人本地工具：同一时刻至多一个 running 任务；状态落盘 server/data/.jobs.json，重启可恢复（cancelled 不占并发位）。
import json
import time
from pathlib import Path

_jobs: dict[str, dict] = {}
_seq = 0
_PERSIST: Path | None = None  # 由 main.py 启动时指向 server/data/.jobs.json（jobs 为全局态，与项目解耦）
_SERIAL = ("id", "kind", "label", "cur", "total", "status", "ok", "skipped", "blocked",
           "failed", "started_at", "phase", "current_node", "done_nodes")


def _save() -> None:
    if not _PERSIST:
        return
    rows = [{k: j[k] for k in _SERIAL if k in j} for j in _jobs.values()]
    _PERSIST.write_text(json.dumps(rows, ensure_ascii=False), "utf-8")


def load(p: Path) -> None:
    global _PERSIST, _seq
    _PERSIST = p
    if not p.exists():
        return
    for row in json.loads(p.read_text("utf-8")):
        row.setdefault("skipped", []); row.setdefault("blocked", []); row.setdefault("done_nodes", [])
        if row["status"] == "running":  # 不洁退出残留：置 cancelled 并标记，避免永久占用唯一并发位
            row["status"] = "cancelled"
            row["label"] += "（中断）"
        _jobs[row["id"]] = row
        num = str(row["id"])[1:]
        if str(row["id"]).startswith("J") and num.isdigit():
            _seq = max(_seq, int(num))  # 防重启后新建 job 撞已恢复的 ID


def create(kind: str, label: str, total: int) -> str:
    global _seq
    _seq += 1
    jid = f"J{_seq}"
    _jobs[jid] = {
        "id": jid, "kind": kind, "label": label, "cur": 0, "total": total,
        "status": "running", "ok": 0, "skipped": [], "blocked": [], "failed": 0,
        "started_at": time.time(), "phase": "", "current_node": "", "done_nodes": [],
    }
    _save()
    return jid


def get(jid: str) -> dict | None:
    return _jobs.get(jid)


def list_all() -> list[dict]:
    return list(_jobs.values())


def running() -> dict | None:
    return next((j for j in _jobs.values() if j["status"] == "running"), None)


def update(jid: str, **fields) -> None:
    j = _jobs.get(jid)
    if j:
        j.update(fields)
        _save()


def bump(jid: str, field: str, item: str | None = None) -> None:
    j = _jobs.get(jid)
    if not j:
        return
    if field == "ok" or field == "failed":
        j[field] += 1
    elif item is not None:
        j[field].append(item)
    _save()


def finish(jid: str) -> None:
    if _jobs.get(jid, {}).get("status") == "cancelled":
        return  # cancelled 是终态：后台链收尾的 finish 不得覆写（取消落在链执行窗口内）
    update(jid, status="done", finished_at=time.time())
    _save()


def cancel(jid: str) -> None:
    if jid in _jobs and _jobs[jid]["status"] == "running":
        _jobs[jid]["status"] = "cancelled"
        _save()


def is_cancelled(jid: str) -> bool:
    j = _jobs.get(jid)
    return bool(j and j["status"] == "cancelled")
