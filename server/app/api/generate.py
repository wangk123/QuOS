# server/app/api/generate.py —— 生成/重生成编排（router.py 已 821 行，编排逻辑独立成文件）
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ai import tasks
from app.api.router import (AssembleIn, CLAR_BATCH, REVIEW_IMG_CAP, REVIEW_TEXT_CAP, ReviewIn, _ai,
                            _evidence_parts, _evidence_texts, _load_tree, _review_batches, _root,
                            _run_extract_verify, _to_tree_nodes, assemble_profile, rescan_conflicts,
                            rescan_gaps)
from app.storage import clarifications, evidence, jobs, profiles, rules as rule_store, tree

api_router = APIRouter()

_MODES = ("partial", "rescan", "full")


def _safe_mode(mode: str) -> str:
    """mode 白名单校验（纯函数）：AI 或用户传入编造值一律落 partial（最保守的局部重生成）"""
    return mode if mode in _MODES else "partial"


def _walk_initial_profiles(items, prefix: str = ""):
    """understand 骨架 → (全路径, kind, goal)：每个树节点都存初始画像（推测级一句话），
    树上一句话=节点画像 goal——组装未跑/被闸门拦下时树上也有语义"""
    for n in items:
        full = f"{prefix}/{n.name}" if prefix else n.name
        yield full, ("module" if n.children else "leaf"), n.goal
        yield from _walk_initial_profiles(n.children, full)


async def _run_generate(proj: str, jid: str) -> None:
    """顶层兜底：understand/rescan 等裸调抛错（AITaskError/502 等）不再让后台 task 静默死亡、
    job 永久卡 running 占死并发位——统一置 failed；cancelled 是终态不覆写"""
    try:
        await _run_generate_inner(proj, jid)
    except Exception as e:
        if not jobs.is_cancelled(jid):
            jobs.update(jid, status="failed", label=f"生成失败：{str(e)[:80]}")


async def _run_generate_inner(proj: str, jid: str) -> None:
    root = _root(proj)
    # phase1 outline：树空时 understand 落树+根画像草稿（全部推测级）
    if not _load_tree(root):
        jobs.update(jid, phase="outline", label="正在梳理需求大纲…", cur=1, total=6)
        parts = await _evidence_texts(root)
        material = "\n\n".join(t[:8000] for t, _ in parts)[:60000]
        images = [b for _, imgs in parts for (_, b) in imgs][:5]
        out = await tasks.understand(material, images=images)
        if not out.nodes:  # 空骨架：不落树不留脏数据，直接判失败
            if jobs.is_cancelled(jid):
                return
            jobs.update(jid, status="failed", label="AI 未归纳出结构，请补充材料后重试")
            return
        tree.save(root, _to_tree_nodes(out.nodes))
        profiles.save_profile(root, profiles.ROOT_NODE, profiles.Profile(
            node=profiles.ROOT_NODE, kind="root", goal=out.root.goal, entry=out.root.entry,
            flow=out.root.flow, boundaries=out.root.boundaries, note=out.root.note))
        for full, kind, goal in _walk_initial_profiles(out.nodes):
            profiles.save_profile(root, full, profiles.Profile(node=full, kind=kind, goal=goal))
    # phase2 extract+verify：复用既有「提取+AI 核验」一体链（跳过已提取材料：断点恢复幂等）
    ev_ids = [e.id for e in await evidence.list_all(root)
              if e.type != "压缩包" and e.state != "extracted"]
    if jobs.is_cancelled(jid):
        return
    jobs.update(jid, phase="extract", label="正在读材料提炼并核验条目…")
    await _run_extract_verify(proj, jid, ev_ids)
    if jobs.is_cancelled(jid):
        return
    # phase3 conflict（复用既有 handler，本仓库既有做法）；status 拉回 running——复用链尾部自带 finish
    jobs.update(jid, status="running", phase="conflict", label="正在核对来源与矛盾…", total=6)
    await rescan_conflicts(proj)
    # phase4 assemble：逐叶组装，409（无规则/未核验）细分跳过——闸门数据化
    lv = tree.leaves(_load_tree(root))
    for i, (digits, full) in enumerate(lv, 1):
        if jobs.is_cancelled(jid):
            return
        jobs.update(jid, phase="assemble", label=f"正在完善「{full}」",
                    current_node=full, cur=i, total=len(lv))
        try:
            await assemble_profile(proj, AssembleIn(node_path=digits, note=""))
            jobs.bump(jid, "done_nodes", full)
            jobs.bump(jid, "ok")
        except HTTPException as e:
            if e.status_code == 409:
                jobs.bump(jid, "blocked", full)
            else:
                jobs.bump(jid, "failed")
    # phase5 gap
    if jobs.is_cancelled(jid):
        return
    jobs.update(jid, phase="gap", label="正在汇总需求画像…")
    await rescan_gaps(proj)
    if jobs.is_cancelled(jid):  # cancel 落在 gap 执行窗口：不得覆写为 done
        return
    jobs.finish(jid)


@api_router.post("/generate")
async def generate(proj: str):
    root = _root(proj)
    if jobs.running():
        raise HTTPException(409, f"已有任务进行中（{jobs.running()['label']}）")
    if not await evidence.list_all(root):
        raise HTTPException(422, "证据池是空的——先导入材料")
    if _load_tree(root):
        raise HTTPException(409, "需求已生成——补充材料请走「重新生成」")
    jid = jobs.create("generate", "生成需求", 6)
    asyncio.create_task(_run_generate(proj, jid))
    return {"job_id": jid, "total": 6}


@api_router.post("/generate/cancel")
async def generate_cancel(proj: str):
    j = jobs.running()
    if j and j["kind"] in ("generate", "regen"):
        jobs.cancel(j["id"])
    return {"status": "cancelled"}


# ---------- 重生成（三模式：局部组装 / 待确认重扫 / 全量） ----------

class RegenIn(BaseModel):
    mode: str
    ev_ids: list[str] = []
    nodes: list[str] = []  # partial 模式的局部组装目标（树全路径；默认取 impact 建议的 nodes）


def _digit_map(nodes, digits: str = "", prefix: str = "") -> dict[str, str]:
    """树全路径 → 数字路径（assemble 按 node_path 寻址）"""
    out: dict[str, str] = {}
    for i, n in enumerate(nodes):
        d = f"{digits},{i}" if digits else str(i)
        full = f"{prefix}/{n.name}" if prefix else n.name
        out[full] = d
        out.update(_digit_map(n.children, d, full))
    return out


def _child_map(nodes, prefix: str = "") -> dict[str, list[str]]:
    """父全路径（""=树根）→ 直接子节点全路径——summary 聚合的 parts 取材范围"""
    out: dict[str, list[str]] = {}
    for n in nodes:
        full = f"{prefix}/{n.name}" if prefix else n.name
        out.setdefault(prefix, []).append(full)
        out.update(_child_map(n.children, full))
    return out


def _ancestors(full: str) -> list[str]:
    segs = full.split("/")
    return ["/".join(segs[:i]) for i in range(1, len(segs))]


async def _review_material(root, ev_ids: list[str]) -> tuple[str, list[bytes], bool]:
    """重扫取材：选中材料的文本拼接（超长截断）+ 图片限量——与 /clarifications/review 同口径"""
    evs = []
    for eid in ev_ids:
        e = await evidence.get(root, eid)
        if e is not None:
            evs.append(e)
    parts = [_evidence_parts(root, e) for e in evs]
    images = [b for _, imgs in parts for (_, b) in imgs][:REVIEW_IMG_CAP]
    text = "\n\n".join(t for t, _ in parts if t)
    truncated = len(text) > REVIEW_TEXT_CAP
    return text[:REVIEW_TEXT_CAP], images, truncated


async def _rescan_waits(proj, jid, root, ev_ids) -> None:
    """对全部 wait 题 AI 代答（复用重检分批循环体；题级过滤只增复杂度且重扫无害）"""
    waits = [c for c in await clarifications.list_all(root) if c.st == "wait"]
    if not waits:
        jobs.update(jid, label="没有待问问题，无需重扫")
        return
    text, images, truncated = await _review_material(root, ev_ids)
    answered = await _review_batches(proj, jid, root, waits, text, images, ev_ids, truncated)
    jobs.update(jid, ok=answered)


async def _regen_summaries(root, jid, affected: list[str]) -> None:
    """受影响节点的祖先模块 + 根做 summary 聚合重生成（先深后浅、root 最后——父级 parts 能吃到刚更新的子画像）；
    parts=子节点画像「名称：goal｜主流程首行」，写回只覆写 goal/entry/boundaries/note（flow 等原值不动）"""
    children = _child_map(_load_tree(root))
    modules = sorted({a for full in affected for a in _ancestors(full)},
                     key=lambda p: p.count("/"), reverse=True)
    for target in [*modules, profiles.ROOT_NODE]:
        if jobs.is_cancelled(jid):
            return
        kids = children.get("" if target == profiles.ROOT_NODE else target, [])
        parts = []
        for kid in kids:
            p = profiles.load_profile(root, kid)
            if p is None:
                continue
            parts.append(f"{kid}：{p.goal}｜{p.flow.splitlines()[0] if p.flow else ''}")
        if not parts:
            continue
        kind = "root" if target == profiles.ROOT_NODE else "module"
        jobs.update(jid, label=f"正在汇总「{'根画像' if kind == 'root' else target}」")
        out = await _ai(tasks.summary, "\n".join(parts), kind)
        card = profiles.load_profile(root, target) or profiles.Profile(node=target, kind=kind)
        card.kind = kind
        card.goal, card.entry, card.boundaries, card.note = out.goal, out.entry, out.boundaries, out.note
        profiles.save_profile(root, target, card)


async def _run_regen(proj: str, jid: str, mode: str, ev_ids: list[str], nodes: list[str]) -> None:
    """与 _run_generate 同款异常兜底：分支裸调抛错统一置 failed，不占死并发位"""
    try:
        await _run_regen_inner(proj, jid, mode, ev_ids, nodes)
    except Exception as e:
        if not jobs.is_cancelled(jid):
            jobs.update(jid, status="failed", label=f"重生成失败：{str(e)[:80]}")


async def _run_regen_inner(proj: str, jid: str, mode: str, ev_ids: list[str], nodes: list[str]) -> None:
    root = _root(proj)
    if mode == "full":
        await _run_generate_inner(proj, jid)  # 同 generate 壳语义：树非空仅跳过 outline，其余全跑
        return
    if mode == "rescan":
        await _rescan_waits(proj, jid, root, ev_ids)
        jobs.finish(jid)
        return
    # partial：⓪ 新材料（未提取的）先过「提取+核验」一体链（与 generate phase2 同款：跳过已提取材料，
    # 幂等断点恢复；复用链尾部自带 finish 会置 done——照 generate 的做法拉回 running）
    pending = [e.id for e in await evidence.list_all(root)
               if e.type != "压缩包" and e.state != "extracted"]
    if pending:
        jobs.update(jid, phase="extract", label="正在读新材料提炼并核验条目…")
        await _run_extract_verify(proj, jid, pending)
        if jobs.is_cancelled(jid):
            return
        jobs.update(jid, status="running")
    # ① 逐节点局部组装（assemble 输入本就不改规则 → verified 天然保留；409 细分 blocked）
    dmap = _digit_map(_load_tree(root))
    for n in nodes:
        if n not in dmap:
            jobs.bump(jid, "skipped", n)
    targets = [n for n in nodes if n in dmap]
    for i, full in enumerate(targets, 1):
        if jobs.is_cancelled(jid):
            return
        jobs.update(jid, phase="assemble", label=f"正在完善「{full}」",
                    current_node=full, cur=i, total=len(targets))
        try:
            await assemble_profile(proj, AssembleIn(node_path=dmap[full], note=""))
            jobs.bump(jid, "done_nodes", full)
            jobs.bump(jid, "ok")
        except HTTPException as e:
            if e.status_code == 409:
                jobs.bump(jid, "blocked", full)
            else:
                jobs.bump(jid, "failed")
    # ② 受影响待确认重扫（全部 wait 题）
    if jobs.is_cancelled(jid):
        return
    jobs.update(jid, phase="clar", label="正在重扫待确认问题…", cur=0)
    await _rescan_waits(proj, jid, root, ev_ids)
    # ③ 受影响模块/根 summary 聚合重生成
    if jobs.is_cancelled(jid):
        return
    jobs.update(jid, phase="summary", label="正在汇总模块与根画像…")
    await _regen_summaries(root, jid, targets)
    jobs.finish(jid)


@api_router.post("/regen")
async def regen(proj: str, body: RegenIn):
    """重生成三模式：full=同 generate 但树非空不拦；partial=局部组装+待确认重扫+模块/根 summary；
    rescan=仅对 wait 题 AI 代答。mode 过白名单（编造值落 partial）"""
    root = _root(proj)
    if jobs.running():
        raise HTTPException(409, f"已有任务进行中（{jobs.running()['label']}）")
    if not body.ev_ids:
        raise HTTPException(422, "未选择重生成材料")
    for eid in body.ev_ids:
        if await evidence.get(root, eid) is None:
            raise HTTPException(404, detail=f"证据不存在: {eid}")
    mode = _safe_mode(body.mode)
    waits = [c for c in await clarifications.list_all(root) if c.st == "wait"] if mode == "rescan" else []
    total = {"partial": max(1, len(body.nodes)) + 2,
             "rescan": max(1, (len(waits) + CLAR_BATCH - 1) // CLAR_BATCH),
             "full": 6}[mode]
    jid = jobs.create("regen", {"partial": "局部重生成", "rescan": "待确认重扫", "full": "全量重生成"}[mode], total)
    asyncio.create_task(_run_regen(proj, jid, mode, body.ev_ids, body.nodes))
    return {"job_id": jid, "mode": mode, "total": total}


async def _summary_regen_all(root) -> list[str]:
    """全量 summary 重聚合：先深后浅（父级 parts 能吃到刚更新的子画像），root 最后；
    写回只覆写 goal/entry/boundaries/note（flow 等原值不动）——与 _regen_summaries 同口径"""
    children = _child_map(_load_tree(root))
    modules = sorted((k for k in children if k), key=lambda p: p.count("/"))
    updated: list[str] = []
    for target in [*modules, profiles.ROOT_NODE]:
        kids = children.get("" if target == profiles.ROOT_NODE else target, [])
        parts = []
        for kid in kids:
            p = profiles.load_profile(root, kid)
            if p is None:
                continue
            parts.append(f"{kid}：{p.goal}｜{p.flow.splitlines()[0] if p.flow else ''}")
        if not parts:
            continue
        kind = "root" if target == profiles.ROOT_NODE else "module"
        out = await _ai(tasks.summary, "\n".join(parts), kind)
        card = profiles.load_profile(root, target) or profiles.Profile(node=target, kind=kind)
        card.kind = kind
        card.goal, card.entry, card.boundaries, card.note = out.goal, out.entry, out.boundaries, out.note
        profiles.save_profile(root, target, card)
        updated.append(target)
    return updated


@api_router.post("/summary/regen")
async def summary_regen(proj: str):
    """根卡 ↻ 摘要：对全部模块画像 + 根同步重聚合写回（目标少秒级完成，不 job 化；
    深浅序保证父级汇总吃到最新子画像；并发由全局 job 位 409 拦）"""
    root = _root(proj)
    if jobs.running():
        raise HTTPException(409, f"已有任务进行中（{jobs.running()['label']}）")
    if not _load_tree(root):
        raise HTTPException(422, "功能树为空——请先生成需求")
    updated = await _summary_regen_all(root)
    return {"updated": updated}


@api_router.post("/regen/impact")
async def regen_impact(proj: str, body: ReviewIn):
    """材料级影响分析：新材料全文 × 现有条目/待确认清单 → 受影响范围 + 重生成方案建议；
    AI 产出的 nodes/rule_ids/clar_nos 逐项防幻觉过滤（失配丢弃），mode 过白名单"""
    root = _root(proj)
    if not body.ev_ids:
        raise HTTPException(422, "未选择新材料")
    evs = []
    for eid in body.ev_ids:
        ev = await evidence.get(root, eid)
        if ev is None:
            raise HTTPException(404, detail=f"证据不存在: {eid}")
        evs.append(ev)
    new_text = "\n\n".join(t for t, _ in (_evidence_parts(root, e) for e in evs) if t)
    items = rule_store.load(root)
    rules_text = "\n".join(f"- {a.id} | {a.node or '（未归类）'} | {a.text}" for a in items) or "（暂无条目）"
    waits = [c for c in await clarifications.list_all(root) if c.st == "wait"]
    clars_text = "\n".join(f"- Q{c.no} | {c.q}" for c in waits) or "（暂无待确认问题）"
    out = await _ai(tasks.impact_analysis, new_text, rules_text, clars_text)
    valid_nodes, valid_rules, valid_nos = (
        set(tree.paths(_load_tree(root))), {a.id for a in items}, {f"Q{c.no}" for c in waits})
    return {**out.model_dump(),
            "nodes": [n for n in out.nodes if n in valid_nodes],
            "rule_ids": [r for r in out.rule_ids if r in valid_rules],
            "clar_nos": [q for q in out.clar_nos if q in valid_nos],
            "recommend": _safe_mode(out.mode)}
