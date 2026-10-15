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
        if cur is None:
            fence_buf.clear()
            return
        if fence_lang == 'mermaid':
            src = '\n'.join(x.rstrip() for x in fence_buf).strip()
            if src:
                cur['blocks'].append({"type": "diagram", "text": src})   # 源码原样入库,前端 mermaid 渲染
            fence_buf.clear()
            return
        if not fence_lang and '┌' in ''.join(fence_buf):
            # ASCII 盒子图:非 mermaid 语法,进 diagram 块后渲染必失败 → 降级等宽源码(换行/对齐保留)
            src = '\n'.join(x.rstrip() for x in fence_buf).strip('\n')
            cur['blocks'].append({"type": "diagram", "text": src})
            fence_buf.clear()
            return
        flows: list[str] = []
        for raw in fence_buf:
            st = re.sub(r'[│┌┐└┘├┤┬┴┼─]+', ' ', raw)               # 盒线字符剥除
            st = re.sub(r'─*([^─▸▶▼]*?)─*[▸▶]', r' → \1 → ', st)   # ──label──▶ → 链路
            st = st.replace('▼', '→').strip()
            if not st or not re.search(r'[→\w\u4e00-\u9fff]', st):
                continue
            if st.startswith('→'):                      # 行首续链箭头:并入最近一条 flow
                cont = re.sub(r'^[→\s]+', '', st)
                if flows and cont:
                    flows[-1] = flows[-1].rstrip('→ ') + ' → ' + cont
                continue
            if '→' in st or '-->' in st:                 # 新链(含 ├─/└─ 分支行,剥符号)
                st = re.sub(r'^[├└]─*\s*', '', st)
                st = re.sub(r'\s*--\s*(.+?)\s*-->', r' → \1 → ', st)  # label→中间节点
                flows.append(_clean_inline(st))
        if flows:
            cur['blocks'].append({"type": "figure", "title": cur['title'], "flows": flows})
        elif fence_buf:  # 无箭头围栏:降级 para 收录,信息不断层
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

        if fence_lang == 'skip' and re.match(r'^##\s+\d', ln):
            in_fence = False; fence_lang = ''   # 附录结束:回到正常编号二级标题
        if in_fence and fence_lang == 'skip':
            continue
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

        if ln.startswith('#') and '附录' in ln:
            flush_para(); flush_table(); in_fence = True; fence_lang = 'skip'   # 附录整节跳过
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

    payload = DocPayload.model_validate({
        "meta": {"version": "draft", "date": date.today().isoformat(),
                 "scope": _clean_inline(next((l.strip('# ') for l in lines if l.startswith('# ')), ''))[:200]},
        "overview": {"intent": "", "boundary": ""},
        "glossary": glossary,
        "new_terms": [],
        "chapters": chapters,
        "rules": rules,
    })
    return payload, _extract_questions(md)


def detect_format_issues(md: str) -> list[str]:
    """导入时的格式契约检测:违规进导入响应 format_warnings,导入即知,不等渲染后返工。"""
    warns = []
    in_fence, lang = False, ''
    fence: list[str] = []
    for ln in md.splitlines():
        st = ln.strip()
        fm = re.match(r'^```(\w+)?\s*$', st)
        if fm:
            if in_fence:
                body = '\n'.join(fence)
                if lang == 'mermaid':
                    for nm in re.finditer(r'\[[^\]\n]*\([^)\n]*\)[^\]\n]*\]', body):
                        if not re.match(r'^\[\(.*\)\]$', nm.group(0)):  # [(x)]圆柱是合法形状
                            warns.append('R1:mermaid 节点文本含半角括号()(形状语法冲突,整图渲染会失败): ' + nm.group(0)[:40])
                            break
                if not lang and '┌' in body:
                    warns.append('R1:存在 ASCII 盒子图(网页必错位,应重画为 mermaid 或线性箭头链)')
            in_fence, lang, fence = not in_fence, (fm.group(1) or '').lower(), []
            continue
        if in_fence:
            fence.append(ln)
            continue
        if st.startswith('>') and len(st) > 8 and not re.match(r'^>\s*(题型|说明|注[:：])', st):
            warns.append('R5:引用块(>)承载实质内容,导入时会被丢弃: ' + st.lstrip('> ')[:30])
    return warns


_TBD_INLINE = re.compile(r'^\*\*(TBD-\d+)（(填空|确认|选择)）\*\*\s+(.+)$')          # 行内题型(云风控式)
_TBD_GROUPED = re.compile(r'^-\s*\*\*(TBD-\d+)[^*]*\*\*[:：]\s*(.+)$')                 # 分组题型(瀚海式)
_GROUP_TITLE = re.compile(r'^#{2,4}\s*(填空|选择|确认)')
_KIND = {"填空": "fill", "确认": "confirm", "选择": "choice"}


def _extract_questions(md: str) -> list[dict]:
    """附录 A 待确认问题清单 → 批注元素 {kind, payload{klabel,q}, anchor}。
    兼容两种写法:行内题型「**TBD-01（填空）** 题」与分组题型「### 填空题」下的「- **TBD-01 标题**：题」。
    题面提到的规则号尽量锚定;附录本体不进文档正文(由调用方跳过渲染)。"""
    out, group_kind = [], "fill"
    for ln in md.splitlines():
        st = ln.strip()
        gm = _GROUP_TITLE.match(st)
        if gm:
            group_kind = _KIND[gm.group(1)]
            continue
        m = _TBD_INLINE.match(st) or _TBD_GROUPED.match(st)
        if not m:
            continue
        no, ktype, q = m.group(1), (m.group(2) if m.lastindex == 3 else group_kind), m.group(m.lastindex)
        anchor = {"chapter_id": "", "seg": no}
        rm = re.search(r'((?:GP|FR|NFR)-[A-Za-z0-9-]+)', q)
        if rm:
            anchor["rule_no"] = rm.group(1)
        out.append({"kind": _KIND[ktype] if ktype in _KIND else ktype,
                    "payload": {"klabel": f"待确认 {no}", "q": q.strip(),
                                "ctx": "md 导入:附录 A 待确认问题清单"},
                    "anchor": anchor})
    return out
