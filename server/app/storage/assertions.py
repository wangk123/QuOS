# server/app/storage/assertions.py
import json
from pathlib import Path

from app.core.models import Assertion


def _file(root) -> Path:
    return Path(root) / "assertions.json"


def _load(root) -> list[Assertion]:
    p = _file(root)
    if not p.exists():
        return []
    try:
        return [Assertion(**r) for r in json.loads(p.read_text("utf-8"))]
    except json.JSONDecodeError:
        raise RuntimeError("assertions.json 损坏，请人工修复或删除")


def _save(root, items: list[Assertion]) -> None:
    _file(root).parent.mkdir(parents=True, exist_ok=True)
    _file(root).write_text(json.dumps([a.model_dump() for a in items], ensure_ascii=False, indent=1), "utf-8")


def load(root) -> list[Assertion]:
    return _load(root)


def save(root, items: list[Assertion]) -> None:
    _save(root, items)
