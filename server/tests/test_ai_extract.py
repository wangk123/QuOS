# server/tests/test_ai_extract.py
import pytest
from app.ai import tasks
from app.core.models import Assertion

async def test_extract(monkeypatch):
    fake = tasks.ExtractOut(assertions=[Assertion(id="A1", text="当超时30s触发重试", src="retry.py:15", conf="实证")])
    async def mock(task, variables, schema): return fake
    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.extract("代码内容", "代码")
    assert out[0].conf == "实证"

async def test_verify_marks_correction(monkeypatch):
    fake = tasks.VerifyOut(results=[{"id": "A7", "ok": False, "corrected_text": "指数退避", "reason": "代码为指数"}])
    async def mock(task, variables, schema): return fake
    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.verify([Assertion(id="A7", text="固定60s", src="x:1", conf="实证")], "代码")
    assert out.results[0]["corrected_text"] == "指数退避"
