# server/tests/test_agent_export.py
import json
import shutil
from pathlib import Path

from app.ai.agent import engine_on
from app.ai.agent.export import build_task_dir
from app.storage.evidence import Evidence

EVS = [
    Evidence(id="文档a1", name="需求.md", ext="md", type="文档", stars=2,
             reg="2026-10-09", path="", state="pending"),
    Evidence(id="图片b2", name="shot.png", ext="png", type="图片", stars=2,
             reg="2026-10-09", path="", state="pending"),
]

# 现场生成的合法 PNG（比硬编码字节稳）
import io
from PIL import Image

_buf = io.BytesIO()
Image.new("RGB", (2, 2), (255, 0, 0)).save(_buf, "PNG")
PNG_1X1 = _buf.getvalue()


def _mk_material(root: Path, ev: Evidence, content: bytes):
    p = root / "evidence" / "files" / ev.name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    ev.path = f"evidence/files/{ev.name}"


async def test_engine_toggle(monkeypatch):
    monkeypatch.delenv("QUOS_DSH_CMD", raising=False)
    monkeypatch.setenv("QUOS_AGENT_ENGINE", "dsh")
    assert engine_on() is False  # 未配置启动命令 → 回落
    monkeypatch.setenv("QUOS_DSH_CMD", "echo dsh")
    assert engine_on() is True
    monkeypatch.setenv("QUOS_AGENT_ENGINE", "off")
    assert engine_on() is False


async def test_build_task_dir(tmp_path, monkeypatch):
    import app.ai.agent.export as ex
    monkeypatch.setattr(ex, "_TMP_BASE", tmp_path)  # 测试不写系统临时目录
    md = EVS[0]
    _mk_material(tmp_path, md, "# 需求\n正文".encode("utf-8"))
    png = EVS[1]
    _mk_material(tmp_path, png, PNG_1X1)
    d = await build_task_dir(tmp_path, [md, png], "tree-gen", "材料清单：全部")
    assert (d / "TASK.md").read_text("utf-8").startswith("材料清单")
    assert (d / "RULES.md").exists() and (d / "out").is_dir()
    manifest = json.loads((d / "materials" / "manifest.json").read_text("utf-8"))
    assert [m["id"] for m in manifest] == ["文档a1", "图片b2"]
    assert (d / "materials" / "文档a1.md").read_text("utf-8") == "# 需求\n正文"
    assert (d / "materials" / "图片b2.jpg").exists()  # 图片统一转 jpg
    assert manifest[0].get("no_text") is None and manifest[1].get("no_text") is None


async def test_no_text_pdf_flagged(tmp_path, monkeypatch):
    import app.ai.agent.export as ex
    monkeypatch.setattr(ex, "_TMP_BASE", tmp_path)
    monkeypatch.setattr(ex, "pdf_text", lambda f: "")  # 空文本 pdf（扫描件）分支
    ev = EVS[0].model_copy(update={"name": "scan.pdf", "ext": "pdf", "id": "文档c3"})
    _mk_material(tmp_path, ev, b"%PDF-1.4 whatever")
    d = await build_task_dir(tmp_path, [ev], "extract", "x")
    manifest = json.loads((d / "materials" / "manifest.json").read_text("utf-8"))
    assert manifest[0]["no_text"] is True
    assert "无可提取文本" in (d / "materials" / "文档c3.md").read_text("utf-8")
