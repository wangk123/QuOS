# server/app/api/router.py
import asyncio
import json
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.ai import tasks
from app.ai.runner import AITaskError
from app.ai.agent import engine_on
from app.ai.agent import flow as agent_flow
from app.ai.tasks import AssembleBlocked
from app.core.classify import classify_file, classify_text
from app.core.models import AiReview
from app.core.parse import pdf_text, shrink_image

from app.storage import clarifications, dims, evidence, findings, gitops, jobs, profiles, project, rules as rule_store, tree
from app.storage.project import is_valid_name, project_root

api_router = APIRouter()


class VerifyIn(BaseModel):
    assert_id: Optional[str] = None


class ConflictIn(BaseModel):
    id: str
    action: str
    side: Optional[str] = None


class GapIn(BaseModel):
    id: str
    action: str


class DimsIn(BaseModel):
    dims: list


class TreeIn(BaseModel):
    op: str
    path: Optional[str] = None
    name: Optional[str] = None


_PRIO = {"", "P0", "P1", "P2"}


class AssembleIn(BaseModel):
    node_path: str
    note: str = ""


class GoalIn(BaseModel):
    goal: str


class ClarIn(BaseModel):
    no: int
    action: str  # answer | adopt | ignore | verify
    idx: Optional[int] = None
    text: Optional[str] = None
    ev_ids: Optional[list[str]] = None
    extra: Optional[str] = None  # confirm 选「与实际不符」的实际行为补充


class BaselineIn(BaseModel):
    note: str = "基线存档"


class NodeIn(BaseModel):
    node: str


class AskIn(BaseModel):
    q: str = ""  # 自定义问法；空 = 默认拼接问法（「该推测与实际系统一致吗？」）


def _root(proj: str) -> Path:
    """项目根目录；非法名 422（防路径遍历），项目不存在或已归档 404（防拼错 URL 凭空建目录）"""
    if not is_valid_name(proj):
        raise HTTPException(status_code=422, detail=f"非法项目名: {proj}")
    root = project_root(proj)
    if not root.resolve().is_relative_to(Path(project.DATA_DIR).resolve()):
        raise HTTPException(status_code=422, detail=f"非法项目名: {proj}")
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"项目不存在或已归档: {proj}")
    return root


def _load_tree(root):
    try:
        return tree.load(root)
    except tree.TreeFormatError as e:
        raise HTTPException(status_code=422, detail=str(e))


async def _ai(fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except AssembleBlocked as e:
        raise HTTPException(status_code=409, detail={"unqualified": [a.id for a in e.unqualified]})
    except AITaskError as e:
        raise HTTPException(status_code=502, detail=f"AI 任务失败: {e}")


def _resolve(nodes, path: str):
    """数字 path → (node, 全名路径)；非数字段 422，越界返回 (None, None)"""
    try:
        node = tree.find(nodes, path)
        segs = [int(s) for s in path.split(",")]
    except ValueError:
        raise HTTPException(status_code=422, detail=f"非法路径: {path}")
    if node is None:
        return None, None
    layer, names = nodes, []
    for i in segs:
        names.append(layer[i].name)
        layer = layer[i].children
    return node, "/".join(names)


def _docx_text(f: Path) -> str:
    """docx = zip 包内的 XML：剥标签取正文（零依赖；解析失败退回原文错误）"""
    import re
    import zipfile
    with zipfile.ZipFile(f) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _evidence_parts(root, ev) -> tuple[str, list[tuple[str, bytes]]]:
    """(文本, [(mime, 图片字节)])；文本类只出文本，图片只出图，仓库/压缩包退回名称"""
    if ev.path:
        f = Path(root) / ev.path
        if f.exists():
            suf = f.suffix.lower()
            if suf == ".docx":
                return _docx_text(f), []
            if suf == ".pdf":
                return pdf_text(f), []
            if suf in _IMG_EXT:
                return "", [("image/jpeg", shrink_image(f))]
            return f.read_text("utf-8", errors="replace"), []
    return ev.name, []


async def _evidence_texts(root, evs=None) -> list[tuple[str, list[tuple[str, bytes]]]]:
    evs = evs if evs is not None else await evidence.list_all(root)
    return [_evidence_parts(root, e) for e in evs]


def _rule_map(root) -> dict:
    return {a.id: a for a in rule_store.load(root)}


# ---------- 证据 ----------

@api_router.get("/evidence")
async def list_evidence(proj: str):
    return [e.model_dump() for e in await evidence.list_all(_root(proj))]


@api_router.post("/evidence")
async def add_evidence(proj: str, request: Request):
    root = _root(proj)
    source = request.query_params.get("source")
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(status_code=422, detail="body 不是合法 JSON")
        raw = (body or {}).get("raw") if isinstance(body, dict) else None
        if not isinstance(raw, str) or not raw.strip():
            raise HTTPException(status_code=422, detail="body.raw 必须为非空文本")
        payload = classify_text(raw)
        if source == "clar":
            payload["source"] = "clar"
        ev = await evidence.add(root, payload, content=raw.encode("utf-8"))
    else:
        data = await request.body()
        if not data:
            raise HTTPException(status_code=422, detail="请求体为空")
        # 前端以 encodeURIComponent 传 X-Filename，解码还原中文/空格
        name = unquote(request.headers.get("x-filename") or request.query_params.get("filename") or "upload.bin")
        payload = {"type": classify_file(name), "name": Path(name).name,
                   "ext": Path(name).suffix.lstrip("."), "stars": 2}
        if source == "clar":
            payload["source"] = "clar"
        ev = await evidence.add(root, payload, content=data)
    return ev.model_dump()


async def _extract_one(root, ev) -> int:
    """提取单份证据并落盘（重提替换、白名单归属）；返回新增条数。
    agent 引擎启用时整段走 flow（提取+自核验一体）"""
    if engine_on():
        return await agent_flow.extract_one(root, ev)
    nodes = _load_tree(root)
    paths_list = tree.paths(nodes)
    valid = set(paths_list)
    text, images = _evidence_parts(root, ev)
    if not text and not images:
        raise HTTPException(status_code=422, detail="该材料没有可提取文本（扫描件请转图片入池）")
    img_kwargs = {"images": [b for _, b in images]} if images else {}
    got = await _ai(tasks.extract, text, ev.type, "\n".join(paths_list) or "（空树：全部留空）", **img_kwargs)
    items = [a for a in rule_store.load(root) if a.src_id != ev.id]  # 重提：替换上次产出
    n = max((int(a.id[1:]) for a in items if a.id.startswith("R") and a.id[1:].isdigit()), default=0)
    for a in got:
        n += 1
        if a.node not in valid:  # AI 编造路径 → 白名单外置空（未归类）
            a.node = ""
        items.append(a.model_copy(update={"id": f"R{n}", "src_id": ev.id}))
    rule_store.save(root, items)
    await evidence.mark_extracted(root, ev.id, len(got))
    return len(got)


@api_router.post("/evidence/{ev_id}/extract")
async def extract_evidence(proj: str, ev_id: str):
    root = _root(proj)
    ev = await evidence.get(root, ev_id)
    if ev is None:
        raise HTTPException(status_code=404, detail=f"证据不存在: {ev_id}")
    if ev.type == "压缩包":
        raise HTTPException(status_code=422, detail="该类型不支持 AI 提取（M1.x 支持解析）")
    added = await _extract_one(root, ev)
    return {"added": added}


@api_router.post("/evidence/extract-job")
async def extract_job(proj: str):
    """提取+核验后台任务（两阶段）：逐份提取 pending 证据 → 自动分批核验全部未核验规则。
    长流程（多份材料分钟级）不走单请求；进度由 GET /jobs 轮询，刷新可恢复。"""
    root = _root(proj)
    if jobs.running():
        r = jobs.running()
        raise HTTPException(status_code=409, detail=f"已有任务进行中（{r['label']}，{r['cur']}/{r['total']}）")
    pend = [e for e in await evidence.list_all(root) if e.state == "pending" and e.type != "压缩包"]
    if not pend:
        raise HTTPException(status_code=422, detail="池中没有可提取的新材料")
    jid = jobs.create("extract-verify", "提取池中材料", len(pend))
    asyncio.create_task(_run_extract_verify(proj, jid, [e.id for e in pend]))
    return {"job_id": jid, "total": len(pend)}


async def _run_extract_verify(proj: str, jid: str, ev_ids: list[str]) -> None:
    """阶段一：逐份提取（cur/total=份数）；阶段二：复用核验分批逻辑（cur/total 重置为批数）"""
    extracted = 0
    for i, ev_id in enumerate(ev_ids, 1):
        try:
            root = _root(proj)
            ev = await evidence.get(root, ev_id)
            if ev is None:
                continue
            jobs.update(jid, cur=i, label=f"AI 正在读《{ev.name}》提炼行为规则")
            extracted += await _extract_one(root, ev)
        except Exception:
            jobs.update(jid, failed=jobs.get(jid).get("failed", 0) + 1)
    root = _root(proj)
    # 提取全军覆没且无存量规则：置 failed 终态——不再空跑核验，产出「树有骨架、条目全 0」的假完成
    if extracted == 0 and not rule_store.load(root) and (jobs.get(jid) or {}).get("failed"):
        jobs.update(jid, status="failed",
                    label=f"材料提取全部失败（{jobs.get(jid)['failed']} 份）——AI 调用超时或输出异常，请重试")
        return
    ids = [a.id for a in rule_store.load(root) if not a.verified]
    if not ids:
        jobs.update(jid, extracted=extracted)
        jobs.finish(jid)
        return
    total = (len(ids) + VERIFY_BATCH - 1) // VERIFY_BATCH
    jobs.update(jid, total=total, cur=0, extracted=extracted, ok=0, corrected=0, nobasis=0, failed=jobs.get(jid).get("failed", 0))
    await _run_verify_phase(proj, jid, ids)


async def _run_verify_phase(proj: str, jid: str, ids: list[str], only_doc: bool = False) -> None:
    """分批核验落盘并累计三路计数（verify-job 与 extract-verify 阶段二共用）；
    only_doc=跳过推测级规则（推测无材料依据，核验必然落「无依据」——只核文档/实证级）。
    agent 引擎启用时一次运行不分批（flow 自带失败兜底与 finish）"""
    if engine_on():
        try:
            await agent_flow.verify_all(_root(proj), ids, only_doc, jid)
        except Exception:
            pass  # flow 内部已置 job failed——吞掉防 create_task 裸跑告警
        return
    root = _root(proj)
    material = "\n\n".join(t for t, _ in await _evidence_texts(root))
    for i in range(0, len(ids), VERIFY_BATCH):
        batch = ids[i:i + VERIFY_BATCH]
        jobs.update(jid, cur=i // VERIFY_BATCH + 1, label=f"AI 全量核验 · 第 {i + 1}-{min(i + VERIFY_BATCH, len(ids))}/{len(ids)} 条")
        try:
            root = _root(proj)
            items = rule_store.load(root)
            targets = [a for a in items if a.id in set(batch) and not (only_doc and a.conf == "推测")]
            if not targets:
                continue
            out = await _ai(tasks.verify, targets, material)
            stat = _apply_verify_results(items, out.results)
            rule_store.save(root, items)
            jobs.update(jid, ok=jobs.get(jid)["ok"] + stat["ok"],
                        corrected=jobs.get(jid)["corrected"] + stat["corrected"],
                        nobasis=jobs.get(jid)["nobasis"] + stat["nobasis"])
        except Exception:
            jobs.update(jid, failed=jobs.get(jid)["failed"] + len(batch))
    jobs.finish(jid)


@api_router.delete("/evidence/{ev_id}", status_code=204)
async def delete_evidence(proj: str, ev_id: str):
    root = _root(proj)
    if await evidence.get(root, ev_id) is None:
        raise HTTPException(status_code=404, detail=f"证据不存在: {ev_id}")
    await evidence.remove(root, ev_id)
    kept = [a for a in rule_store.load(root) if a.src_id != ev_id]  # 其产出的规则一并移除
    rule_store.save(root, kept)


# ---------- 规则 ----------

@api_router.get("/rules")
async def list_rules(proj: str):
    return [a.model_dump() for a in rule_store.load(_root(proj))]


def _apply_verify_results(items, results) -> dict:
    """核验结果落字段：ok→核过 / corrected_text→标黄修正 / 其余→无依据留人工；返回三路计数"""
    stat = {"ok": 0, "corrected": 0, "nobasis": 0}
    by_id = {a.id: a for a in items}
    for r in results:
        a = by_id.get(r.get("id"))
        if a is None:
            continue
        if r.get("ok") is True:
            a.verified, a.nb = True, ""
            stat["ok"] += 1
        elif r.get("corrected_text"):
            a.text, a.suspect, a.verified, a.nb = r["corrected_text"], True, True, ""
            stat["corrected"] += 1
        else:
            a.nb = r.get("reason") or "材料中无对应依据"  # 推测类规则：留给人工核过/转问人
            stat["nobasis"] += 1
    return stat


@api_router.post("/rules/verify")
async def verify_rules(proj: str, body: VerifyIn):
    """单点核验专用（行内「核」按钮）：全量核验一律走 POST /rules/verify-job 后台任务"""
    root = _root(proj)
    items = rule_store.load(root)
    if not body.assert_id:
        raise HTTPException(status_code=422, detail="本端点仅单点核验；全量核验请用 /rules/verify-job")
    targets = [a for a in items if a.id == body.assert_id]
    if not targets:
        raise HTTPException(status_code=404, detail=f"规则不存在: {body.assert_id}")
    material = "\n\n".join(t for t, _ in await _evidence_texts(root))
    out = await _ai(tasks.verify, targets, material)
    stat = _apply_verify_results(items, out.results)
    rule_store.save(root, items)
    return {"applied": [r.get("id") for r in out.results], "results": out.results, **stat}


VERIFY_BATCH = 20  # 每批核验条数：一次 LLM 调用一批，job 进度按批推进


class VerifyJobIn(BaseModel):
    only_doc: bool = False  # 文档级核验：跳过推测级（推测无材料依据，核也必落「无依据」）


@api_router.post("/rules/verify-job")
async def verify_job(proj: str, body: VerifyJobIn | None = None):
    """全量核验后台任务：分批逐批核验，进度由 GET /jobs 轮询（提取后前端自动链入，也可手动重核）；
    body.only_doc=true 只核文档/实证级（不核推测级）"""
    root = _root(proj)
    if jobs.running():
        r = jobs.running()
        raise HTTPException(status_code=409, detail=f"已有任务进行中（{r['label']}，{r['cur']}/{r['total']}）")
    only_doc = bool(body and body.only_doc)
    ids = [a.id for a in rule_store.load(root) if not a.verified and not (only_doc and a.conf == "推测")]
    if not ids:
        raise HTTPException(status_code=422, detail="没有未核验的规则")
    total = (len(ids) + VERIFY_BATCH - 1) // VERIFY_BATCH
    jid = jobs.create("verify-batch", "AI 全量核验" + ("（文档级）" if only_doc else ""), total)
    asyncio.create_task(_run_verify(proj, jid, ids, only_doc))
    return {"job_id": jid, "total": total, "rules": len(ids)}


async def _run_verify(proj: str, jid: str, ids: list[str], only_doc: bool = False) -> None:
    """verify-job 入口：初始化计数后复用分批公共体（agent 分流在 _run_verify_phase 入口——
    verify-job 与 extract-verify 链尾共用同一段）"""
    jobs.update(jid, ok=0, corrected=0, nobasis=0, failed=0)
    await _run_verify_phase(proj, jid, ids, only_doc)


@api_router.post("/rules/{rid}/confirm", status_code=204)
async def confirm_rule(proj: str, rid: str):
    """人工核过：不经 AI，直接确认该规则与实际一致"""
    root = _root(proj)
    rmap = _rule_map(root)
    if rid not in rmap:
        raise HTTPException(status_code=404, detail=f"规则不存在: {rid}")
    a = rmap[rid]
    a.verified, a.nb, a.clar = True, "", None
    rule_store.save(root, list(rmap.values()))


@api_router.post("/rules/{rid}/ask", status_code=204)
async def ask_rule(proj: str, rid: str, body: AskIn | None = None):
    """转问人：推测/无依据规则进「问人」清单，答案按题型联动：一致核过、不符改写标黄、不清楚不动；body.q 非空时替代默认问法"""
    root = _root(proj)
    rmap = _rule_map(root)
    if rid not in rmap:
        raise HTTPException(status_code=404, detail=f"规则不存在: {rid}")
    a = rmap[rid]
    if a.clar:
        raise HTTPException(status_code=409, detail=f"{rid} 已转问人（问#{a.clar}）")
    custom = (body.q.strip() if body else "") or ""
    if custom:  # 自定义问法：问的是具体事实 → 开放题（type=custom），不再套三连选项
        c = await clarifications.add(root, custom, [], ref=a.id, type="custom")
    else:
        q = a.text + "——该推测与实际系统一致吗？"
        c = await clarifications.add(root, q, ["确认一致", "与实际不符", "不清楚"], ref=a.id, type="confirm")
    a.clar = c.no
    rule_store.save(root, list(rmap.values()))


@api_router.put("/rules/{rid}/node", status_code=204)
async def set_rule_node(proj: str, rid: str, body: NodeIn):
    """人工挂载/改归属：node 必须为空（回未归类）或树中全路径"""
    root = _root(proj)
    rmap = _rule_map(root)
    if rid not in rmap:
        raise HTTPException(status_code=404, detail=f"规则不存在: {rid}")
    if body.node and body.node not in tree.paths(_load_tree(root)):
        raise HTTPException(status_code=422, detail=f"节点不存在: {body.node}")
    rmap[rid].node = body.node
    rule_store.save(root, list(rmap.values()))


# ---------- 矛盾 ----------

@api_router.get("/conflicts")
async def list_conflicts(proj: str):
    return [c.model_dump() for c in findings.load_conflicts(_root(proj))]


@api_router.post("/conflicts/rescan")
async def rescan_conflicts(proj: str):
    root = _root(proj)
    detected = await _ai(tasks.conflict, rule_store.load(root))
    items = findings.merge_conflicts(root, detected)
    return [c.model_dump() for c in items]


@api_router.post("/conflicts")
async def adjudicate_conflict(proj: str, body: ConflictIn):
    root = _root(proj)
    items = findings.load_conflicts(root)
    c = next((x for x in items if x.id == body.id), None)
    if c is None:
        raise HTTPException(status_code=404, detail=f"矛盾不存在: {body.id}")
    if body.action == "code":
        if body.side not in ("a", "b"):
            raise HTTPException(status_code=422, detail="side 必须为 a 或 b")
        c.st, c.resolution = "code", c.a if body.side == "a" else c.b
    elif body.action == "clar":
        c.st = "clar"
        rmap = _rule_map(root)
        opts = [rmap[c.a].text if c.a in rmap else "", rmap[c.b].text if c.b in rmap else ""]
        await clarifications.add(root, c.q, opts, ref=c.id, type="choose")
    else:
        raise HTTPException(status_code=422, detail="action 必须为 code 或 clar")
    findings.save_conflicts(root, items)
    return c.model_dump()


# ---------- 空白 ----------

@api_router.get("/gaps")
async def list_gaps(proj: str):
    return [g.model_dump() for g in findings.load_gaps(_root(proj))]


def _in_subtree(node: str, root_path: str) -> bool:
    """node 是否落在 root_path 节点或其子树内——选父节点 = 包含子节点内容"""
    return node == root_path or node.startswith(root_path + "/")


@api_router.post("/gaps/rescan")
async def rescan_gaps(proj: str, node_path: str = ""):
    root = _root(proj)
    dim_list = dims.get_dims(root)
    nodes = _load_tree(root)
    if node_path:
        node, full = _resolve(nodes, node_path)
        if node is None:
            raise HTTPException(status_code=404, detail=f"节点不存在: {node_path}")
        subtree = [c for c in profiles.load_latest(root) if _in_subtree(c.node, full)]
        if not subtree:
            raise HTTPException(status_code=422, detail=f"该节点及其子树都没有画像，请先生成画像: {node_path}")
        summary = "\n".join(_profile_summary(c) for c in subtree)
    else:
        summary = "\n".join(_profile_summary(c) for c in profiles.load_all(root)) or "（暂无用户画像）"
    detected = await _ai(tasks.gaps, summary, dim_list)
    detected = [g for g in detected if g.dim in dim_list]  # 防 AI 自造维度
    valid_nodes = set(tree.paths(nodes)) | {profiles.ROOT_NODE}
    for g in detected:  # 防 AI 编造节点路径：白名单外置空（=全局）
        if g.node not in valid_nodes:
            g.node = ""
    items = findings.merge_gaps(root, detected)
    return [g.model_dump() for g in items]


def _profile_summary(c) -> str:
    rules = "；".join(r.text for r in c.rules)
    return f"{c.node}：{c.goal}；主流程：{c.flow}；规则：{rules}"


@api_router.post("/gaps")
async def adjudicate_gap(proj: str, body: GapIn):
    root = _root(proj)
    items = findings.load_gaps(root)
    g = next((x for x in items if x.id == body.id), None)
    if g is None:
        raise HTTPException(status_code=404, detail=f"空白不存在: {body.id}")
    if body.action == "clar":
        g.st = "clar"
        await clarifications.add(root, g.text + "？", [], ref=g.id, type="supply")
    elif body.action == "ok":
        g.st = "ok"
    else:
        raise HTTPException(status_code=422, detail="action 必须为 clar 或 ok")
    findings.save_gaps(root, items)
    return g.model_dump()


# ---------- 维度 ----------

@api_router.get("/dims")
async def get_dims(proj: str):
    return dims.get_dims(_root(proj))


@api_router.put("/dims")
async def put_dims(proj: str, body: DimsIn):
    d = body.dims
    if not isinstance(d, list) or not d or not all(isinstance(x, str) and x.strip() for x in d):
        raise HTTPException(status_code=422, detail="dims 必须为非空字符串数组")
    dims.set_dims(_root(proj), d)
    return d


# ---------- 功能树 ----------

@api_router.get("/tree")
async def get_tree(proj: str):
    return [n.model_dump() for n in _load_tree(_root(proj))]


@api_router.post("/tree")
async def mutate_tree(proj: str, body: TreeIn):
    root = _root(proj)
    nodes = _load_tree(root)
    if body.op in ("add", "rename"):
        if not isinstance(body.name, str) or not body.name.strip():
            raise HTTPException(status_code=422, detail="name 必须为非空文本")
        if "\n" in body.name or "\r" in body.name:
            raise HTTPException(status_code=422, detail="name 不允许换行")
    try:
        if body.op == "add":
            if body.path and len(body.path.split(",")) >= 5:
                raise HTTPException(422, detail="节点最多 5 级——过深结构请在既有层级内整理")
            tree.add_node(nodes, body.path or None, body.name)
        elif body.op == "rename":
            if body.path is None:
                raise HTTPException(status_code=422, detail="rename 需要 path")
            tree.rename(nodes, body.path, body.name)
        elif body.op == "del":
            if body.path is None:
                raise HTTPException(status_code=422, detail="del 需要 path")
            tree.delete(nodes, body.path)
        elif body.op == "prio":
            if body.path is None:
                raise HTTPException(status_code=422, detail="prio 需要 path")
            if body.name not in _PRIO:
                raise HTTPException(status_code=422, detail="name 必须为 P0/P1/P2 或空串")
            tree.set_priority(nodes, body.path, body.name)
        else:
            raise HTTPException(status_code=422, detail="op 必须为 add/rename/del/prio")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    tree.save(root, nodes)
    return [n.model_dump() for n in nodes]


def _to_tree_nodes(items) -> list[tree.Node]:
    return [tree.Node(name=i.name, children=_to_tree_nodes(i.children)) for i in items]


@api_router.post("/tree/scaffold")
async def scaffold_tree(proj: str):
    """AI 从证据池生成功能树骨架（仅树空时可用；生成后人工在侧栏调整即采纳）"""
    root = _root(proj)
    if _load_tree(root):
        raise HTTPException(status_code=409, detail="功能树非空，不覆盖——如需调整请在左侧手工编辑")
    texts = [t for e in await evidence.list_all(root) if e.type != "压缩包"
             for (t, imgs) in [_evidence_parts(root, e)] if t]
    if not texts:
        raise HTTPException(status_code=422, detail="证据池没有可提取材料，请先入池")
    material = "\n\n".join(t[:8000] for t in texts)  # 每份截断防超长
    items = await _ai(tasks.outline, material)
    nodes = _to_tree_nodes(items)
    tree.save(root, nodes)
    return [n.model_dump() for n in nodes]


# ---------- 用户画像 ----------

def _void_ids(root) -> set[str]:
    """矛盾裁决信代码侧后，被否定一侧规则视为作废，不得进入组装"""
    return {x for c in findings.load_conflicts(root)
            if c.st == "code" and c.resolution
            for x in (c.a, c.b) if x != c.resolution}


def _parent_goal(root, node_path: str) -> str:
    """父节点（所属模块）画像的 goal——assemble 的父上下文；顶层节点/无画像给空串"""
    _, full = _resolve(_load_tree(root), node_path)
    if not full or "/" not in full:
        return ""
    parent = profiles._latest_profiles(root).get(full.rsplit("/", 1)[0])
    return parent.goal if parent else ""


@api_router.post("/profiles/assemble")
async def assemble_profile(proj: str, body: AssembleIn):
    root = _root(proj)
    nodes = _load_tree(root)
    node, full = _resolve(nodes, body.node_path)
    if node is None:
        raise HTTPException(status_code=404, detail=f"节点不存在: {body.node_path}")
    void = _void_ids(root)
    usable = [a for a in rule_store.load(root) if a.id not in void and _in_subtree(a.node, full)]
    if not usable:
        raise HTTPException(
            status_code=409,
            detail=f"「{full}」及其子树没有已挂载的规则——空规则集只会生成空画像。请先在①规则提取挂载归属（旧数据可在证据池重新提取自动挂载）",
        )
    profile = await _ai(tasks.assemble, usable, node.name, body.note,
                        _parent_goal(root, body.node_path))
    profile.node = full  # 存储按树全路径寻址（load/export 匹配用）
    f = profiles.save_profile(root, full, profile)
    return {"profile": profile.model_dump(), "file": f.name}


@api_router.get("/profiles")
async def list_profiles(proj: str):
    """项目级画像清单（node 全路径）——⑤ 定稿存档页统计「画像 x/功能点」用"""
    return [p.node for p in profiles.load_latest(_root(proj))]


@api_router.get("/profiles/{node_path}")
async def get_profile(proj: str, node_path: str):
    root = _root(proj)
    nodes = _load_tree(root)
    node, full = _resolve(nodes, node_path)
    if node is None:
        raise HTTPException(status_code=404, detail=f"节点不存在: {node_path}")
    card = profiles.load_profile(root, full)
    if card is None:
        raise HTTPException(status_code=404, detail=f"节点无用户画像: {node_path}")
    return card.model_dump()


@api_router.patch("/profiles/{node_path}")
async def patch_profile_goal(proj: str, node_path: str, body: GoalIn):
    """工作台行内编辑 goal：读现有画像（无则建空画像，kind 按树上有无子节点）；__root__ 跳过树校验直接存取"""
    root = _root(proj)
    if node_path == profiles.ROOT_NODE:
        full, kind = profiles.ROOT_NODE, "root"
    else:
        nodes = _load_tree(root)
        node, full = _resolve(nodes, node_path)
        if node is None:
            raise HTTPException(status_code=404, detail=f"节点不存在: {node_path}")
        kind = "module" if node.children else "leaf"
    card = profiles.load_profile(root, full) or profiles.Profile(node=full, kind=kind)
    card.goal = body.goal
    profiles.save_profile(root, full, card)
    return card.model_dump()


@api_router.get("/doc")
async def export_doc(proj: str):
    try:
        text = profiles.export_doc(_root(proj))
    except tree.TreeFormatError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


# ---------- 批量画像（后台任务 + 轮询） ----------

class BatchIn(BaseModel):
    node_path: str = ""  # 空 = 全部叶子；给定 = 该节点子树内的叶子


@api_router.post("/profiles/assemble-batch")
async def assemble_batch(proj: str, body: BatchIn):
    """创建批量画像后台任务，立即返回 job_id——长任务不走单请求（会超时），进度由 GET /jobs 轮询"""
    root = _root(proj)
    if jobs.running():
        r = jobs.running()
        raise HTTPException(status_code=409, detail=f"已有批量任务进行中（{r['label']}，{r['cur']}/{r['total']}）")
    nodes = _load_tree(root)
    lv = tree.leaves(nodes)
    if body.node_path:
        node, full = _resolve(nodes, body.node_path)
        if node is None:
            raise HTTPException(status_code=404, detail=f"节点不存在: {body.node_path}")
        lv = [(d, f) for d, f in lv if f == full or f.startswith(full + "/")]
    if not lv:
        raise HTTPException(status_code=422, detail="没有可生成的叶子节点（树为空或所选子树无叶子）")
    jid = jobs.create("assemble-batch", f"批量生成画像 · {lv[0][1].split('/')[0] if not body.node_path else '选中子树'}", len(lv))
    asyncio.create_task(_run_batch(proj, jid, lv))
    return {"job_id": jid, "total": len(lv)}


async def _run_batch(proj: str, jid: str, lv: list[tuple[str, str]]) -> None:
    """逐叶组装：409 细分为「无规则→跳过 / 未核验→阻断」，其余计失败；单叶失败不中断"""
    for i, (digits, name) in enumerate(lv, 1):
        jobs.update(jid, cur=i, label=f"AI 生成画像 · {name}")
        try:
            await assemble_profile(proj, AssembleIn(node_path=digits, note=""))
            jobs.bump(jid, "ok")
        except HTTPException as e:
            if e.status_code == 409:
                if isinstance(e.detail, dict) and e.detail.get("unqualified"):
                    jobs.bump(jid, "blocked", name)
                else:
                    jobs.bump(jid, "skipped", name)
            else:
                jobs.bump(jid, "failed")
        except Exception:
            jobs.bump(jid, "failed")
    jobs.finish(jid)


@api_router.get("/jobs")
async def list_jobs(proj: str):
    _root(proj)  # 与其他端点同口径：非法/不存在项目名直接 4xx
    return jobs.list_all()


# ---------- 工作台 ----------

class WbNode(BaseModel):
    path: str; name: str; full: str; goal: str = ""
    kind: str = "leaf"; rules: int = 0; pend: int = 0; conf: int = 0
    profiled: bool = False; state: str = ""


@api_router.get("/wb/summary")
async def wb_summary(proj: str):
    root = _root(proj); nodes = _load_tree(root)
    profs = profiles._latest_profiles(root)
    rules = rule_store.load(root); void = _void_ids(root)
    confs = findings.load_conflicts(root)
    rmap = _rule_map(root)
    run = jobs.running() or {}
    jobless = not run or run.get("kind") not in ("generate", "regen")  # 其他 job（核验/重检等）不动树：日常态全部就绪

    def state_of(full: str) -> str:
        """generate 期间全树三态（done_nodes→done、current→doing、其余排队）；
        regen 期间仅受影响节点动（current→doing，其余就绪）——B8 局部语义"""
        if jobless:
            return "done"
        if full == run.get("current_node"):
            return "doing"
        if run.get("kind") == "regen":
            return "done"
        return "done" if full in run.get("done_nodes", []) else ""

    def stat(full: str) -> dict:
        rs = [a for a in rules if a.id not in void and _in_subtree(a.node, full)]
        cf = [c for c in confs if c.st == "open" and _in_subtree(
            next((rmap[x].node for x in (c.a, c.b) if x in rmap), ""), full)]  # 冲突按其规则归属计
        return {"rules": len(rs), "pend": sum(0 if a.verified else 1 for a in rs) + len(cf), "conf": len(cf)}
    out: list[dict] = []
    def walk(items, prefix, name_prefix, depth):
        for i, n in enumerate(items):
            path = f"{prefix},{i}" if prefix else str(i)
            full = f"{name_prefix}/{n.name}" if name_prefix else n.name
            kids = bool(n.children)
            s = stat(full)
            p = profs.get(full)
            out.append({"path": path, "name": n.name, "full": full,
                        "goal": (p.goal if p else "")[:60], "kind": "module" if kids else "leaf",
                        **s, "profiled": full in profs,
                        "state": state_of(full)})
            walk(n.children, path, full, depth + 1)
    walk(nodes, "", "", 0)
    rp = profs.get(profiles.ROOT_NODE)
    return {"tree": out, "root": {"goal": rp.goal, "entry": rp.entry, "flow": rp.flow,
                                  "boundaries": rp.boundaries, "note": rp.note,
                                  "kind": "root"} if rp else None}


# ---------- 问人 ----------

@api_router.get("/clarifications")
async def list_clarifications(proj: str):
    return [c.model_dump() for c in await clarifications.list_all(_root(proj))]


@api_router.post("/clarifications")
async def resolve_clarification(proj: str, body: ClarIn):
    root = _root(proj)
    rows = await clarifications.list_all(root)
    if not any(c.no == body.no for c in rows):
        raise HTTPException(status_code=404, detail=f"问题不存在: {body.no}")
    try:
        if body.action == "answer":
            cl = await clarifications.answer(root, body.no, idx=body.idx, text=body.text,
                                             ev_ids=body.ev_ids or [], extra=body.extra)
        elif body.action == "adopt":
            cl = await clarifications.clar_adopt(root, body.no)
        elif body.action == "ignore":
            cl = await clarifications.clar_ignore(root, body.no)
            return cl.model_dump()  # 忽略≠人工确认：跳过 ref→规则核过联动
        elif body.action == "verify":
            cl = await clarifications.verify(root, body.no)
        else:
            raise HTTPException(status_code=422, detail="action 必须为 answer/adopt/ignore/verify")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # 闭环联动：按题型×答案分流——只有 confirm 动规则；choose 走下方矛盾裁决块
    rmap = _rule_map(root)
    a = rmap.get(cl.ref)
    if a is not None:
        extra = (cl.ans.extra if cl.ans else "").strip()
        if cl.type == "confirm" and cl.answer == "与实际不符" and extra:
            a.text, a.suspect, a.verified, a.nb, a.clar = extra, True, True, "", None
        elif cl.type == "confirm" and cl.answer == "确认一致":
            a.verified, a.nb, a.clar = True, "", None
        else:
            a.clar = None  # 不清楚 / custom：不核过不改动，仅解除转问占用（可重新转问）
        rule_store.save(root, list(rmap.values()))
    # 闭环联动二：ref 指向矛盾（① 裁决转澄清）时，人工答案 = 代码侧裁决——
    # 胜方写 resolution（opts 构造序 [a 规则文本, b 规则文本]：idx 0→a、1→b），败方由 _void_ids 自动作废
    if body.action in ("answer", "adopt"):
        confs = findings.load_conflicts(root)
        c = next((x for x in confs if x.id == cl.ref and x.st == "clar"), None)
        if c is not None and c.a and c.b:
            idx = cl.opts.index(cl.answer) if cl.answer in cl.opts else body.idx
            if idx in (0, 1):
                c.st, c.resolution = "code", c.a if idx == 0 else c.b
                findings.save_conflicts(root, confs)
    # supply 答复自动入材料池（source=clar）：补全的事实进证据链，可走受影响重生成；
    # 只收真实文本/材料答复（ans.kind text|material）——选项回声（opt，如旧三连的「不支持/否」）不是事实描述，不入池；
    # 入池失败不吞（答案已落盘，重提交幂等）
    if (body.action in ("answer", "adopt") and cl.type == "supply" and cl.ans
            and cl.ans.kind in ("text", "material") and cl.answer):
        payload = classify_text(cl.answer)
        payload["source"] = "clar"
        await evidence.add(root, payload, content=cl.answer.encode("utf-8"))
    return cl.model_dump()


# ---------- 澄清重检（材料级 AI 代答，后台 job） ----------

CLAR_BATCH = 20  # 每批重检题数：一次 LLM 调用一批，job 进度按批推进
REVIEW_TEXT_CAP = 30000  # 重检材料文本上限，超长截断防超上下文
REVIEW_IMG_CAP = 5  # 单次重检图片上限


class ReviewIn(BaseModel):
    ev_ids: list[str]


def _apply_review(results, waits, materials_text: str, ev_ids: list[str], has_image: bool = False) -> int:
    """防幻觉校验并落库：choice 未命中→丢弃；quote 非 substring→quote_ok=False+conf=low；no 未知→丢弃。返回落库数"""
    by_no = {w.no: w for w in waits}
    n = 0
    for r in results:
        w = by_no.get(r.no)
        if w is None or not r.answered:
            continue
        if w.kind == "choice" and r.answer not in w.opts:
            continue  # 选择题答案必须逐字命中选项
        quote_ok = bool(r.quote) and r.quote in materials_text if not has_image else False  # 带图无法做 substring 校验
        conf = r.conf if quote_ok else "low"
        w.ai = AiReview(answer=r.answer, quote=r.quote,
                        ev_ids=list(ev_ids), conf=conf, quote_ok=quote_ok)
        n += 1
    return n


@api_router.post("/clarifications/review")
async def review_clarifications(proj: str, body: ReviewIn):
    """澄清重检：选定材料 × 全部 wait 题 → AI 代答落 clar.ai（待人工采纳），进度走 GET /jobs"""
    root = _root(proj)
    if not body.ev_ids:
        raise HTTPException(status_code=422, detail="未选择重检材料")
    if jobs.running():
        r = jobs.running()
        raise HTTPException(status_code=409, detail=f"已有任务进行中（{r['label']}，{r['cur']}/{r['total']}）")
    all_wait = [c for c in await clarifications.list_all(root) if c.st == "wait"]
    waits = [c for c in all_wait if c.type != "confirm"]  # 确认题不送 AI：材料证不了「实际系统」
    if not waits:
        detail = "没有可代答的问题（确认题不送 AI——待人工拍板）" if all_wait else "没有待问问题，无需重检"
        raise HTTPException(422, detail)
    evs = []
    for eid in body.ev_ids:
        ev = await evidence.get(root, eid)
        if ev is None:
            raise HTTPException(status_code=404, detail=f"证据不存在: {eid}")
        evs.append(ev)
    if engine_on():
        # agent 引擎：一次运行全部 wait 题，不截断不分批不限图片（flow 自带失败兜底与 finish）
        async def _run_review_agent():
            try:
                await agent_flow.clar_review_all(root, waits, body.ev_ids, jid)
            except Exception:
                pass  # flow 内部已置 job failed——吞掉防 create_task 裸跑告警

        jid = jobs.create("clar-review", "澄清重检", 1)
        asyncio.create_task(_run_review_agent())
        return {"job_id": jid, "total": 1, "questions": len(waits)}
    parts = [_evidence_parts(root, e) for e in evs]
    images = [b for _, imgs in parts for (_, b) in imgs]
    if len(images) > REVIEW_IMG_CAP:
        raise HTTPException(status_code=422, detail=f"单次重检图片最多 {REVIEW_IMG_CAP} 张（收到 {len(images)}）")
    text = "\n\n".join(t for t, _ in parts if t)
    truncated = len(text) > REVIEW_TEXT_CAP
    text = text[:REVIEW_TEXT_CAP]
    total = (len(waits) + CLAR_BATCH - 1) // CLAR_BATCH
    jid = jobs.create("clar-review", "澄清重检" + ("（材料超长已截断）" if truncated else ""), total)
    asyncio.create_task(_run_review(proj, jid, root, waits, text, images, body.ev_ids, truncated))
    return {"job_id": jid, "total": total, "questions": len(waits)}


async def _review_batches(proj, jid, root, waits, text, images, ev_ids, truncated: bool = False) -> int:
    """重检分批循环体（不收尾）——/clarifications/review 与 regen(rescan/partial) 共用；返回代答落库数"""
    has_image = bool(images)
    suffix = "（材料超长已截断）" if truncated else ""
    answered = 0
    for i in range(0, len(waits), CLAR_BATCH):
        batch = waits[i:i + CLAR_BATCH]
        jobs.update(jid, cur=i // CLAR_BATCH + 1,
                    label=f"澄清重检 · 第 {i + 1}-{min(i + CLAR_BATCH, len(waits))}/{len(waits)} 题{suffix}")
        try:
            qs = "\n".join(
                f"{w.no}. [{'选择题：' + ' / '.join(w.opts) if w.kind == 'choice' else '开放题：需补充材料'}] {w.q}"
                for w in batch)
            out = await _ai(tasks.clar_review, qs, text, images=images)
            answered += _apply_review(out.results, batch, text, ev_ids, has_image)
            for w in batch:  # 每批落盘一次
                await clarifications.set_ai(root, w.no, w.ai.model_dump() if w.ai else None)
        except Exception:
            jobs.update(jid, failed=jobs.get(jid).get("failed", 0) + len(batch))
    return answered


async def _run_review(proj, jid, root, waits, text, images, ev_ids, truncated: bool = False):
    answered = await _review_batches(proj, jid, root, waits, text, images, ev_ids, truncated)
    jobs.update(jid, ok=answered)
    jobs.finish(jid)


# ---------- 基线 ----------

@api_router.post("/baseline")
async def create_baseline(proj: str, body: BaselineIn):
    try:
        return gitops.save_baseline(_root(proj), body.note)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/baseline")
async def list_baselines_route(proj: str):
    return gitops.list_baselines(_root(proj))
