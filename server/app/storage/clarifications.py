# server/app/storage/clarifications.py
import json
from pathlib import Path

from app.core.models import Clarification


def _file(root) -> Path:
    return Path(root) / "clarifications.json"


def _load(root) -> list[dict]:
    p = _file(root)
    return json.loads(p.read_text("utf-8")) if p.exists() else []


def _save(root, rows: list[dict]) -> None:
    _file(root).write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")


def _find(rows: list[dict], no: int) -> dict:
    for r in rows:
        if r.get("no") == no:
            return r
    raise ValueError(f"问题不存在: {no}")


async def add(root, q: str, opts: list[str], ref: str | None = None) -> Clarification:
    rows = _load(root)
    row = {"no": max((r.get("no", 0) for r in rows), default=0) + 1,
           "q": q, "opts": list(opts), "st": "wait", "answer": None, "ref": ref}
    rows.append(row)
    _save(root, rows)
    return Clarification(**row)


async def list_all(root) -> list[Clarification]:
    return [Clarification(**r) for r in _load(root)]


async def answer(root, no: int, idx: int) -> Clarification:
    rows = _load(root)
    row = _find(rows, no)
    opts = row.get("opts", [])
    if not 0 <= idx < len(opts):
        raise ValueError(f"选项越界: {idx}")
    row["answer"] = opts[idx]
    row["st"] = "answered"
    _save(root, rows)
    return Clarification(**row)


async def verify(root, no: int) -> Clarification:
    rows = _load(root)
    row = _find(rows, no)
    row["st"] = "verified"
    _save(root, rows)
    return Clarification(**row)
