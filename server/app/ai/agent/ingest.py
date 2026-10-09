# server/app/ai/agent/ingest.py —— agent 产物校验与入库（spec §4.4）
import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError, field_validator

from app.ai.agent.runner import AgentRunError
from app.core.models import AiReview, Rule
from app.storage import profiles as profile_store
from app.storage import rules as rule_store
from app.storage import tree as tree_store


class Cite(BaseModel):
    ev_id: str = ""
    section: str = ""


class TreeNode(BaseModel):
    name: str
    goal: str = ""
    cite: Optional[Cite] = None
    children: list["TreeNode"] = []


class RootDraft(BaseModel):
    goal: str = ""
    entry: str = ""
    flow: str = ""
    boundaries: str = ""
    note: str = ""


class TreeOut(BaseModel):
    root: RootDraft
    nodes: list[TreeNode]


class ExtractRule(BaseModel):
    text: str
    node: str = ""
    conf: str = "文档"
    verified: bool = False
    quote: str = ""

    @field_validator("conf")
    @classmethod
    def _conf_ok(cls, v: str) -> str:
        if v not in ("实证", "文档", "推测", "待实证", "旧文档"):
            raise ValueError(f"非法 conf: {v}")
        return v


class ExtractOut(BaseModel):
    rules: list[ExtractRule]


def load_texts(dir_path: Path) -> dict[str, str]:
    """manifest → {ev_id: 文本全文}；图片与 no_text 不含（quote 定位只对文本类）"""
    manifest = _manifest(dir_path)
    out = {}
    for m in manifest:
        if m.get("no_text") or m["file"].endswith(".jpg"):
            continue
        out[m["id"]] = (dir_path / "materials" / m["file"]).read_text("utf-8", errors="replace")
    return out


def _manifest(dir_path: Path) -> list[dict]:
    return json.loads((dir_path / "materials" / "manifest.json").read_text("utf-8"))


def _quote_ok(quote: str, texts: dict[str, str]) -> bool:
    """quote 定位：substring 匹配文本类材料原文；纯图片/无文本材料池豁免（spec §4.4——
    图片条目 quote 是内容描述无从匹配，可信度由 conf 承载）"""
    if not texts:
        return True
    return bool(quote) and any(quote in t for t in texts.values())


async def ingest_tree(root: Path, data: dict, dir_path: Path) -> list[str]:
    """understand 产物入库：树结构（cite 只做防幻觉校验不落库）+ 根画像 + 初始画像；返回告警"""
    out = TreeOut.model_validate(data)
    valid_ev = set(load_texts(dir_path)) | {m["id"] for m in _manifest(dir_path)
                                            if m["file"].endswith(".jpg")}
    bad = 0

    def to_nodes(items: list[TreeNode], prefix: str = "") -> list[tree_store.Node]:
        nonlocal bad
        result = []
        for n in items:
            if n.cite and n.cite.ev_id and n.cite.ev_id not in valid_ev:
                bad += 1
            full = f"{prefix}/{n.name}" if prefix else n.name
            kids = to_nodes(n.children, full)
            profile_store.save_profile(root, full, profile_store.Profile(
                node=full, kind=("module" if kids else "leaf"), goal=n.goal or ""))
            result.append(tree_store.Node(name=n.name, children=kids))
        return result

    nodes = to_nodes(out.nodes)
    tree_store.save(root, nodes)
    profile_store.save_profile(root, profile_store.ROOT_NODE, profile_store.Profile(
        node=profile_store.ROOT_NODE, kind="root", goal=out.root.goal, entry=out.root.entry,
        flow=out.root.flow, boundaries=out.root.boundaries, note=out.root.note))
    return [f"{bad} 个节点出处失配已置空"] if bad else []


async def ingest_extract(root: Path, ev, data: dict, dir_path: Path) -> int:
    """extract 产物入库：node 白名单（失配置空）+ quote 定位（失败 verified 回落）；
    重提替换与 R{n} 续编号对齐 router._extract_one；返回新增条数。
    条目 schema 前置校验（缺 text/非法 conf → AgentRunError，不落脏数据）"""
    try:
        out = ExtractOut.model_validate(data)
    except ValidationError as e:
        raise AgentRunError(f"extract 产物不合法: {str(e)[:120]}")
    texts = load_texts(dir_path)
    valid = set(tree_store.paths(tree_store.load(root)))
    raw = out.rules
    got = [Rule(id="", text=r.text, src=ev.name, conf=r.conf,
                verified=r.verified, node=r.node or "")
           for r in raw]
    items = [a for a in rule_store.load(root) if a.src_id != ev.id]  # 重提：替换上次产出
    n = max((int(a.id[1:]) for a in items if a.id.startswith("R") and a.id[1:].isdigit()), default=0)
    for a, r in zip(got, raw):
        n += 1
        a.id = f"R{n}"
        a.src_id = ev.id
        if a.node not in valid:  # 编造路径 → 未归类
            a.node = ""
        if a.verified and not _quote_ok(r.quote, texts):
            a.verified = False
            a.nb = "引用无法定位"
    items.extend(got)
    rule_store.save(root, items)
    return len(got)


def ingest_verify(items: list[Rule], data: dict, dir_path: Path) -> dict:
    """verify 产物落字段：语义对齐 router._apply_verify_results（ok/corrected_text/无依据三路），
    差异=quote 给了但定位失败 → 按无依据落「引用无法定位」；返回三路计数"""
    stat = {"ok": 0, "corrected": 0, "nobasis": 0}
    texts = load_texts(dir_path)
    by_id = {a.id: a for a in items}
    for r in data.get("results", []):
        a = by_id.get(r.get("id"))
        if a is None:
            continue
        quote = r.get("quote", "")
        if r.get("ok") is True and _quote_ok(quote, texts):
            a.verified, a.nb = True, ""
            stat["ok"] += 1
        elif r.get("ok") is True and quote and not _quote_ok(quote, texts):
            a.verified, a.nb = False, "引用无法定位"
            stat["nobasis"] += 1
        elif r.get("corrected_text"):
            a.text, a.suspect, a.verified, a.nb = r["corrected_text"], True, True, ""
            stat["corrected"] += 1
        else:
            a.nb = r.get("reason") or "材料中无对应依据"
            stat["nobasis"] += 1
    return stat


def ingest_clar(waits, data: dict, dir_path: Path, ev_ids: list[str]) -> int:
    """clar-review 产物落库：语义对齐 router._apply_review——choice 逐字命中、quote substring→quote_ok
    （图片材料天然豁免：texts 不含图片）、失败 conf=low、未知 no 丢弃；返回落库数"""
    by_no = {w.no: w for w in waits}
    texts = load_texts(dir_path)
    n = 0
    for r in data.get("results", []):
        w = by_no.get(r.get("no"))
        if w is None or not r.get("answered"):
            continue
        if w.kind == "choice" and r.get("answer") not in w.opts:
            continue  # 选择题答案必须逐字命中选项
        quote = r.get("quote", "")
        quote_ok = _quote_ok(quote, texts)
        conf = r.get("conf", "med") if quote_ok else "low"
        w.ai = AiReview(answer=r.get("answer", ""), quote=quote,
                        ev_ids=list(ev_ids), conf=conf, quote_ok=quote_ok)
        n += 1
    return n
