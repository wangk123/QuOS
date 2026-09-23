# server/app/ai/runner.py
import os
from pathlib import Path

import httpx
from pydantic import BaseModel

PROMPTS = Path(__file__).parent / "prompts"
_BASE_URL = "https://api.openai.com/v1"
_MODEL = "gpt-4o-mini"


class AITaskError(Exception): ...


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=os.environ.get("QUOS_LLM_BASE_URL", _BASE_URL),
        headers={"Authorization": f"Bearer {os.environ.get('QUOS_LLM_API_KEY', '')}"},
        timeout=60.0,
    )


def _transport() -> httpx.AsyncClient | None:
    return None  # 测试用 monkeypatch 替换


async def _call(prompt: str) -> str:
    t = _transport()
    owned = True
    if t is None:
        client = _client()
    elif isinstance(t, httpx.AsyncClient):
        client, owned = t, False
    else:
        client = httpx.AsyncClient(
            transport=t, base_url=os.environ.get("QUOS_LLM_BASE_URL", _BASE_URL)
        )
    try:
        r = await client.post(
            "/chat/completions",
            json={
                "model": os.environ.get("QUOS_LLM_MODEL", _MODEL),
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
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


async def complete(task: str, variables: dict, schema: type[BaseModel]) -> BaseModel:
    prompt = (PROMPTS / f"{task}.md").read_text("utf-8").format(**variables)
    for attempt in (1, 2):
        try:
            return schema.model_validate_json(_strip_fence(await _call(prompt)))
        except Exception as e:
            if attempt == 2:
                raise AITaskError(task, f"输出校验失败: {str(e)[:200]}")
