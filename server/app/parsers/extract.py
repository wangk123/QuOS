"""材料文本抽取:按后缀分派,pdf 用 pypdf、图片返回空串(design §6:不引 OCR)。"""
import io
from pathlib import Path

from pypdf import PdfReader


def extract_text(filename: str, data: bytes) -> str:
    """尽力抽取文本;失败返回空串,不抛错(解析失败保留原件可重试的语义)。"""
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        if suffix in {".md", ".txt", ".markdown"}:
            return data.decode("utf-8", errors="replace")
        return ""  # 图片与其他二进制:parsed_text 空
    except Exception:
        return ""
