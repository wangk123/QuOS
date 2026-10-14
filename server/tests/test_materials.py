"""材料上传/解析/hash 去重测试。"""
import io

from pypdf import PdfWriter


def make_pdf_bytes(text: str = "Hello QuOS") -> bytes:
    """动态构造最小含文本 PDF(精确计算 xref 偏移)。"""
    content = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF".encode()
    )
    return out.getvalue()


def make_png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _upload(client, pid: int, name: str, data: bytes):
    return client.post(
        f"/api/v1/projects/{pid}/materials",
        files={"file": (name, data)},
    )


def _mk_project(client) -> int:
    return client.post("/api/v1/projects", json={"name": "P"}).json()["id"]


def test_upload_pdf_extracts_text(client):
    pid = _mk_project(client)
    r = _upload(client, pid, "contract.pdf", make_pdf_bytes("Hello QuOS"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Hello QuOS" in body["parsed_text"]
    assert body["sha256"] and len(body["sha256"]) == 64


def test_upload_image_empty_text_ok(client):
    pid = _mk_project(client)
    r = _upload(client, pid, "whiteboard.png", make_png_bytes())
    assert r.status_code == 200
    assert r.json()["parsed_text"] == ""


def test_duplicate_hash_409_with_original_id(client):
    pid = _mk_project(client)
    first = _upload(client, pid, "a.pdf", make_pdf_bytes()).json()
    r = _upload(client, pid, "b-copy.pdf", make_pdf_bytes())
    assert r.status_code == 409
    assert r.json()["detail"]["material_id"] == first["id"]


def test_upload_to_missing_project_404(client):
    r = _upload(client, 9999, "x.md", b"# hi")
    assert r.status_code == 404


def test_list_materials_for_agent(client):
    pid = _mk_project(client)
    _upload(client, pid, "note.md", "# 标题\n正文".encode())
    items = client.get(f"/api/v1/projects/{pid}/materials").json()
    assert len(items) == 1
    assert items[0]["filename"] == "note.md"
    assert "标题" in items[0]["parsed_text"]
