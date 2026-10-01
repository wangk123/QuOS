# server/tests/conftest.py
import pytest
from app.storage import jobs

@pytest.fixture(autouse=True)
def _jobs_persist_isolated(monkeypatch, tmp_path):
    """import app.main 会在模块加载时 jobs.load(真实路径)；之后所有 _save 重定向到 tmp，
    测试不再写真实 server/data/.jobs.json"""
    monkeypatch.setattr(jobs, "_PERSIST", tmp_path / "jobs.json")
    jobs._jobs.clear()  # 清掉采集期 app.main import 注入的内存态
