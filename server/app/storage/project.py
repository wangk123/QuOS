# server/app/storage/project.py
# 文件系统是项目身份与状态的真相源：身份=目录名，归档=目录移入 .archived/。
# project.json 存静态元信息（name/description/created_at），缺失时目录名兜底。
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"
ARCHIVE_DIR = DATA_DIR / ".archived"

_SLUG_RE = re.compile(r"[^\w\u4e00-\u9fff-]")


class ProjectNotFound(Exception): ...


def is_valid_name(name: str) -> bool:
    """项目名清洗后是否非空（空名无法定位项目目录）"""
    return bool(_SLUG_RE.sub("", name))


def slugify(name: str) -> str:
    return _SLUG_RE.sub("", name) or "node"


def project_root(name: str) -> Path:
    # 只返回路径不建目录（创建走 create/ensure_root，防拼错 URL 凭空生成空项目）
    return DATA_DIR / f"{slugify(name)}/"


def ensure_root(name: str) -> Path:
    root = project_root(name)
    root.mkdir(parents=True, exist_ok=True)
    return root


def exists_active(name: str) -> bool:
    return project_root(name).is_dir()


def require_root(name: str) -> Path:
    root = project_root(name)
    if not root.is_dir():
        raise ProjectNotFound(slugify(name))
    return root


def _meta_path(root: Path) -> Path:
    return root / "project.json"


def _read_meta(root: Path, slug: str) -> dict:
    p = _meta_path(root)
    if p.exists():
        try:
            m = json.loads(p.read_text("utf-8"))
            return {"slug": slug, "name": m.get("name") or slug,
                    "description": m.get("description") or "",
                    "created_at": m.get("created_at") or ""}
        except ValueError:
            pass  # 损坏 json 按无元信息兜底
    return {"slug": slug, "name": slug, "description": "", "created_at": ""}


def _write_meta(root: Path, name: str, description: str, created_at: str):
    _meta_path(root).write_text(json.dumps(
        {"name": name, "description": description, "created_at": created_at},
        ensure_ascii=False, indent=2), "utf-8")


def scan(status: str) -> list[dict]:
    base = ARCHIVE_DIR if status == "archived" else DATA_DIR
    if not base.is_dir():
        return []
    rows = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        rows.append(_read_meta(d, d.name))
    return rows


def create(name: str, description: str = "") -> dict:
    if not is_valid_name(name):
        raise ValueError(f"非法项目名: {name}")
    slug = slugify(name)
    if project_root(name).is_dir() or (ARCHIVE_DIR / slug).is_dir():
        raise ValueError(f"项目已存在（含归档侧）: {slug}")
    root = ensure_root(name)
    created_at = datetime.now().isoformat(timespec="seconds")
    _write_meta(root, name, description, created_at)
    return {"slug": slug, "name": name, "description": description, "created_at": created_at}


def write_description(slug: str, description: str):
    root = ARCHIVE_DIR / slug if (ARCHIVE_DIR / slug).is_dir() else DATA_DIR / slug
    m = _read_meta(root, slug)
    _write_meta(root, m["name"], description, m["created_at"])


def archive(slug: str):
    src = DATA_DIR / slug
    if not src.is_dir():
        raise ProjectNotFound(slug)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(ARCHIVE_DIR / slug))


def restore(slug: str):
    src = ARCHIVE_DIR / slug
    if not src.is_dir():
        raise ProjectNotFound(slug)
    if (DATA_DIR / slug).is_dir():
        raise ValueError(f"活跃侧已存在同名项目: {slug}")
    shutil.move(str(src), str(DATA_DIR / slug))


def purge(slug: str):
    src = ARCHIVE_DIR / slug
    if not src.is_dir():
        if (DATA_DIR / slug).is_dir():
            raise ValueError(f"活跃项目不可彻底删除，须先归档: {slug}")
        raise ProjectNotFound(slug)
    shutil.rmtree(src)  # 含 git 基线历史，仅归档态可调用
