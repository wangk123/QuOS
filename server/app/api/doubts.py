# server/app/api/doubts.py —— 存疑汇总读侧聚合（需求②）：全项目矛盾/缺口按顶层模块归位 + 全局区。
# 归属与 wb_summary 同源（router._conflict_node/_gap_node 唯一实现，见 tests/test_badge_consistency.py 恒等式）。
from fastapi import APIRouter

from app.api.router import (_conflict_node, _gap_node, _in_subtree, _load_tree, _root,
                            _rule_map, _void_ids)
from app.storage import findings, profiles, rules as rule_store, tree

api_router = APIRouter()


@api_router.get("/doubts/summary")
async def doubts_summary(proj: str):
    """根详情「存疑汇总」卡数据源：统计条（open 计数）+ 全局区（缺口与冲突）+ 模块分组行（与树行同口径）"""
    root = _root(proj)
    nodes = _load_tree(root)
    gaps = findings.load_gaps(root)
    confs = findings.load_conflicts(root)
    rmap = _rule_map(root)
    void = _void_ids(root)
    valid = set(tree.paths(nodes))
    rules = [a for a in rule_store.load(root) if a.id not in void]

    g_open = [g for g in gaps if g.st == "open"]
    c_open = [c for c in confs if c.st == "open"]
    g_node = lambda g: _gap_node(g, valid)  # noqa: E731
    c_node = lambda c: _conflict_node(c, rmap, valid)  # noqa: E731

    rows: list[dict] = []
    for n in nodes:
        mg = [g for g in g_open if _in_subtree(g_node(g), n.name)]
        mc = [c for c in c_open if _in_subtree(c_node(c), n.name)]
        rows.append({"name": n.name,
                     # rules 与 wb 同口径：void/孤儿路径不进（wb stat 的 valid 白名单恒等）
                     "rules": sum(1 for a in rules if a.node in valid and _in_subtree(a.node, n.name)),
                     "conflicts": len(mc), "gaps": len(mg),
                     "peek": mg[0].text if mg else (mc[0].q if mc else "")})
    root_node = profiles.ROOT_NODE
    glob = [{"id": g.id, "dim": g.dim, "text": g.text, "st": g.st}
            for g in g_open if g_node(g) == root_node]
    glob_c = [{"id": c.id, "q": c.q, "st": c.st}
              for c in c_open if c_node(c) == root_node]
    return {"stats": {"conflicts": len(c_open), "gaps": len(g_open),
                      "clarified": sum(1 for c in confs if c.st == "clar")
                      + sum(1 for g in gaps if g.st == "clar")},
            "global": glob, "globalConflicts": glob_c, "modules": rows}
