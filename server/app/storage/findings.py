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


def _migrate_conflict(row: dict) -> dict:
    """存量兼容：a/b → parties=[a,b]；st=clar（历史转澄清，体系已退役）归一 done"""
    if "parties" not in row:
        row["parties"] = [row["a"], row["b"]]
    row.pop("a", None); row.pop("b", None)
    if row.get("st") in ("code", "clar"):  # 旧裁决态（code=信某方/clar=历史转澄清）统一归一 done
        row["st"] = "done"
    return row


def load_conflicts(root) -> list[Conflict]:
    p = _file(root, "conflicts")
    if not p.exists():
        return []
    try:
        import json as _json
        rows = [_migrate_conflict(r) for r in _json.loads(p.read_text("utf-8"))]
        return [Conflict(**r) for r in rows]
    except json.JSONDecodeError:
        raise RuntimeError("conflicts.json 损坏，请人工修复或删除")


def save_conflicts(root, items: list[Conflict]) -> None:
    _save(root, "conflicts", items)


def load_gaps(root) -> list[Gap]:
    return _load(root, "gaps", Gap)


def save_gaps(root, items: list[Gap]) -> None:
    _save(root, "gaps", items)


def merge_conflicts(root, detected: list[Conflict]) -> list[Conflict]:
    """重扫合并：按无序多方集合去重（防重扫 id 漂移丢新冲突），已知组保留裁决状态，已消失不删除"""
    items = load_conflicts(root)
    seen = {frozenset(c.parties) for c in items}
    n = max((int(c.id[1:]) for c in items if c.id.startswith("C") and c.id[1:].isdigit()), default=0)
    for d in detected:
        key = frozenset(d.parties)
        if key not in seen:
            seen.add(key)
            if not d.id:
                n += 1
                d.id = f"C{n}"
            items.append(d)
    save_conflicts(root, items)
    return items


def merge_gaps(root, detected: list[Gap]) -> list[Gap]:
    items = load_gaps(root)
    seen = {(g.dim, g.text, g.node) for g in items}  # 含 node：同文案不同节点是两条独立缺口
    for d in detected:
        if (d.dim, d.text, d.node) not in seen:
            seen.add((d.dim, d.text, d.node))
            items.append(d)
    save_gaps(root, items)
    return items
