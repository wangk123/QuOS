# server/app/storage/gitops.py
import re
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} 失败: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def _commit_args(root: Path) -> list[str]:
    """环境无 git 提交身份时兜底，避免 data 仓库提交失败"""
    r = subprocess.run(["git", "config", "user.email"], cwd=root, capture_output=True, text=True)
    return [] if (r.returncode == 0 and r.stdout.strip()) else \
        ["-c", "user.name=QuOS", "-c", "user.email=quos@local"]


def _tags(root: Path) -> list[dict]:
    out = _git(root, "for-each-ref", "refs/tags", "--format=%(refname:short) %(objectname)")
    rows = [line.split(maxsplit=1) for line in out.splitlines() if line.strip()]
    tags = [{"tag": t, "commit": c} for t, c in rows]
    tags.sort(key=lambda x: int(re.sub(r"\D", "", x["tag"]) or 0))
    return tags


def save_baseline(root, note: str) -> dict:
    root = Path(root)
    if not (root / ".git").exists():
        _git(root, "init")
    _git(root, "add", "-A")
    if _git(root, "status", "--porcelain"):  # 无变更时跳过 commit
        _git(root, "commit", *_commit_args(root), "-m", note)
    commit = _git(root, "rev-parse", "HEAD")
    nums = [int(re.sub(r"\D", "", t["tag"]) or 0) for t in _tags(root)]
    v = max(nums, default=0) + 1  # 删除中间 tag 后不与残留 vN 撞号
    tag = f"v{v}"
    _git(root, "tag", tag)
    return {"commit": commit, "tag": tag, "v": v}


def list_baselines(root) -> list[dict]:
    root = Path(root)
    if not (root / ".git").exists():
        return []
    return _tags(root)
