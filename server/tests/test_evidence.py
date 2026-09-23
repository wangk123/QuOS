# server/tests/test_evidence.py
import pytest
from app.storage.project import project_root
from app.storage import evidence as ev

@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    return project_root("测试项目")

@pytest.mark.asyncio
async def test_add_and_list(root):
    e = await ev.add(root, {"type": "文本", "name": "口头说明", "ext": "文本·粘贴", "stars": 2})
    assert e.id and e.state == "pending"
    assert (await ev.list_all(root))[0].name == "口头说明"

@pytest.mark.asyncio
async def test_missing_file_flagged(root):
    e = await ev.add(root, {"type": "文档", "name": "旧文档.docx", "ext": "", "stars": 1}, content=b"x")
    (root / "evidence" / "files" / "旧文档.docx").unlink()
    lst = await ev.list_all(root)
    assert lst[0].model_dump().get("missing") is True

@pytest.mark.asyncio
async def test_mark_extracted(root):
    e = await ev.add(root, {"type": "文本", "name": "t", "ext": "", "stars": 2})
    await ev.mark_extracted(root, e.id, 6)
    assert (await ev.get(root, e.id)).state == "extracted"
