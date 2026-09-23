# server/app/core/classify.py
import re

_REPO = re.compile(r"^(git@|https?://\S*(?:github|gitlab|gitee|git))", re.I)
# ssh 仓库名不强制 .git 后缀；分支分隔符为 @ 或空白；https 仅在 .git 后缀下解析分支
_BRANCH = re.compile(r"^(git@[^@\s]+?(?:\.git)?|https?://\S+?\.git)[@\s]+([\w][\w/\-.]*)$", re.S)

def classify_text(v: str) -> dict:
    v = v.strip()
    if _REPO.match(v):
        m = _BRANCH.match(v)
        if m:
            return {"type": "仓库", "name": m.group(1), "ext": "@" + m.group(2), "stars": 3}
        return {"type": "仓库", "name": v, "ext": "", "stars": 3}
    is_url = v.startswith("http://") or v.startswith("https://")
    return {"type": "文本", "name": v[:38] + ("…" if len(v) > 38 else ""),
            "ext": "文本·链接" if is_url else "文本·粘贴", "stars": 2}

def classify_file(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in {"zip", "rar", "7z", "tar", "gz"}:
        return "压缩包"
    if ext in {"png", "jpg", "jpeg", "gif", "webp"}:
        return "截图"
    return "文档"
