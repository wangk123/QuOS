# server/app/ai/agent/flow.py —— 四个大输入任务的 agent 组合层（export→runner→ingest）
from pathlib import Path

from app.ai import tasks
from app.ai.agent import export
from app.ai.agent.ingest import ingest_extract, ingest_tree, ingest_verify
from app.storage import findings as findings_store
from app.ai.agent.runner import AgentRunError, run_agent
from app.storage import evidence, jobs, tree
from app.storage import rules as rule_store


def _on_event(jid: str | None, text: str):
    if jid:
        jobs.update(jid, label=f"AI 引擎：{text}")


async def _run_flow(d, jid: str | None) -> dict:
    """跑 agent 并在失败时保留任务目录现场再抛"""
    try:
        return await run_agent(d, on_event=lambda t: _on_event(jid, t))
    except AgentRunError:
        export.cleanup(d, keep=True)
        raise


async def gen_tree(proj: str, root: Path, jid: str | None) -> list[str]:
    """understand 的 agent 版：材料池全量导出 → 一次运行 → 树+根画像+初始画像入库"""
    evs = [e for e in await evidence.list_all(root) if e.type != "压缩包"]
    body = "材料清单（全部）：\n" + "\n".join(f"- {e.name}（{e.type}）" for e in evs)
    d = await export.build_task_dir(root, evs, "tree-gen", body)
    data = await _run_flow(d, jid)
    if not data.get("nodes"):
        export.cleanup(d, keep=True)
        raise AgentRunError("AI 未归纳出结构")
    warns = await ingest_tree(root, data, d)
    export.cleanup(d)
    return warns


async def extract_one(root: Path, ev, jid: str | None = None) -> int:
    """extract 的 agent 版：单材料提取+自核验一体（TASK.md 附树白名单）；返回新增条数"""
    paths = tree.paths(tree.load(root))
    body = (f"目标材料：{ev.name}（manifest 中 id={ev.id}，只处理这一份）\n\n"
            "树节点全路径白名单（node 只能从中选，找不到合适的留空）：\n"
            + ("\n".join(f"- {p}" for p in paths) if paths else "（空树：全部留空）"))
    d = await export.build_task_dir(root, [ev], "extract", body)
    data = await _run_flow(d, jid)
    n = await ingest_extract(root, ev, data, d)
    await evidence.mark_extracted(root, ev.id, n)
    export.cleanup(d)
    return n


async def verify_all(root: Path, ids: list[str], only_doc: bool, jid: str) -> None:
    """verify 的 agent 版：一次运行 = 待核验规则 × 材料池（不分批）。
    失败兜底置 job failed 后 re-raise——create_task 裸跑的编排点无人收异常，job 不得卡 running"""
    evs = [e for e in await evidence.list_all(root) if e.type != "压缩包"]
    items = rule_store.load(root)
    targets = [a for a in items if a.id in set(ids)]
    rules_text = "\n".join(f"- {a.id} | {a.text}" for a in targets) or "（无）"
    scope = "（只核文档/实证级；推测级已在清单外）" if only_doc else ""
    body = (f"待核验规则清单{scope}：\n{rules_text}\n\n"
            "材料范围：materials/ 全部（在池材料）")
    d = await export.build_task_dir(root, evs, "verify", body)
    try:
        data = await _run_flow(d, jid)
        stat = ingest_verify(items, data, d)
        rule_store.save(root, items)
        jobs.update(jid, ok=stat["ok"], corrected=stat["corrected"], nobasis=stat["nobasis"])
        jobs.finish(jid)
    except Exception as e:
        jobs.update(jid, status="failed", label=f"agent 核验失败：{str(e)[:60]}")
        raise




async def resolve_doubts(root: Path, jid: str | None) -> dict:
    """智能生成 ③ 阶段：遗留 open 冲突+缺口 × 全池材料 → ATD 运行 → _apply_resolve 落库
    （off 引擎由编排层直接调 tasks.resolve_doubts，不经此函数）"""
    evs = [e for e in await evidence.list_all(root) if e.type != "压缩包"]
    confs = [c for c in findings_store.load_conflicts(root) if c.st == "open"]
    gaps = [g for g in findings_store.load_gaps(root) if g.st == "open"]
    if not confs and not gaps:
        return {"auto_resolved": [], "auto_closed": []}
    rmap = {a.id: a for a in rule_store.load(root)}
    body = ("遗留冲突清单（信某方须材料明确依据）：\n"
            + "\n".join(f"- {c.id} | {c.q} | 各方："
                        + " / ".join(f"{x}={rmap[x].text if x in rmap else x}" for x in c.parties)
                        for c in confs)
            + "\n\n遗留缺口清单：\n"
            + "\n".join(f"- {g.id} | {g.dim} | {g.text}" for g in gaps))
    d = await export.build_task_dir(root, evs, "resolve-doubts", body)
    try:
        data = await _run_flow(d, jid)
        out = tasks.ResolveDoubtsOut.model_validate(data)
        from app.api.router import _apply_resolve, _evidence_texts
        material = "\n\n".join(t for t, _ in await _evidence_texts(root))
        return await _apply_resolve(root, out, material)
    except AgentRunError:
        export.cleanup(d, keep=True)
        raise
    export.cleanup(d)
