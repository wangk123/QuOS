# server/app/storage/rules.py
import json
import re
from pathlib import Path

from app.core.models import Rule

_OLD_FILE = "assertions.json"
_A_ID = re.compile(r"^A(\d+)$")


def _file(root) -> Path:
    return Path(root) / "rules.json"


def _read_rows(p: Path) -> list[dict]:
    try:
        return json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError:
        raise RuntimeError(f"{p.name} 损坏，请人工修复或删除")


def _rewrite_refs(root, mapping: dict[str, str]) -> None:
    """旧数据 id（A 前缀，断言时代）联动改名：冲突 a/b 与澄清 ref 同步映射，仅动命中项"""
    for kind, keys in (("conflicts", ("a", "b")), ("clarifications", ("ref",))):
        p = Path(root) / f"{kind}.json"
        if not p.exists():
            continue
        rows = _read_rows(p)
        for r in rows:
            for k in keys:
                if r.get(k) in mapping:
                    r[k] = mapping[r[k]]
        p.write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")


def _migrate(root) -> list[Rule] | None:
    """术语迁移（「断言」→「规则」）：读旧 assertions.json，id A→R，联动改引用文件，落 rules.json 并删旧文件"""
    old = Path(root) / _OLD_FILE
    if not old.exists():
        return None
    rows = _read_rows(old)
    mapping = {r["id"]: f"R{m.group(1)}" for r in rows if (m := _A_ID.match(r.get("id", "")))}
    for r in rows:
        if r.get("id") in mapping:
            r["id"] = mapping[r["id"]]
    _file(root).write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
    _rewrite_refs(root, mapping)
    old.unlink()
    return [Rule(**r) for r in rows]


def _load(root) -> list[Rule]:
    p = _file(root)
    if not p.exists():
        migrated = _migrate(root)
        if migrated is not None:
            return migrated
        return []
    try:
        return [Rule(**r) for r in json.loads(p.read_text("utf-8"))]
    except json.JSONDecodeError:
        raise RuntimeError("rules.json 损坏，请人工修复或删除")


def _save(root, items: list[Rule]) -> None:
    _file(root).parent.mkdir(parents=True, exist_ok=True)
    _file(root).write_text(json.dumps([r.model_dump() for r in items], ensure_ascii=False, indent=1), "utf-8")


def load(root) -> list[Rule]:
    return _load(root)


def save(root, items: list[Rule]) -> None:
    _save(root, items)
