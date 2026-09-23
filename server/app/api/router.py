# server/app/api/router.py
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.ai import tasks
from app.ai.runner import AITaskError
from app.ai.tasks import AssembleBlocked
from app.core.classify import classify_file, classify_text
from app.storage import assertions as assert_store
from app.storage import cards, clarifications, dims, evidence, findings, gitops, project, tree
from app.storage.project import project_root, slugify

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


class AssembleIn(BaseModel):
    node_path: str
    note: str = ""


class ClarIn(BaseModel):
    no: int
    action: str
    idx: Optional[int] = None


class BaselineIn(BaseModel):
    note: str = "基线存档"


def _root(proj: str) -> Path:
    """项目根目录；项目名清洗后为空或逃逸 DATA_DIR 一律 422（防路径遍历）"""
    if not slugify(proj):
        raise HTTPException(status_code=422, detail=f"非法项目名: {proj}")
    root = project_root(proj)
    if not root.resolve().is_relative_to(Path(project.DATA_DIR).resolve()):
        raise HTTPException(status_code=422, detail=f"非法项目名: {proj}")
    return root


def _load_tree(root):
    try:
        return tree.load(root)
    except tree.TreeFormatError as e:
        raise HTTPException(status_code=422, detail=str(e))


async def _ai(fn, *args):
    try:
        return await fn(*args)
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


def _evidence_text(root, ev) -> str:
    if ev.path:
        f = Path(root) / ev.path
        if f.exists():
            return f.read_text("utf-8", errors="replace")
    return ev.name


def _assert_map(root) -> dict:
    return {a.id: a for a in assert_store.load(root)}


# ---------- 证据 ----------

@api_router.get("/evidence")
async def list_evidence(proj: str):
    return [e.model_dump() for e in await evidence.list_all(_root(proj))]


@api_router.post("/evidence")
async def add_evidence(proj: str, request: Request):
    root = _root(proj)
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
        ev = await evidence.add(root, payload, content=raw.encode("utf-8"))
    else:
        data = await request.body()
        if not data:
            raise HTTPException(status_code=422, detail="请求体为空")
        name = request.headers.get("x-filename") or request.query_params.get("filename") or "upload.bin"
        payload = {"type": classify_file(name), "name": Path(name).name,
                   "ext": Path(name).suffix.lstrip("."), "stars": 2}
        ev = await evidence.add(root, payload, content=data)
    return ev.model_dump()


@api_router.post("/evidence/{ev_id}/extract")
async def extract_evidence(proj: str, ev_id: str):
    root = _root(proj)
    ev = await evidence.get(root, ev_id)
    if ev is None:
        raise HTTPException(status_code=404, detail=f"证据不存在: {ev_id}")
    got = await _ai(tasks.extract, _evidence_text(root, ev), ev.type)
    items = assert_store.load(root)
    for i, a in enumerate(got, len(items) + 1):
        items.append(a.model_copy(update={"id": f"A{i}"}))
    assert_store.save(root, items)
    await evidence.mark_extracted(root, ev_id, len(got))
    return {"added": len(got), "assertions": [a.model_dump() for a in items[len(items) - len(got):]]}


# ---------- 断言 ----------

@api_router.get("/assertions")
async def list_assertions(proj: str):
    return [a.model_dump() for a in assert_store.load(_root(proj))]


@api_router.post("/assertions/verify")
async def verify_assertions(proj: str, body: VerifyIn):
    root = _root(proj)
    items = assert_store.load(root)
    if body.assert_id:
        targets = [a for a in items if a.id == body.assert_id]
        if not targets:
            raise HTTPException(status_code=404, detail=f"断言不存在: {body.assert_id}")
    else:
        targets = items
    material = "\n\n".join(_evidence_text(root, e) for e in await evidence.list_all(root))
    out = await _ai(tasks.verify, targets, material)
    by_id = {a.id: a for a in items}
    applied = []
    for r in out.results:
        a = by_id.get(r.get("id"))
        if a is None:
            continue
        if r.get("ok") is True:
            a.verified = True
        elif r.get("corrected_text"):
            a.text, a.suspect, a.verified = r["corrected_text"], True, True
        applied.append(a.id)
    assert_store.save(root, items)
    return {"applied": applied, "results": out.results}


# ---------- 矛盾 ----------

@api_router.get("/conflicts")
async def list_conflicts(proj: str):
    return [c.model_dump() for c in findings.load_conflicts(_root(proj))]


@api_router.post("/conflicts/rescan")
async def rescan_conflicts(proj: str):
    root = _root(proj)
    detected = await _ai(tasks.conflict, assert_store.load(root))
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
        amap = _assert_map(root)
        opts = [amap[c.a].text if c.a in amap else "", amap[c.b].text if c.b in amap else ""]
        await clarifications.add(root, c.q, opts, ref=c.id)
    else:
        raise HTTPException(status_code=422, detail="action 必须为 code 或 clar")
    findings.save_conflicts(root, items)
    return c.model_dump()


# ---------- 空白 ----------

@api_router.get("/gaps")
async def list_gaps(proj: str):
    return [g.model_dump() for g in findings.load_gaps(_root(proj))]


@api_router.post("/gaps/rescan")
async def rescan_gaps(proj: str):
    root = _root(proj)
    dim_list = dims.get_dims(root)
    summary = "\n".join(_card_summary(c) for c in cards.load_all(root)) or "（暂无卡片）"
    detected = await _ai(tasks.gaps, summary, dim_list)
    detected = [g for g in detected if g.dim in dim_list]  # 防 AI 自造维度
    items = findings.merge_gaps(root, detected)
    return [g.model_dump() for g in items]


def _card_summary(c) -> str:
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
        await clarifications.add(root, g.text + "？", ["支持/是", "不支持/否", "不清楚"], ref=g.id)
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
            tree.add_node(nodes, body.path or None, body.name)
        elif body.op == "rename":
            if body.path is None:
                raise HTTPException(status_code=422, detail="rename 需要 path")
            tree.rename(nodes, body.path, body.name)
        elif body.op == "del":
            if body.path is None:
                raise HTTPException(status_code=422, detail="del 需要 path")
            tree.delete(nodes, body.path)
        else:
            raise HTTPException(status_code=422, detail="op 必须为 add/rename/del")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    tree.save(root, nodes)
    return [n.model_dump() for n in nodes]


# ---------- 卡片 ----------

@api_router.post("/cards/assemble")
async def assemble_card(proj: str, body: AssembleIn):
    root = _root(proj)
    nodes = _load_tree(root)
    node, full = _resolve(nodes, body.node_path)
    if node is None:
        raise HTTPException(status_code=404, detail=f"节点不存在: {body.node_path}")
    card = await _ai(tasks.assemble, assert_store.load(root), node.name, body.note)
    card.node = full  # 存储按树全路径寻址（load/export 匹配用）
    f = cards.save_card(root, full, card)
    return {"card": card.model_dump(), "file": f.name}


@api_router.get("/cards/{node_path}")
async def get_card(proj: str, node_path: str):
    root = _root(proj)
    nodes = _load_tree(root)
    node, full = _resolve(nodes, node_path)
    if node is None:
        raise HTTPException(status_code=404, detail=f"节点不存在: {node_path}")
    card = cards.load_card(root, full)
    if card is None:
        raise HTTPException(status_code=404, detail=f"节点无卡片: {node_path}")
    return card.model_dump()


@api_router.get("/doc")
async def export_doc(proj: str):
    try:
        text = cards.export_doc(_root(proj))
    except tree.TreeFormatError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


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
            if body.idx is None:
                raise HTTPException(status_code=422, detail="answer 需要 idx")
            cl = await clarifications.answer(root, body.no, body.idx)
        elif body.action == "verify":
            cl = await clarifications.verify(root, body.no)
        else:
            raise HTTPException(status_code=422, detail="action 必须为 answer 或 verify")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return cl.model_dump()


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
