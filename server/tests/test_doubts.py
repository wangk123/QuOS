# server/tests/test_doubts.py —— 存疑汇总聚合端点（需求②）：分组/全局区/统计口径
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.models import Conflict, Gap, Rule
from app.main import app
from app.storage import findings, rules as rule_store
from app.storage.project import DATA_DIR, ensure_root

BASE = "/api/projects/存疑项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _seed(client):
    root = ensure_root("存疑项目")
    assert DATA_DIR  # 引用防 linter 误报未使用
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "支付"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": "0", "name": "放款重试"})
    await client.post(f"{BASE}/tree", json={"op": "add", "path": None, "name": "风控"})
    rule_store.save(root, [
        Rule(id="R1", text="重试3次", src="a.py:1", conf="实证", verified=True, node="支付/放款重试"),
        Rule(id="R2", text="额度校验", src="b.py:1", conf="文档", node="风控"),
        Rule(id="R3", text="幂等键", src="a.py:9", conf="实证", verified=True, node="支付/放款重试"),
    ])
    findings.save_conflicts(root, [
        Conflict(id="C1", parties=["R1", "R2"], q="重试几次？"),               # open：按 R1 归属「支付」
        Conflict(id="C2", parties=["R1", "R3"], q="历史已裁决的矛盾", st="done"),
    ])
    findings.save_gaps(root, [
        Gap(id="G1", dim="幂等", text="未说明幂等键", node="支付/放款重试"),
        Gap(id="G2", dim="状态", text="未说明风控状态流转", node="风控"),
        Gap(id="G3", dim="状态", text="未说明根级发布状态", node="__root__"),
        Gap(id="G4", dim="边界", text="旧数据的全局缺口", node=""),
        Gap(id="G5", dim="边界", text="已处置不计数", st="ok", node="风控"),
        Gap(id="G6", dim="状态", text="已转澄清不占缺口数", st="clar", node="风控"),
    ])


async def test_doubts_summary_groups_global_and_stats(client):
    await _seed(client)
    r = await client.get(f"{BASE}/doubts/summary")
    assert r.status_code == 200
    d = r.json()
    assert d["stats"] == {"conflicts": 1, "gaps": 4}  # open 计数（clarified 已随问人体系退役）
    assert [g["id"] for g in d["global"]] == ["G3", "G4"]  # __root__ 与未绑定 → 全局区
    by_name = {m["name"]: m for m in d["modules"]}
    assert by_name["支付"] == {"name": "支付", "rules": 2, "total": 4, "conflicts": 1, "gaps": 1, "peek": "未说明幂等键"}  # total=rules+open冲突+open缺口
    assert by_name["风控"] == {"name": "风控", "rules": 1, "total": 2, "conflicts": 0, "gaps": 1, "peek": "未说明风控状态流转"}
    assert [m["name"] for m in d["modules"]] == ["支付", "风控"]  # 行序=树序
