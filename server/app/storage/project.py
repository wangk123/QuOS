# server/app/storage/project.py
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def slugify(name: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]", "", name)


def project_root(name: str) -> Path:
    root = DATA_DIR / f"{slugify(name)}/"
    root.mkdir(parents=True, exist_ok=True)
    return root
