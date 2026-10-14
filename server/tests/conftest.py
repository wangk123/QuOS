"""conftest:每测试独立 in-memory SQLite + TestClient。"""
import pytest
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app.db import get_session


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db(engine):
    maker = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)
    session = maker()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def client(engine, db, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import app.db as dbmod
    from app.main import app

    maker = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)

    def _override():
        yield maker()

    app.dependency_overrides[get_session] = _override
    monkeypatch.setattr(dbmod, "DATA_DIR", tmp_path)  # 材料落盘走临时目录
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def client_factory(tmp_path):
    """文件库 + 每 TestClient 独立连接(并发/竞态测试用,StaticPool 单连接会掩盖 TOCTOU)。"""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker as sa_maker
    import app.db as dbmod
    from app.main import app

    db_file = tmp_path / "race.db"
    eng = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    maker = sa_maker(bind=eng, class_=Session, autoflush=False, expire_on_commit=False)

    def override():
        yield maker()

    app.dependency_overrides[dbmod.get_session] = override

    class Factory:
        client = TestClient(app)
        session = staticmethod(maker)

        @staticmethod
        def make_client() -> TestClient:
            return TestClient(app)

    yield Factory
    app.dependency_overrides.clear()
    eng.dispose()
