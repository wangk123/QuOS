# server/tests/test_badge_consistency.py —— 标识体系一致性恒等式（防口径分裂回归）：
# ① wb/summary 树行 ≡ doubts/summary 模块行（同函数同口径）
# ② Σ顶层模块行 + 全局区 ≡ 根汇总 stats（不重不漏）
# ③ 模块行 ≡ Σ子节点行 + 自身直接项（子树聚合可加性）
# ④ GET /conflicts 的 node 归属与树行计数同源（详情 tab 角标 ≡ 树行）
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.models import Conflict, Gap, Rule
from app.main import app
from app.storage import findings, rules as rule_store
from app.storage.project import ensure_root

BASE = "/api/projects/对拍项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _seed(client):
    """覆盖全部归属形态：叶级/模块级/未归类/已删路径规则 × 冲突五种组合 + 缺口六种形态"""
    root = ensure_root("对拍项目")
    for body in ({"op": "add", "path": None, "name": "支付"},
                 {"op": "add", "path": "0", "name": "放款重试"},
                 {"op": "add", "path": "0", "name": "额度测算"},
                 {"op": "add", "path": None, "name": "风控"}):
        await client.post(f"{BASE}/tree", json=body)
    rule_store.save(root, [
        Rule(id="R1", text="叶级已核", src="a", conf="实证", verified=True, node="支付/放款重试"),
        Rule(id="R2", text="叶级未核", src="a", conf="文档", verified=False, node="支付/放款重试"),
        Rule(id="R3", text="模块级规则", src="a", conf="文档", verified=True, node="支付"),
        Rule(id="R4", text="未归类规则", src="a", conf="文档", verified=True, node=""),
        Rule(id="R5", text="树上已删路径的规则", src="a", conf="文档", verified=True, node="支付/已删节点"),
    ])
    findings.save_conflicts(root, [
        Conflict(id="C1", a="R1", b="R2", q="双叶冲突"),                     # deepest → 支付/放款重试
        Conflict(id="C2", a="R3", b="R1", q="模块级×叶"),                    # deepest → 支付/放款重试
        Conflict(id="C3", a="R4", b="R6", q="一方未归类一方不存在"),         # 无有效归属 → 全局
        Conflict(id="C4", a="R5", b="R1", q="一方路径已删"),                 # 有效方最深 → 支付/放款重试
        Conflict(id="C5", a="R1", b="R2", q="已裁决不计数", st="code", resolution="R1"),
    ])
    findings.save_gaps(root, [
        Gap(id="G1", dim="边界", text="叶缺口", node="支付/额度测算"),
        Gap(id="G2", dim="边界", text="模块缺口", node="支付"),
        Gap(id="G3", dim="状态", text="根级缺口", node="__root__"),
        Gap(id="G4", dim="状态", text="未绑定缺口", node=""),
        Gap(id="G5", dim="边界", text="孤儿路径缺口", node="支付/已删节点"),   # 归全局，不得泄漏
        Gap(id="G6", dim="边界", text="已处置", st="ok", node="支付"),
    ])


async def test_identity_wb_equals_doubts(client):
    """① 同一模块 wb 树行与 doubts 模块行指标恒等（归属唯一函数，两端口同源）"""
    await _seed(client)
    wb = {n["full"]: n for n in (await client.get(f"{BASE}/wb/summary")).json()["tree"]}
    doubts = {m["name"]: m for m in (await client.get(f"{BASE}/doubts/summary")).json()["modules"]}
    for top, m in doubts.items():
        r = wb[top]
        assert (r["rules"], r["conf"], r["gaps"]) == (m["rules"], m["conflicts"], m["gaps"]), top


async def test_identity_tree_plus_global_equals_stats(client):
    """② Σ顶层模块行 + 全局区 ≡ stats（open 冲突/缺口各归一处，不重不漏）"""
    await _seed(client)
    wb = (await client.get(f"{BASE}/wb/summary")).json()["tree"]
    d = (await client.get(f"{BASE}/doubts/summary")).json()
    tops = [n for n in wb if "/" not in n["full"]]
    assert sum(n["conf"] for n in tops) + len(d["globalConflicts"]) == d["stats"]["conflicts"]
    assert sum(n["gaps"] for n in tops) + len(d["global"]) == d["stats"]["gaps"]
    assert [c["id"] for c in d["globalConflicts"]] == ["C3"]  # 无有效归属的 open 冲突进全局冲突区
    assert {g["id"] for g in d["global"]} == {"G3", "G4", "G5"}  # 根级/未绑定/孤儿路径缺口归全局


async def test_identity_module_equals_children_plus_own(client):
    """③ 每个模块行 = Σ子节点行 + 自身直接项（子树两两不交，指标可加）"""
    await _seed(client)
    tree = (await client.get(f"{BASE}/wb/summary")).json()["tree"]
    for mod in [n for n in tree if n["kind"] == "module"]:
        kids = [n for n in tree if n["full"].startswith(mod["full"] + "/")
                and n["full"].count("/") == mod["full"].count("/") + 1]
        own = {k: 0 for k in ("rules", "unverified", "conf", "gaps")}
        for k in kids:
            for f in own:
                own[f] += k[f]
        # 自身直接项：node 恰为模块路径的规则/归属恰为模块的冲突与缺口
        rs = (await client.get(f"{BASE}/rules")).json()
        confs = (await client.get(f"{BASE}/conflicts")).json()
        gaps = (await client.get(f"{BASE}/gaps")).json()
        own["rules"] += sum(1 for r in rs if r["node"] == mod["full"])
        own["unverified"] += sum(1 for r in rs if r["node"] == mod["full"] and not r["verified"])
        own["conf"] += sum(1 for c in confs if c["st"] == "open" and c.get("node") == mod["full"])
        own["gaps"] += sum(1 for g in gaps if g["st"] == "open" and g["node"] == mod["full"])
        for f, v in own.items():
            assert mod[f] == v, f"{mod['full']}.{f}: {mod[f]} != {v}"


async def test_conflicts_carry_node_field(client):
    """④ GET /conflicts 每条带 node 归属（与树行计数同源）——前端只按它过滤，不再自行推导"""
    await _seed(client)
    confs = {c["id"]: c for c in (await client.get(f"{BASE}/conflicts")).json()}
    assert confs["C1"]["node"] == "支付/放款重试"
    assert confs["C2"]["node"] == "支付/放款重试"  # 模块级×叶 → 最深叶
    assert confs["C3"]["node"] == "__root__"        # 无有效归属 → 全局
    assert confs["C4"]["node"] == "支付/放款重试"   # 已删路径方被跳过
    assert "node" in confs["C5"]                    # 已裁决也带归属（展示用）
    wb = {n["full"]: n for n in (await client.get(f"{BASE}/wb/summary")).json()["tree"]}
    n_open = sum(1 for c in confs.values() if c["st"] == "open" and c["node"] == "支付/放款重试")
    assert wb["支付/放款重试"]["conf"] == n_open
