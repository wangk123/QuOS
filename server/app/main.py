# server/app/main.py
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router

app = FastAPI(title="QuOS")

app.include_router(api_router, prefix="/api/projects/{proj}")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 无 LLM key 的端到端走查：AI 任务返回固定假数据（见 app/ai/fake.py）
if os.environ.get("QUOS_FAKE_AI") == "1":
    from app.ai import fake

    fake.install()

# 前端静态托管：web/dist 构建产物（server/app/main.py → 上两级为 QuOS 根）
# 目录不存在时跳过挂载，避免测试/纯 API 环境报错
_web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
if _web_dist.is_dir():
    app.mount("/", StaticFiles(directory=_web_dist, html=True), name="web")
