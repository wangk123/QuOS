# server/app/storage/findings.py
import json
from pathlib import Path

from app.core.models import Conflict, Gap


def _file(root, kind: str) -> Path:
    return Path(root) / f"{kind}.json"


def _load(root, kind: str, model) -> list:
    p = _file(root, kind)
    return [model(**r) for r in json.loads(p.read_text("utf-8"))] if p.exists() else []


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
    """重扫合并：已知 id 保留裁决状态，新发现追加，已消失不删除（保留裁决历史）"""
    old = {i.id: i for i in load_conflicts(root)}
    for d in detected:
        if d.id not in old:
            old[d.id] = d
    items = list(old.values())
    save_conflicts(root, items)
    return items


def merge_gaps(root, detected: list[Gap]) -> list[Gap]:
    old = {i.id: i for i in load_gaps(root)}
    for d in detected:
        if d.id not in old:
            old[d.id] = d
    items = list(old.values())
    save_gaps(root, items)
    return items
