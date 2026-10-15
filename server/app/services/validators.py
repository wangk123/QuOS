"""两级校验器(纯函数,无 IO)。

硬错误拒收:编号口径 / quote 出处定位 / 结构完整;
软警告转批注:new_terms 术语确认 / 已登记术语写法 / 可判定存疑 / 章节缺口。
归一化:NFKC + 空白折叠为单空格 + casefold(design §6)。
"""
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.models import DocPayload, Material

_QUOTE_MIN = 6  # 短引用定位不可靠,降级软警告


def normalize(s: str) -> str:
    folded = unicodedata.normalize("NFKC", s).casefold()
    return re.sub(r"\s+", "", folded)


@dataclass
class Located:
    ok: bool
    nearest: str = ""


def locate_quote(quote: str, material_text: str) -> Located:
    if not material_text.strip():
        return Located(False, "")
    nq, nm = normalize(quote), normalize(material_text)
    if nq and nq in nm:
        return Located(True)
    # 失败:按原文句切分,取与 quote 归一化后最相似的原文句(供 agent 修正;原文形态,不做错位切片)
    import re as _re
    sentences = [x for x in _re.split(r"[。\.\n]", material_text) if x.strip()]
    best, best_ratio = "", 0.0
    ns = normalize(quote)
    for sent in sentences:
        ratio = SequenceMatcher(None, ns, normalize(sent)).ratio()
        if ratio >= best_ratio and sent.strip():
            best, best_ratio = sent.strip(), ratio
    return Located(False, best[:120])


@dataclass
class Err:
    code: str
    rule_no: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class Warn:
    code: str
    rule_no: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class AutoQ:
    kind: str  # confirm | fill
    payload: dict  # {klabel, q, ctx}
    anchor: dict  # {chapter_id, rule_no?, seg?, chapter?}


@dataclass
class Report:
    hard_errors: list[Err] = field(default_factory=list)
    soft_warnings: list[Warn] = field(default_factory=list)
    auto_questions: list[AutoQ] = field(default_factory=list)


def check_draft(
    payload: DocPayload,
    rules_existing: dict[str, str],
    materials: dict[int, Material],
    terms: set[str],
) -> Report:
    rpt = Report()
    rules = payload.rules

    # ── 编号口径:章节引用不重复;active 复用现存 active 编号=修改放行;复活 voided 拒 ──
    for ch in payload.chapters:
        if len(set(ch.rule_nos)) != len(ch.rule_nos):
            rpt.hard_errors.append(Err("NO_CONFLICT", detail={"chapter": ch.id}))
    for no, r in rules.items():
        if r.status == "active" and rules_existing.get(no) == "voided":
            rpt.hard_errors.append(Err("NO_CONFLICT", no, {"reason": "resurrect-voided"}))
    known = set(rules) | set(rules_existing)
    for ch in payload.chapters:
        for no in ch.rule_nos:
            if no not in known:
                rpt.hard_errors.append(Err("DANGLING_REF", no, {"chapter": ch.id}))

    # ── 规则级硬校验 ──
    for no, r in rules.items():
        if r.status == "voided":
            if not r.replaced_by:
                rpt.hard_errors.append(Err("VOIDED_NO_REPLACED_BY", no))
            continue
        if not r.violation.strip():
            rpt.hard_errors.append(Err("VIOLATION_EMPTY", no))
        if r.material_id is None or r.material_id not in materials:
            rpt.hard_errors.append(Err("MATERIAL_NOT_FOUND", no, {"material_id": r.material_id}))
            continue  # 材料缺失时出处核对无从谈起,单列错误
        if not r.quote.strip():
            # 空 quote 与过短同因:定位不可靠,降软警告(不得静默绕过出处层)
            rpt.soft_warnings.append(Warn("QUOTE_TOO_SHORT", no))
            continue
        m = materials[r.material_id]
        if not m.parsed_text.strip():
            continue  # 图片类材料:跳过出处硬校验(design §4.4)
        if len(r.quote.strip()) < _QUOTE_MIN:
            rpt.soft_warnings.append(Warn("QUOTE_TOO_SHORT", no))
            continue
        loc = locate_quote(r.quote, m.parsed_text)
        if not loc.ok:
            rpt.hard_errors.append(
                Err("QUOTE_NOT_FOUND", no, {"quote": r.quote, "nearest": loc.nearest})
            )

    # ── 章节结构硬校验 ──
    ch_ids = {ch.id for ch in payload.chapters}
    for ch in payload.chapters:
        if not ch.title.strip():
            rpt.hard_errors.append(Err("CHAPTER_NO_TITLE", detail={"chapter": ch.id}))
        if ch.parent is not None and ch.parent not in ch_ids:
            rpt.hard_errors.append(Err("CHAPTER_PARENT_DANGLING",
                                       detail={"chapter": ch.id, "parent": ch.parent}))
    # parent 成环检测(章节数小,逐章上溯即可)
    by_id = {ch.id: ch for ch in payload.chapters}
    for ch in payload.chapters:
        seen, cur = set(), ch.id
        while cur is not None:
            if cur in seen:
                rpt.hard_errors.append(Err("CHAPTER_PARENT_CYCLE", detail={"chapter": ch.id}))
                break
            seen.add(cur)
            cur = by_id[cur].parent if (cur in by_id and by_id[cur].parent) else None

    # ── 正文块结构硬校验(有块必填实,空块=模板填空式残骸) ──
    _block_required = {
        "para": lambda b: bool(b.text.strip()),
        "states": lambda b: bool(b.text.strip()),
        "table": lambda b: bool(b.columns) and bool(b.rows),
        "figure": lambda b: bool(b.flows),
        "exceptions": lambda b: bool(b.items),
    }
    for ch in payload.chapters:
        for b in ch.blocks:
            check = _block_required.get(b.type)
            if check is None:
                rpt.hard_errors.append(Err("BLOCK_BAD_TYPE",
                                           detail={"chapter": ch.id, "type": b.type}))
            elif not check(b):
                rpt.hard_errors.append(Err("BLOCK_EMPTY", detail={"chapter": ch.id, "type": b.type}))

    # ── 软警告 → 批注 ──
    for t in payload.new_terms:
        rpt.auto_questions.append(AutoQ(
            kind="confirm",
            payload={"klabel": "术语确认",
                     "q": f"术语「{t.name}」收录术语表?请给定义",
                     "ctx": t.context or "草案 new_terms 申报"},
            anchor={"chapter_id": "", "seg": t.name},
        ))
    for term in terms:
        for no, r in rules.items():
            if term not in r.text and normalize(term) in normalize(r.text):
                rpt.auto_questions.append(AutoQ(
                    kind="confirm",
                    payload={"klabel": "术语写法",
                             "q": f"规则 {no} 中术语「{term}」的写法与术语表不一致,是否修正?",
                             "ctx": r.text[:80]},
                    anchor={"chapter_id": "", "rule_no": no, "seg": term},
                ))
    for no, r in rules.items():
        if r.status == "active" and r.text.strip() and r.text.strip() == r.violation.strip():
            rpt.auto_questions.append(AutoQ(
                kind="confirm",
                payload={"klabel": "可判定存疑",
                         "q": f"{no} 的「怎样算违反」与规则正文相同,请补写可判定表述",
                         "ctx": r.text[:80]},
                anchor={"chapter_id": "", "rule_no": no, "seg": r.text[:20]},
            ))
    # 空壳章=既无正文块也无规则且无子章(纯容器父章由子章承载内容,合法)
    parent_ids = {c.parent for c in payload.chapters if c.parent}
    for ch in payload.chapters:
        if not ch.rule_nos and not ch.blocks and ch.id not in parent_ids:
            rpt.auto_questions.append(AutoQ(
                kind="fill",
                payload={"klabel": "内容缺口",
                         "q": f"章节「{ch.title}」没有任何正文与规则,该章的要求是什么?",
                         "ctx": "软校验:空壳章节"},
                anchor={"chapter_id": ch.id, "chapter": True},
            ))
    return rpt
