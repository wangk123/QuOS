# server/tests/test_runner.py
import json
import pytest, httpx
from app.ai import runner
from app.ai.runner import complete, AITaskError
from pydantic import BaseModel

class Out(BaseModel):
    rules: list[dict]

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
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"rules": []}'}}]})
    monkeypatch.setattr("app.ai.runner._transport", lambda: _mock(h))
    out = await complete("extract", {"material": "x"}, Out)
    assert out.rules == []

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
        content = "不是json" if len(calls) == 1 else '{"rules": [{"k": "v"}]}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    monkeypatch.setattr("app.ai.runner._transport", lambda: _mock(h))
    out = await complete("extract", {"material": "x"}, Out)
    assert out.rules == [{"k": "v"}]
    assert len(calls) == 2

async def test_fenced_json_stripped(monkeypatch):
    # LLM 常把 JSON 包在 ```json 围栏里，应剥离后校验通过
    def h(request):
        content = '```json\n{"rules": [{"k": "v"}]}\n```'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    monkeypatch.setattr("app.ai.runner._transport", lambda: _mock(h))
    out = await complete("extract", {"material": "x"}, Out)
    assert out.rules == [{"k": "v"}]

async def test_call_with_images_builds_content_parts(monkeypatch):
    """带图片时 content 为 parts 数组：text part 在前，图片 base64 data URL 在后"""
    captured = {}

    async def h(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"rules": []}'}}]})

    monkeypatch.setattr("app.ai.runner._transport", lambda: _mock(h))
    img = b"\xff\xd8fakejpeg"
    await runner._call("提示词", [img])
    content = captured["payload"]["messages"][0]["content"]
    assert isinstance(content, list) and content[0] == {"type": "text", "text": "提示词"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

async def test_call_without_images_keeps_plain_string(monkeypatch):
    captured = {}

    async def h(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"rules": []}'}}]})

    monkeypatch.setattr("app.ai.runner._transport", lambda: _mock(h))
    await runner._call("纯文本")
    assert captured["payload"]["messages"][0]["content"] == "纯文本"


async def test_stream_sse_chunks_assembled(monkeypatch):
    """SSE 流式：data: 行逐 chunk 拼接、keepalive 注释行忽略、[DONE] 结束；请求带 stream=true"""
    captured = {}

    def h(request):
        captured["payload"] = json.loads(request.content)
        chunks = [
            {"choices": [{"delta": {"content": '{"rules": '}}]},
            {"choices": [{"delta": {"content": '[{"k": "v"}]}'}}]},
            {"choices": [{"delta": {}}]},  # 空 delta（如 usage 尾包）
        ]
        lines = [f"data: {json.dumps(c)}" for c in chunks] + [": keepalive", "data: [DONE]"]
        body = ("\n\n".join(lines) + "\n\n").encode()
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr("app.ai.runner._transport", lambda: _mock(h))
    out = await complete("extract", {"material": "x"}, Out)
    assert out.rules == [{"k": "v"}]
    assert captured["payload"]["stream"] is True
