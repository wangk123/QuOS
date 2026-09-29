# server/app/storage/jobs.py
# 后台任务登记（内存态）：批量画像等长任务的进度源，前端轮询 GET /jobs。
# 单人本地工具：同一时刻至多一个 running 任务；服务重启丢任务状态（已完成的卡片文件已落盘，不受影响）。
import time

_jobs: dict[str, dict] = {}
_seq = 0


def create(kind: str, label: str, total: int) -> str:
    global _seq
    _seq += 1
    jid = f"J{_seq}"
    _jobs[jid] = {
        "id": jid, "kind": kind, "label": label, "cur": 0, "total": total,
        "status": "running", "ok": 0, "skipped": [], "blocked": [], "failed": 0,
        "started_at": time.time(),
    }
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


def bump(jid: str, field: str, item: str | None = None) -> None:
    j = _jobs.get(jid)
    if not j:
        return
    if field == "ok" or field == "failed":
        j[field] += 1
    elif item is not None:
        j[field].append(item)


def finish(jid: str) -> None:
    update(jid, status="done", finished_at=time.time())
