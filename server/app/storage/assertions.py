# server/app/storage/assertions.py
import json
from pathlib import Path

from app.core.models import Assertion


def _file(root) -> Path:
    return Path(root) / "assertions.json"


def _load(root) -> list[Assertion]:
    p = _file(root)
    return [Assertion(**r) for r in json.loads(p.read_text("utf-8"))] if p.exists() else []


def _save(root, items: list[Assertion]) -> None:
    _file(root).parent.mkdir(parents=True, exist_ok=True)
    _file(root).write_text(json.dumps([a.model_dump() for a in items], ensure_ascii=False, indent=1), "utf-8")


def load(root) -> list[Assertion]:
    return _load(root)


def save(root, items: list[Assertion]) -> None:
    _save(root, items)
