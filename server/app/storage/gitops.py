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


_VER = re.compile(r"\d+\.\d+\.\d+")


def _semver(tag: str) -> tuple[int, int, int] | None:
    """新格式 v{x.y.z} → 三元组；其余（旧 vN 等）→ None"""
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(int(x) for x in m.groups()) if m else None


def _sort_key(tag: str) -> tuple[int, int, int]:
    """时间线排序键：新格式语义化；旧 vN 映射 (N,0,0)；兜底 0"""
    return _semver(tag) or (int(re.sub(r"\D", "", tag) or 0), 0, 0)


def _tags(root: Path) -> list[dict]:
    out = _git(root, "for-each-ref", "refs/tags", "--format=%(refname:short) %(objectname)")
    rows = [line.split(maxsplit=1) for line in out.splitlines() if line.strip()]
    tags = [{"tag": t, "commit": c} for t, c in rows]
    tags.sort(key=lambda x: _sort_key(x["tag"]))
    return tags


def save_baseline(root, version: str, note: str) -> dict:
    root = Path(root)
    if not _VER.fullmatch(version):
        raise ValueError(f"版本号格式须为 x.y.z（三段数字）: {version}")
    if not (root / ".git").exists():
        _git(root, "init")
    tags = _tags(root)
    tag = f"v{version}"
    if any(t["tag"] == tag for t in tags):
        raise ValueError(f"版本号已存在: {version}")
    max_new = max((s for s in (_semver(t["tag"]) for t in tags) if s), default=None)
    if max_new and tuple(int(x) for x in version.split(".")) <= max_new:
        raise ValueError(f"版本号不得低于已有最大版本 {'.'.join(map(str, max_new))}")
    _git(root, "add", "-A")
    has_head = _git(root, "rev-list", "-n1", "--all") != ""
    if _git(root, "status", "--porcelain") or not has_head:  # 无变更跳过；空仓库建空 commit 供 tag 挂靠
        _git(root, "commit", *_commit_args(root), "-m", note, "--allow-empty")
    commit = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", tag)
    return {"commit": commit, "tag": tag, "version": version}


def list_baselines(root) -> list[dict]:
    root = Path(root)
    if not (root / ".git").exists():
        return []
    # 双取 * 字段：annotated tag 的 objectname/committerdate 是 tag object 自身的，
    # %(*objectname)/%(*committerdate) 才穿透到指向的 commit；轻量 tag 恰好相反（* 为空）
    out = _git(root, "for-each-ref", "refs/tags", "--format="
               "%(refname:short)%00%(objectname)%00%(*objectname)%00"
               "%(contents:subject)%00%(*committerdate:unix)%00%(committerdate:unix)")
    head = _git(root, "rev-parse", "HEAD")
    items = []
    for line in out.splitlines():
        if not line.strip():
            continue
        tag, oid, deref, note, dts, ts = line.split("\x00")
        commit = deref or oid
        items.append({"tag": tag, "commit": commit, "note": note,
                      "time": int(dts or ts or 0), "cur": commit == head})
    items.sort(key=lambda x: _sort_key(x["tag"]))
    return items


def restore_baseline(root, tag: str) -> None:
    """工作区完整回到该版：reset --hard + 清未跟踪文件（未存版修改丢弃，已裁定）"""
    root = Path(root)
    if tag not in {t["tag"] for t in _tags(root)}:
        raise KeyError(tag)
    _git(root, "reset", "--hard", tag)
    _git(root, "clean", "-fd")


def delete_baseline(root, tag: str) -> None:
    """废弃：tag 删除即时间线消失；commit 留在 git 历史。幂等"""
    root = Path(root)
    if tag in {t["tag"] for t in _tags(root)}:
        _git(root, "tag", "-d", tag)
