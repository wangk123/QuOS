# server/app/ai/runner.py
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

PROMPTS = Path(__file__).parent / "prompts"
_BASE_URL = "https://api.openai.com/v1"
_MODEL = "gpt-4o-mini"
_TIMEOUT = float(os.environ.get("QUOS_LLM_TIMEOUT", "600"))  # 流式下为 chunk 间隔超时；600s 兜底大材料长生成


class AITaskError(Exception): ...


def _client() -> httpx.AsyncClient:
    base_url = os.environ.get("QUOS_LLM_BASE_URL", _BASE_URL)
    host = (urlparse(base_url).hostname or "").strip("[]")
    return httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {os.environ.get('QUOS_LLM_API_KEY', '')}"},
        timeout=_TIMEOUT,
        # 本机网关（含模型网关）不走系统代理，避免代理未启动时连不上
        trust_env=host not in ("127.0.0.1", "localhost", "::1"),
    )


def _transport() -> httpx.AsyncClient | None:
    return None  # 测试用 monkeypatch 替换


async def _call(prompt: str, images: list[bytes] | None = None) -> str:
    content: list | str = [{"type": "text", "text": prompt}]
    if images:
        for b in images:
            url = f"data:image/jpeg;base64,{base64.b64encode(b).decode()}"
            content.append({"type": "image_url", "image_url": {"url": url}})
    else:
        content = prompt  # 纯文本任务保持原样（现状不变）
    payload = {
        "model": os.environ.get("QUOS_LLM_MODEL", _MODEL),
        "messages": [{"role": "user", "content": content}],
        "response_format": {"type": "json_object"},
        # 流式：超时语义从「整包最长等 600s」变「chunk 间隔最长 600s」——长生成不再被整体超时掐断
        "stream": True,
    }
    t = _transport()
    owned = True
    if t is None:
        client = _client()
    elif isinstance(t, httpx.AsyncClient):
        client, owned = t, False
    else:
        client = httpx.AsyncClient(
            transport=t, base_url=os.environ.get("QUOS_LLM_BASE_URL", _BASE_URL), timeout=_TIMEOUT
        )
    try:
        async with client.stream("POST", "/chat/completions", json=payload) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "text/event-stream" not in ctype:
                # 网关/测试 mock 不走 SSE：整包 JSON 兜底（choices[0].message.content）
                return json.loads(await r.aread())["choices"][0]["message"]["content"]
            parts: list[str] = []
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                ch = (obj.get("choices") or [{}])[0]
                piece = (ch.get("delta") or {}).get("content")
                if piece:
                    parts.append(piece)
            return "".join(parts)
    finally:
        if owned:
            await client.aclose()


def _strip_fence(content: str) -> str:
    """LLM 输出常被 ```json 围栏包裹，校验前剥离首尾围栏"""
    t = content.strip()
    if not t.startswith("```"):
        return t
    t = t.split("\n", 1)[1] if "\n" in t else ""
    if t.rstrip().endswith("```"):
        t = t.rstrip()[:-3]
    return t.strip()


async def complete(task: str, variables: dict, schema: type[BaseModel],
                   images: list[bytes] | None = None) -> BaseModel:
    prompt = (PROMPTS / f"{task}.md").read_text("utf-8").format(**variables)
    for attempt in (1, 2):
        try:
            return schema.model_validate_json(_strip_fence(await _call(prompt, images)))
        except Exception as e:
            if attempt == 2:
                msg = str(e).strip()[:180] or type(e).__name__  # ReadTimeout 等 str 为空：至少留类型名
                raise AITaskError(task, f"AI 调用失败: {msg}")
