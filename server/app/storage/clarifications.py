# server/app/storage/clarifications.py
import json
from pathlib import Path

from app.core.models import Clarification


def _file(root) -> Path:
    return Path(root) / "clarifications.json"


def _load(root) -> list[dict]:
    p = _file(root)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError:
        raise RuntimeError("clarifications.json 损坏，请人工修复或删除")


def _save(root, rows: list[dict]) -> None:
    _file(root).write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")


def _find(rows: list[dict], no: int) -> dict:
    for r in rows:
        if r.get("no") == no:
            return r
    raise ValueError(f"问题不存在: {no}")


async def add(root, q: str, opts: list[str], ref: str | None = None, kind: str | None = None) -> Clarification:
    rows = _load(root)
    row = {"no": max((r.get("no", 0) for r in rows), default=0) + 1,
           "q": q, "opts": list(opts),
           "kind": kind or ("open" if not opts else "choice"),
           "st": "wait", "answer": None, "ref": ref, "ai": None, "ans": None}
    rows.append(row)
    _save(root, rows)
    return Clarification(**row)


async def set_ai(root, no: int, ai: dict | None) -> Clarification:
    rows = _load(root)
    row = _find(rows, no)
    c = Clarification(**{**row, "ai": ai})  # 先校验，防非法代答落盘毒化存储
    row["ai"] = ai
    _save(root, rows)
    return c


async def list_all(root) -> list[Clarification]:
    return [Clarification(**r) for r in _load(root)]


async def answer(root, no: int, idx: int | None = None, text: str | None = None,
                 ev_ids: list[str] | None = None) -> Clarification:
    rows = _load(root)
    row = _find(rows, no)
    kind = row.get("kind") or ("open" if not row.get("opts") else "choice")
    if kind == "choice":
        if idx is None or text is not None:
            raise ValueError("选择题必须回选项序号 idx")
        if not 0 <= idx < len(row["opts"]):
            raise ValueError(f"选项越界: {idx}")
        ans = {"kind": "opt", "text": row["opts"][idx], "ev_ids": []}
    else:
        if text is None or not text.strip() or idx is not None:
            raise ValueError("开放题必须回文本 text")
        ans = {"kind": "material" if ev_ids else "text", "text": text.strip(), "ev_ids": ev_ids or []}
    c = Clarification(**{**row, "answer": ans["text"], "ans": ans, "st": "answered"})  # 先校验，防非法参数落盘毒化存储
    row.update(answer=ans["text"], ans=ans, st="answered")
    _save(root, rows)
    return c


async def clar_adopt(root, no: int) -> Clarification:
    rows = _load(root)
    row = _find(rows, no)
    ai = row.get("ai")
    if not ai:
        raise ValueError(f"没有待采纳的代答: {no}")
    kind = row.get("kind") or ("open" if not row.get("opts") else "choice")
    new = {**row, "answer": ai["answer"], "st": "answered", "ai": None,
           "ans": {"kind": "opt" if kind == "choice" else "material",
                   "text": ai["answer"], "ev_ids": ai.get("ev_ids", [])}}
    c = Clarification(**new)  # 先校验，防非法代答落盘毒化存储
    row.update(new)
    _save(root, rows)
    return c


async def clar_ignore(root, no: int) -> Clarification:
    rows = _load(root)
    _find(rows, no)["ai"] = None
    _save(root, rows)
    return Clarification(**_find(rows, no))


async def verify(root, no: int) -> Clarification:
    rows = _load(root)
    row = _find(rows, no)
    row["st"] = "verified"
    _save(root, rows)
    return Clarification(**row)
