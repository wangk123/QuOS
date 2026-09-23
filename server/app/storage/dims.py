# server/app/storage/dims.py
import json
from pathlib import Path

DEFAULT = ["状态", "异常", "边界", "幂等", "数据", "依赖"]


def _f(root) -> Path:
    return Path(root) / "dims.json"


def get_dims(root) -> list[str]:
    p = _f(root)
    return json.loads(p.read_text("utf-8")) if p.exists() else list(DEFAULT)


def set_dims(root, dims: list[str]) -> None:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    _f(root).write_text(json.dumps(dims, ensure_ascii=False, indent=1), "utf-8")
