# server/app/api/doubts.py —— 存疑汇总读侧聚合（需求②）：全项目矛盾/缺口按顶层模块归位 + 全局区。
# router.py 已 850+ 行（拆分是已登记债务）：新聚合端点独立成文件。
from fastapi import APIRouter

from app.api.router import _in_subtree, _load_tree, _root, _rule_map, _void_ids
from app.storage import findings, rules as rule_store

api_router = APIRouter()


def _top(full: str) -> str:
    """树全路径 → 顶层模块名（第一段）；空串原样返回"""
    return full.split("/", 1)[0]


@api_router.get("/doubts/summary")
async def doubts_summary(proj: str):
    """根详情「存疑汇总」卡数据源：统计条（open 计数）+ 全局缺口（node=__root__/空）+ 模块分组行。
    矛盾归属沿用 wb_summary 口径（a/b 规则 node 推导，查不到归属不过滤防漏）；行序=树序。"""
    root = _root(proj)
    nodes = _load_tree(root)
    gaps = findings.load_gaps(root)
    confs = findings.load_conflicts(root)
    rmap = _rule_map(root)
    void = _void_ids(root)
    rules = [a for a in rule_store.load(root) if a.id not in void]

    def conf_node(c) -> str:
        return next((rmap[x].node for x in (c.a, c.b) if x in rmap), "")

    mods = {n.name for n in nodes}  # 顶层模块名集合（树序由下方遍历保证）
    rows: list[dict] = []
    g_open = [g for g in gaps if g.st == "open"]
    c_open = [c for c in confs if c.st == "open"]
    for n in nodes:
        mg = [g for g in g_open if _in_subtree(g.node, n.name)]
        mc = [c for c in c_open if _in_subtree(conf_node(c), n.name)]
        rows.append({"name": n.name,
                     "rules": sum(1 for a in rules if _in_subtree(a.node, n.name)),
                     "conflicts": len(mc), "gaps": len(mg),
                     "peek": mg[0].text if mg else (mc[0].q if mc else "")})
    glob = [{"id": g.id, "dim": g.dim, "text": g.text, "st": g.st}
            for g in g_open if _top(g.node) not in mods]
    return {"stats": {"conflicts": len(c_open), "gaps": len(g_open),
                      "clarified": sum(1 for c in confs if c.st == "clar")
                      + sum(1 for g in gaps if g.st == "clar")},
            "global": glob, "modules": rows}
