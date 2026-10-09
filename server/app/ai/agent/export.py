# server/app/ai/agent/export.py —— ATD 任务目录构造（spec §4.1）
import json
import re
import tempfile
import time
from pathlib import Path

from app.core.parse import pdf_text, shrink_image
from app.storage.evidence import Evidence

_TMP_BASE = Path(tempfile.gettempdir())  # 测试 monkeypatch 重定向
_RULES_DIR = Path(__file__).parent / "rules"
_SAFE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]")


def _material_file(ev: Evidence) -> str:
    """ev_id → 落盘文件名；图片统一 .jpg，文本类统一 .md（文本容器，不保留原后缀）"""
    base = _SAFE.sub("_", ev.id)
    if ev.ext.lower() in ("png", "jpg", "jpeg", "webp"):
        return f"{base}.jpg"
    return f"{base}.md"


def _plain_text(f: Path) -> str:
    """docx 剥正文 / 其余按文本读——与 router._docx_text 同口径（内联避免循环导入）"""
    if f.suffix.lower() == ".docx":
        import zipfile
        with zipfile.ZipFile(f) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    return f.read_text("utf-8", errors="replace")


async def build_task_dir(root: Path, evs: list[Evidence], task: str, task_body: str) -> Path:
    """构造 ATD 任务目录：TASK.md（调用方拼的运行时参数）+ RULES.md（模板原文，不做 format）
    + materials/（每材料一文件）+ manifest.json + out/。
    目录名带毫秒时间戳——每次运行唯一：失败现场保留 + 严防读到上次运行的旧 result.json"""
    d = _TMP_BASE / f"quos-agent-{task}-{_SAFE.sub('_', root.name)}-{int(time.time() * 1000)}"
    mdir = d / "materials"
    mdir.mkdir(parents=True, exist_ok=True)
    (d / "out").mkdir(exist_ok=True)
    (d / "TASK.md").write_text(task_body, "utf-8")
    (d / "RULES.md").write_text((_RULES_DIR / f"{task}.md").read_text("utf-8"), "utf-8")
    manifest = []
    for ev in evs:
        f = (root / ev.path) if ev.path else None
        name = _material_file(ev)
        no_text = False
        if f is not None and f.exists():
            suf = f.suffix.lower()
            if suf in (".png", ".jpg", ".jpeg", ".webp"):
                (mdir / name).write_bytes(shrink_image(f))
            elif suf == ".pdf":
                text = pdf_text(f)
                no_text = not text.strip()
                (mdir / name).write_text(
                    text or "（该 PDF 无可提取文本——扫描件，需按图片材料另行入池）", "utf-8")
            else:
                (mdir / name).write_text(_plain_text(f), "utf-8")
        else:
            (mdir / name).write_text(ev.name, "utf-8")
            no_text = True
        entry = {"id": ev.id, "type": ev.type, "name": ev.name, "file": name}
        if no_text:
            entry["no_text"] = True
        manifest.append(entry)
    (mdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    return d


def cleanup(d: Path, keep: bool = False) -> None:
    """任务目录清理：keep=False 删本目录（失败保留现场）；顺带滚动清理旧目录（保留最近 20 个）"""
    import shutil
    if not keep and d.exists():
        shutil.rmtree(d, ignore_errors=True)
    siblings = sorted(d.parent.glob("quos-agent-*"), key=lambda p: p.stat().st_mtime)
    for old in siblings[:-20]:
        shutil.rmtree(old, ignore_errors=True)
