# server/app/storage/project.py
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"

_SLUG_RE = re.compile(r"[^\w\u4e00-\u9fff-]")


def is_valid_name(name: str) -> bool:
    """项目名清洗后是否非空（空名无法定位项目目录）"""
    return bool(_SLUG_RE.sub("", name))


def slugify(name: str) -> str:
    return _SLUG_RE.sub("", name) or "node"


def project_root(name: str) -> Path:
    root = DATA_DIR / f"{slugify(name)}/"
    root.mkdir(parents=True, exist_ok=True)
    return root
