# server/app/core/parse.py
from io import BytesIO
from pathlib import Path

MAX_EDGE = 1600


def pdf_text(f: Path) -> str:
    """PDF 文本提取；无文本（扫描件）返回空串，损坏文件抛中文 RuntimeError"""
    try:
        from pypdf import PdfReader
        pages = [p.extract_text() or "" for p in PdfReader(str(f)).pages]
    except Exception as e:
        raise RuntimeError(f"PDF 解析失败: {e}") from e
    return "\n".join(t.strip() for t in pages if t.strip())


def shrink_image(f: Path) -> bytes:
    """图片压缩为长边 ≤1600 的 JPEG 字节（控多模态 token）"""
    from PIL import Image
    img = Image.open(f)
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_EDGE:
        r = MAX_EDGE / max(w, h)
        img = img.resize((int(w * r), int(h * r)))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()
