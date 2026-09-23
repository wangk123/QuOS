# server/app/storage/evidence.py
import json
import uuid
from datetime import date
from pathlib import Path

from app.core.models import Evidence


def _idx(root: Path) -> Path:
    return root / "evidence" / "index.json"


def _load(root) -> list[dict]:
    p = _idx(root)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError:
        raise RuntimeError("evidence/index.json 损坏，请人工修复或删除")


def _save(root, rows):
    _idx(root).parent.mkdir(parents=True, exist_ok=True)
    _idx(root).write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")


def _ev(row: dict) -> Evidence:
    r = dict(row)
    if not r.get("path"):
        r["path"] = ""
    r.setdefault("ext", "")
    r.setdefault("stars", 2)
    r.setdefault("state", "pending")
    r.setdefault("count", 0)
    return Evidence(**r)


async def add(root, payload: dict, content: bytes | None = None) -> Evidence:
    rows = _load(root)
    row = {"id": payload.get("type", "文本")[:4].upper() + uuid.uuid4().hex[:8],
           "reg": date.today().isoformat(), "path": None, **payload}
    if content is not None:
        fdir = root / "evidence" / "files"; fdir.mkdir(parents=True, exist_ok=True)
        f = fdir / Path(payload["name"]).name; f.write_bytes(content); row["path"] = str(f.relative_to(root))
    rows.append(row); _save(root, rows)
    return _ev(row)


async def list_all(root) -> list[Evidence]:
    out = []
    for r in _load(root):
        if r.get("path"):
            r["missing"] = not (root / r["path"]).exists()
            if r["missing"]: r["stars"] = max(0, r.get("stars", 2) - 1)
        out.append(_ev(r))
    return out


async def get(root, id) -> Evidence | None:
    for r in _load(root):
        if r.get("id") == id:
            return _ev(r)
    return None


async def mark_extracted(root, id, count: int) -> None:
    rows = _load(root)
    for r in rows:
        if r.get("id") == id:
            r["state"] = "extracted"
            r["count"] = count
    _save(root, rows)
