"""HTML 图(diagram-design 产物)结构校验:平台侧图契约的校验器(纯函数,无 IO)。

改写自 cathrynlavery/diagram-design skill 的 scripts/self_check.py(MIT),适配为字符串接口:
- 自包含:禁 script 标签、禁 on*= 事件属性、禁外链资源(豁免 Google Fonts 字体 link——在线字体已拍板)
- 可访问契约:svg 内 title/desc 存在且 id 前缀化(裸 title/desc 多图同页会冲突)
- 内容越界:无 transform 元素的几何坐标超出 viewBox 声明范围(带容差,防误杀)
"""
import re

_FONT_HOSTS = {'fonts.googleapis.com', 'fonts.gstatic.com'}
_TOL = 2.0  # 越界容差(px):模板网格/字号微溢不算越界


def is_html_form(text: str) -> bool:
    """图源形态判别:diagram-design 产物(完整 HTML 或含内联 svg)→ True;mermaid/ASCII 源码 → False。"""
    return bool(re.search(r'<svg|<!doctype html', text or '', re.I))


def _svg_segment(text: str) -> str:
    m = re.search(r'<svg\b.*</svg>', text, re.S | re.I)
    return m.group(0) if m else ''


def check_diagram(text: str) -> list[str]:
    """HTML 图结构校验,返回错误明细(空=通过)。仅对 is_html_form 为 True 的源码调用。"""
    errs: list[str] = []
    if not (text or '').strip():
        return ['图源为空']
    if re.search(r'<script[\s>]', text, re.I):
        errs.append('含 <script> 标签(平台禁脚本,与前端 sandbox 双保险)')
    if re.search(r'\son\w+\s*=', text, re.I):
        errs.append('含 on*= 事件属性(平台禁脚本)')

    for m in re.finditer(r'(?:src|href)\s*=\s*["\']https?://([^/"\']+)', text, re.I):
        host = m.group(1).lower()
        if host not in _FONT_HOSTS:
            errs.append(f'含外链资源(图须自包含,仅豁免 Google Fonts): {m.group(0)[:60]}')

    svg = _svg_segment(text)
    if not svg:
        errs.append('未找到 <svg>(图主体缺失)')
        return errs
    for tag, label in (('title', '标题'), ('desc', '描述')):
        tm = re.search(rf'<{tag}\b[^>]*>', svg, re.I)
        if not tm:
            errs.append(f'svg 内缺 <{tag}>(可访问性契约)')
            continue
        im = re.search(r'id\s*=\s*["\']([\w-]+)["\']', tm.group(0))
        if not im or im.group(1).lower() == tag:
            errs.append(f'<{tag}> 缺前缀化 id(裸 id 多图同页冲突)')

    errs.extend(_check_out_of_viewbox(svg))
    return errs


def _check_out_of_viewbox(svg: str) -> list[str]:
    vb = re.search(
        r'viewBox\s*=\s*["\']\s*([-\d.eE+]+)[\s,]+([-\d.eE+]+)[\s,]+([\d.eE+]+)[\s,]+([\d.eE+]+)',
        svg, re.I)
    if not vb:
        return []  # 无 viewBox(如导出型 svg)不适用本检查
    x0, y0, w, h = (float(vb.group(i)) for i in range(1, 5))
    x1, y1 = x0 + w, y0 + h
    errs = []
    for em in re.finditer(r'<(\w+)\b([^>]*)/?>', svg):
        attrs = em.group(2)
        if 'transform' in attrs.lower():
            continue  # 坐标系被变换,直接比对必误杀
        def num(name):
            fm = re.search(rf'\b{name}\s*=\s*["\']([-\d.eE+]+)', attrs)
            return float(fm.group(1)) if fm else None
        tag, lx, ly = em.group(1).lower(), None, None
        ux = uy = None
        if tag in ('rect', 'image', 'use', 'foreignobject'):
            lx, ly, ux, uy = num('x'), num('y'), num('width'), num('height')
            if lx is not None and ux is not None:
                ux += lx
            if ly is not None and uy is not None:
                uy += ly
        elif tag == 'circle':
            cx, cy, r = num('cx'), num('cy'), num('r')
            if None not in (cx, cy, r):
                lx, ly, ux, uy = cx - r, cy - r, cx + r, cy + r
        elif tag == 'line':
            a, b, c, d = num('x1'), num('y1'), num('x2'), num('y2')
            if None not in (a, b, c, d):
                lx, ly, ux, uy = min(a, c), min(b, d), max(a, c), max(b, d)
        elif tag == 'ellipse':
            cx, cy, rx, ry = num('cx'), num('cy'), num('rx'), num('ry')
            if None not in (cx, cy, rx, ry):
                lx, ly, ux, uy = cx - rx, cy - ry, cx + rx, cy + ry
        elif tag == 'text':
            lx, ly = num('x'), num('y')
            ux, uy = lx, ly
        if lx is None or ly is None:
            continue
        if (lx < x0 - _TOL or ly < y0 - _TOL
                or (ux is not None and ux > x1 + _TOL)
                or (uy is not None and uy > y1 + _TOL)):
            errs.append(f'元素 <{tag}> 越界 viewBox(x={lx},y={ly} 超出 [{x0},{y0},{x1},{y1}])')
    return errs
