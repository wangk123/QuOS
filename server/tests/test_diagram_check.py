"""diagram_check:HTML 图(diagram-design 产物)结构校验——自包含/script 禁入/title-desc 契约/外链豁免 Google Fonts。"""
from app.services.diagram_check import check_diagram, is_html_form

MINIMAL = (
    '<!DOCTYPE html><html><head><title>t</title></head><body>'
    '<svg viewBox="0 0 100 50" role="img" aria-labelledby="t-title t-desc">'
    '<title id="t-title">T</title><desc id="t-desc">D</desc>'
    '<rect width="100" height="50" fill="#f5f5f5"/></svg></body></html>'
)


def test_is_html_form():
    assert is_html_form(MINIMAL)
    assert is_html_form('<svg viewBox="0 0 1 1"><title>t</title></svg>')
    assert is_html_form('<!DOCTYPE html>\n<html><body>x</body></html>')
    assert not is_html_form('flowchart TD\nA-->B')
    assert not is_html_form('')
    assert not is_html_form('┌──┐\n│x │')


def test_minimal_passes():
    assert check_diagram(MINIMAL) == []


def test_missing_title_desc():
    bad = MINIMAL.replace('<title id="t-title">T</title><desc id="t-desc">D</desc>', '')
    errs = check_diagram(bad)
    assert any('title' in e or 'desc' in e for e in errs)


def test_script_rejected():
    errs = check_diagram(MINIMAL.replace('</svg>', '<script>alert(1)</script></svg>'))
    assert any('script' in e for e in errs)


def test_event_attr_rejected():
    errs = check_diagram(MINIMAL.replace('<rect ', '<rect onload="x()" '))
    assert any('on*' in e or '事件' in e for e in errs)


def test_google_fonts_link_allowed_but_other_external_rejected():
    ok = MINIMAL.replace(
        '<body>',
        '<head><link href="https://fonts.googleapis.com/css2?family=Geist" rel="stylesheet"></head><body>')
    assert check_diagram(ok) == []
    bad = ok.replace('fonts.googleapis.com/css2?family=Geist', 'evil.example.com/x.css')
    errs = check_diagram(bad)
    assert any('外链' in e for e in errs)


def test_img_external_src_rejected():
    bad = MINIMAL.replace('</svg>', '<image href="https://evil.example.com/x.png"/></svg>')
    assert any('外链' in e for e in check_diagram(bad))


def test_bare_title_id_rejected():
    errs = check_diagram(MINIMAL.replace('id="t-title"', 'id="title"'))
    assert errs  # 裸 title/desc id 违反可访问契约(多图同页 id 冲突)
