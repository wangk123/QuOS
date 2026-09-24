# server/app/main.py
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.projects import projects_router
from app.api.router import api_router
from app.storage import db, project


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 启动对账：文件系统两侧扫描为准，DB 行同步（幽灵行删除、缺失行补齐）
    rows = project.scan("active") + project.scan("archived")
    db.reconcile([{**r, "status": "active" if project.exists_active(r["slug"]) else "archived"}
                  for r in rows])
    yield


app = FastAPI(title="QuOS", lifespan=lifespan)

app.include_router(projects_router, prefix="/api/projects")
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
