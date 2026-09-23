# server/tests/test_runner.py
import pytest, httpx
from app.ai.runner import complete, AITaskError
from pydantic import BaseModel

class Out(BaseModel):
    assertions: list[dict]

@pytest.fixture(autouse=True)
def _prompts(tmp_path, monkeypatch):
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "extract.md").write_text("材料：{material}", "utf-8")
    monkeypatch.setattr("app.ai.runner.PROMPTS", d)

def _mock(handler):
    return httpx.MockTransport(handler)

async def test_ok(monkeypatch):
    def h(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"assertions": []}'}}]})
    monkeypatch.setattr("app.ai.runner._transport", lambda: _mock(h))
    out = await complete("extract", {"material": "x"}, Out)
    assert out.assertions == []

async def test_retry_then_fail(monkeypatch):
    def h(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "不是json"}}]})
    monkeypatch.setattr("app.ai.runner._transport", lambda: _mock(h))
    with pytest.raises(AITaskError):
        await complete("extract", {"material": "x"}, Out)

async def test_retry_recovers(monkeypatch):
    calls = []
    def h(request):
        calls.append(request)
        content = "不是json" if len(calls) == 1 else '{"assertions": [{"k": "v"}]}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    monkeypatch.setattr("app.ai.runner._transport", lambda: _mock(h))
    out = await complete("extract", {"material": "x"}, Out)
    assert out.assertions == [{"k": "v"}]
    assert len(calls) == 2

async def test_fenced_json_stripped(monkeypatch):
    # LLM 常把 JSON 包在 ```json 围栏里，应剥离后校验通过
    def h(request):
        content = '```json\n{"assertions": [{"k": "v"}]}\n```'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    monkeypatch.setattr("app.ai.runner._transport", lambda: _mock(h))
    out = await complete("extract", {"material": "x"}, Out)
    assert out.assertions == [{"k": "v"}]
