# server/app/main.py
from fastapi import FastAPI
app = FastAPI(title="QuOS")

@app.get("/api/health")
def health():
    return {"status": "ok"}
