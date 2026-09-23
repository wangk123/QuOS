# server/app/main.py
from fastapi import FastAPI

from app.api.router import api_router

app = FastAPI(title="QuOS")

app.include_router(api_router, prefix="/api/projects/{proj}")


@app.get("/api/health")
def health():
    return {"status": "ok"}
