"""markdown → DocPayload 转换器(纯函数,无 IO)。

外部 agent 产出 md 文档,平台内置转换(2026-10-15 决策:转换是固定脚本处理的事,内置平台,
agent 不再手拼 JSON/跑外部转换脚本)。清洗规则沉淀自 sync_v5/sync_riskcloud 两轮实战。

规则出处(quote)自动匹配:平台持有材料 parsed_text,对每条规则在素材句中找最相近者,
相似度达标即挂 quote;violation 在 md 中不存在,接受调用方附带精修值,否则模板兜底
(模板与正文不相等,不触发「可判定存疑」,由人工评审/req-review 把关质量)。
"""
import re
from datetime import date
from difflib import SequenceMatcher

from app.models import DocPayload
from app.services.validators import locate_quote, normalize

_RULE_NO = r'(?:GP|FR|NFR|REQ|R)-[A-Za-z0-9-]+'
_RULE_LINE = re.compile(
    rf'^\s*(?:-|\d+\.)\s+`?\*?\*?({_RULE_NO})(?:（[^）]*）)?`?\*?\*?\s*(.+)$')
_HEADING = re.compile(r'^(#{2,4})\s*(\d+(?:\.\d+)*)[.、]?\s+(.+?)\s*$')
_HEADING_BARE = re.compile(r'^(#{2,4})\s+(?!\d)(.+?)\s*$')  # 无编号小节(#### 常见)
_QUOTE_MIN_RATIO = 0.45
_VIOLATION_FALLBACK = '系统行为与该约束不符（触发条件、结果或路径与条文不一致）即违反'


def _clean_inline(t: str) -> str:
    t = re.sub(r'\*\*(.+?)\*\*', r'【\1】', t)  # 粗体→中文括注;脱敏号四连星不匹配(需成对包裹)
    return t.replace('`', '').strip()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'[。\.\n]', text) if len(s.strip()) >= 6]


def match_quote(rule_text: str, material_text: str) -> str:
    """规则文本 ↔ 素材句,最高相似度达标即返回该素材原句(quote 必为子串)。"""
    if not material_text.strip():
        return ''
    nt = normalize(rule_text)
    best, best_ratio = '', 0.0
    for sent in _sentences(material_text):
        ratio = SequenceMatcher(None, nt, normalize(sent)).ratio()
        if ratio > best_ratio:
            best, best_ratio = sent, ratio
    return best if best_ratio >= _QUOTE_MIN_RATIO else ''


def md_to_payload(md: str, materials: dict[int, object],
                  rules_meta: dict | None = None) -> DocPayload:
    """md → DocPayload。materials: {id: Material}(quote 自动匹配;空 dict 时 quote 全空走软警告)。
    rules_meta: 可选 {规则号: {violation, quote}} 精修值,优先于自动匹配。"""
    meta_map = {k.upper(): v for k, v in (rules_meta or {}).items()}
    lines = md.splitlines()

    chapters: list[dict] = []
    rules: dict[str, dict] = {}
    glossary: list[dict] = []
    cur = None            # 当前章节(dict 引用)
    stack: dict[int, dict] = {}   # 标题级别→最近章节
    in_fence = False
    fence_lang = ''
    fence_buf: list[str] = []
    para_buf: list[str] = []
    gloss_on = False

    def flush_para():
        if cur is not None and para_buf:
            cur['blocks'].append({"type": "para", "text": _clean_inline(''.join(para_buf))})
        para_buf.clear()

    def flush_fence():
        if cur is not None:
            flows = []
            for ln in fence_buf:
                line = re.sub(r'^[→\s]+', '', ln.strip())          # 行首续链箭头
                if '→' in line or '-->' in line:
                    line = re.sub(r'\s*--\s*(.+?)\s*-->', r' → \1 → ', line)  # label→中间节点
                    flows.append(_clean_inline(line))
            if flows and fence_lang != 'mermaid':
                cur['blocks'].append({"type": "figure", "title": cur['title'], "flows": flows})
            elif fence_buf:  # mermaid/无箭头围栏:降级 para 收录,信息不断层
                src = ' '.join(x.strip() for x in fence_buf if x.strip())
                if src:
                    cur['blocks'].append(
                        {"type": "para", "text": '【图·源码】' + _clean_inline(src)[:500]})
        fence_buf.clear()

    def add_rule(no: str, text: str):
        m = meta_map.get(no, {})
        quote = m.get('quote') or ''
        if not quote:
            for mat in materials.values():
                quote = match_quote(text, getattr(mat, 'parsed_text', ''))
                if quote:
                    break
        rules[no] = {
            "no": no, "text": _clean_inline(text),
            "violation": _clean_inline(m.get('violation') or '') or _VIOLATION_FALLBACK,
            "quote": quote,
            "material_id": next(iter(materials)) if materials else None,
            # quote 未匹配上时仍挂材料:留空走 QUOTE_TOO_SHORT 软警告(出处层不静默绕过,由人工评审补)
            "status": "active", "replaced_by": None,
        }
        if cur is not None and no not in cur['rule_nos']:
            cur['rule_nos'].append(no)

    def parse_table(rows: list[str]):
        if cur is None or len(rows) < 2:
            return
        cols = [_clean_inline(c) for c in rows[0].strip('|').split('|')]
        body = [[_clean_inline(c) for c in r.strip('|').split('|')] for r in rows[2:]] \
            if len(rows) > 2 else []
        if gloss_on:
            for r in body:
                if r and r[0]:
                    glossary.append({"name": r[0], "definition": r[1] if len(r) > 1 else ''})
            if cur is not None and body:
                cur['blocks'].append(
                    {"type": "para", "text": f'术语表共 {len(body)} 条词条,见平台术语表面板(点击词条定位正文)。'})
        elif body:
            cur['blocks'].append({"type": "table", "title": "", "columns": cols, "rows": body})

    tbl_rows: list[str] = []

    def flush_table():
        nonlocal tbl_rows
        parse_table(tbl_rows)
        tbl_rows = []

    for raw in lines:
        ln = raw.rstrip('\n')

        fm = re.match(r'^```(\w+)?\s*$', ln.strip())
        if fm:
            flush_para()
            flush_table()
            if in_fence:
                flush_fence()
                fence_lang = ''
            else:
                fence_lang = (fm.group(1) or '').lower()
            in_fence = not in_fence
            continue
        if in_fence:
            fence_buf.append(ln)
            continue

        m = _HEADING.match(ln)
        level = None
        if m:
            level, no_str, title = len(m.group(1)), m.group(2), _clean_inline(m.group(3))
        else:
            mb = _HEADING_BARE.match(ln)
            if mb and len(mb.group(1)) >= 3 and cur is not None:   # #### 无编号→当前章子节
                level, no_str, title = 4, '', _clean_inline(mb.group(2))
        if level:
            flush_para(); flush_table()
            gloss_on = '术语' in title
            cid = f'c{no_str.replace(".", "-")}' if no_str else f'{cur["id"]}-s{len(cur["blocks"]) + 1}' if cur else 'c0'
            parent = None
            if level == 3 and stack.get(2):
                parent = stack[2]['id']
            elif level == 4:
                parent = (stack.get(3) or stack.get(2) or {}).get('id')
            cur = {"id": cid, "title": title, "pri": "P1", "parent": parent,
                   "background": "", "blocks": [], "rule_nos": []}
            chapters.append(cur)
            stack[level] = cur
            continue

        if ln.startswith('#'):      # 一级标题/其他标题:文档名,跳过
            flush_para(); flush_table()
            continue
        if ln.startswith('>'):
            continue

        if ln.startswith('|'):
            flush_para()
            tbl_rows.append(ln)
            continue
        flush_table()

        rm = _RULE_LINE.match(ln)
        if rm and cur is not None:
            flush_para()
            add_rule(rm.group(1), rm.group(2))
            continue

        st = ln.strip()
        if not st:
            flush_para()
            continue
        if re.match(r'^\d+\.\s', st) or st.startswith(('- ', '* ')):   # 列表:独立成段(去标记)
            flush_para()
            if cur is not None:
                cur['blocks'].append(
                    {"type": "para", "text": _clean_inline(re.sub(r'^(?:\d+\.|[-*])\s+', '', st))})
            continue
        para_buf.append(st)
    flush_para(); flush_table(); flush_fence()

    return DocPayload.model_validate({
        "meta": {"version": "draft", "date": date.today().isoformat(),
                 "scope": _clean_inline(next((l.strip('# ') for l in lines if l.startswith('# ')), ''))[:200]},
        "overview": {"intent": "", "boundary": ""},
        "glossary": glossary,
        "new_terms": [],
        "chapters": chapters,
        "rules": rules,
    })
