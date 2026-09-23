# server/app/storage/findings.py
import json
from pathlib import Path

from app.core.models import Conflict, Gap


def _file(root, kind: str) -> Path:
    return Path(root) / f"{kind}.json"


def _load(root, kind: str, model) -> list:
    p = _file(root, kind)
    if not p.exists():
        return []
    try:
        return [model(**r) for r in json.loads(p.read_text("utf-8"))]
    except json.JSONDecodeError:
        raise RuntimeError(f"{kind}.json 损坏，请人工修复或删除")


def _save(root, kind: str, items: list) -> None:
    _file(root, kind).parent.mkdir(parents=True, exist_ok=True)
    _file(root, kind).write_text(json.dumps([i.model_dump() for i in items], ensure_ascii=False, indent=1), "utf-8")


def load_conflicts(root) -> list[Conflict]:
    return _load(root, "conflicts", Conflict)


def save_conflicts(root, items: list[Conflict]) -> None:
    _save(root, "conflicts", items)


def load_gaps(root) -> list[Gap]:
    return _load(root, "gaps", Gap)


def save_gaps(root, items: list[Gap]) -> None:
    _save(root, "gaps", items)


def merge_conflicts(root, detected: list[Conflict]) -> list[Conflict]:
    """重扫合并：按无序断言对去重（防重扫 id 漂移丢新冲突），已知对保留裁决状态，已消失不删除"""
    items = load_conflicts(root)
    seen = {frozenset((c.a, c.b)) for c in items}
    for d in detected:
        key = frozenset((d.a, d.b))
        if key not in seen:
            seen.add(key)
            items.append(d)
    save_conflicts(root, items)
    return items


def merge_gaps(root, detected: list[Gap]) -> list[Gap]:
    items = load_gaps(root)
    seen = {(g.dim, g.text) for g in items}
    for d in detected:
        if (d.dim, d.text) not in seen:
            seen.add((d.dim, d.text))
            items.append(d)
    save_gaps(root, items)
    return items
