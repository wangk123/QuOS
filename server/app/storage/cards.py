# server/app/storage/cards.py
import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.storage import tree
from app.storage.project import slugify

CARD_DIR = "cards"
CONF_MARK = {"实证": "✅", "文档": "✅"}

_SECTIONS = [("flow", "主流程"), ("states", "状态机"), ("boundaries", "异常边界"),
             ("note", "补充说明"), ("deps", "依赖"), ("unconfirmed", "未确认项")]
_SECTION_KEY = {"规则": "rules", **{t: k for k, t in _SECTIONS}}


class Rule(BaseModel):
    id: str
    text: str
    src: str
    conf: str


class Card(BaseModel):
    node: str
    goal: str = ""
    entry: str = ""
    flow: str = ""
    rules: list[Rule] = Field(default_factory=list)
    states: str = ""
    boundaries: str = ""
    note: str = ""
    deps: str = ""
    unconfirmed: list[str] = Field(default_factory=list)


def _dump(card: Card) -> str:
    lines = ["---", f"node: {card.node}", f"goal: {card.goal}", f"entry: {card.entry}",
             "---", "", f"# {card.node}", ""]
    for key, title in _SECTIONS:
        lines.append(f"## {title}")
        if key == "unconfirmed":
            lines += [f"- {u}" for u in card.unconfirmed]
        else:
            lines.append(getattr(card, key))
        lines.append("")
    lines += ["## 规则", ""]
    if card.rules:
        lines += ["| ID | 规则 | 来源 | 置信度 |", "|---|---|---|---|"]
        for r in card.rules:
            text = r.text.replace("|", "\\|")
            lines.append(f"| {r.id} | {text} | {r.src} | {r.conf} |")
    lines.append("")
    return "\n".join(lines)


def _parse_rules(body: list[str]) -> list[Rule]:
    rows = [ln for ln in body if ln.strip().startswith("|")]
    data = [r for r in rows if set(r.replace("|", "").replace(" ", "")) != {"-"}]
    rules = []
    for row in data[1:]:  # 首行为表头
        cells = [c.strip().replace("\\|", "|")
                 for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]
        if len(cells) >= 4:
            rules.append(Rule(id=cells[0], text=cells[1], src=cells[2], conf=cells[3]))
    return rules


def _parse(text: str) -> Card:
    lines = text.splitlines()
    meta, i = {}, 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            k, _, v = lines[i].partition(":")
            meta[k.strip()] = v.strip()
            i += 1
        i += 1
    bodies: dict[str, list[str]] = {k: [] for k in _SECTION_KEY.values()}
    cur = None
    for ln in lines[i:]:
        if ln.startswith("## "):
            cur = _SECTION_KEY.get(ln[3:].strip())
        elif cur:
            bodies[cur].append(ln)
    kwargs: dict = {"node": meta.get("node", ""), "goal": meta.get("goal", ""),
                    "entry": meta.get("entry", ""),
                    "rules": _parse_rules(bodies["rules"]),
                    "unconfirmed": [ln.strip()[2:].strip() for ln in bodies["unconfirmed"]
                                    if ln.strip().startswith("- ")]}
    for key, _ in _SECTIONS[:-1]:
        kwargs[key] = "\n".join(bodies[key]).strip()
    return Card(**kwargs)


def _dir(root) -> Path:
    return Path(root) / CARD_DIR


def save_card(root, node_path: str, card: Card) -> Path:
    d = _dir(root)
    d.mkdir(parents=True, exist_ok=True)
    name = slugify(node_path.rsplit("/", 1)[-1])
    f, n = d / f"{name}.md", 2
    while f.exists():
        f = d / f"{name}-{n}.md"
        n += 1
    f.write_text(_dump(card), "utf-8")
    return f


def _file_no(f: Path) -> int:
    m = re.match(r"^(.*)-(\d+)$", f.stem)
    return int(m.group(2)) if m else 1


def _latest_cards(root) -> dict[str, Card]:
    """node -> 最新卡片（同节点取后缀数字最大的文件；重复 save 视为迭代，最新生效）"""
    d = _dir(root)
    if not d.exists():
        return {}
    best: dict[str, tuple[int, Card]] = {}
    for f in sorted(d.glob("*.md")):
        card = _parse(f.read_text("utf-8"))
        no = _file_no(f)
        if card.node not in best or no > best[card.node][0]:
            best[card.node] = (no, card)
    return {node: c for node, (_, c) in best.items()}


def load_card(root, node_path: str) -> Card | None:
    return _latest_cards(root).get(node_path)


def load_all(root) -> list[Card]:
    d = _dir(root)
    if not d.exists():
        return []
    return [_parse(f.read_text("utf-8")) for f in sorted(d.glob("*.md"))]


def _render_card(card: Card, with_title: bool = True) -> list[str]:
    out = ([f"### {card.node}", ""] if with_title else []) + [
        f"- 目标：{card.goal}", f"- 入口：{card.entry}", "",
        "主流程：", card.flow or "无", ""]
    if card.rules:
        out += ["规则：", "", "| ID | 规则 | 来源 | 置信度 |", "|---|---|---|---|"]
        for r in card.rules:
            text = r.text.replace("|", "\\|")
            out.append(f"| {r.id} | {text} | {r.src} | {r.conf} {CONF_MARK.get(r.conf, '⚠️')} |")
        out.append("")
    for key, title in _SECTIONS[1:-1]:
        v = getattr(card, key)
        if v:
            out += [f"{title}：", v, ""]
    if card.unconfirmed:
        out += ["未确认项："] + [f"- {u}" for u in card.unconfirmed] + [""]
    return out


def export_doc(root) -> str:
    cards = _latest_cards(root)
    out = ["# 结果文档", ""]
    used: set[str] = set()

    def walk(items: list[tree.Node], prefix: str, depth: int):
        for n in items:
            full = f"{prefix}/{n.name}" if prefix else n.name
            out.append("#" * (depth + 2) + " " + full)
            out.append("")
            if full in cards:
                used.add(full)
                out.extend(_render_card(cards[full], with_title=False))
            walk(n.children, full, depth + 1)

    walk(tree.load(root), "", 0)
    for node, card in cards.items():
        if node not in used:
            out.extend(_render_card(card))
    return "\n".join(out).rstrip() + "\n"
