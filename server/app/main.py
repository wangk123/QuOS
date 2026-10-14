"""FastAPI 装配:CORS、健康检查、路由挂载。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import doc, materials, projects, questions

app = FastAPI(title="QuOS v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(materials.router)
app.include_router(doc.router)
app.include_router(questions.router)


@app.get("/api/v1/health")
def health():
    return {"ok": True}
