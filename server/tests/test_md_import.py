"""md 导入转换器测试:章节/规则三格式/块清洗/quote 自动匹配/容器父章/mermaid 降级。"""
from types import SimpleNamespace

from app.services.md_import import md_to_payload, match_quote

MATERIAL = (
    "登录安全增强\n"
    "登录时需同时进行密码与短信验证码校验，短信验证码为 6 位数字。\n"
    "密码超过配置周期未修改时，登录成功后强制修改密码。\n"
    "手机号在页面提示与日志中一律脱敏显示。\n"
)


def mat(mid: int = 3) -> SimpleNamespace:
    return SimpleNamespace(id=mid, parsed_text=MATERIAL)


MD = """# 云风控登录安全增强需求文档

## 1 文档头

版本 draft，日期 2026-10-15。

## 2 背景与目标

加强系统账号安全，降低短信接口盗刷。

## 3 用户与场景

### 3.1 用户类清单

| 用户类 | 能干什么 |
|---|---|
| 登录用户 | 登录、改密 |
| 管理员 | 配置开关 |

## 4 系统总览

主链路：

```
打开登录页 → 输入账号密码 → 校验 → 登录成功
→ 进入系统
```

上下文图：

```mermaid
flowchart LR
  U[用户] --> SYS[风控云]
```

## 5 需求主体

### 5.0 跨域通用规则

- **GP-01** 手机号在页面提示与日志中一律脱敏显示，不出现完整手机号 138****2344。
- FR-101 短信验证码开关开启时，密码登录必须同时填写短信验证码。

### 5.1 登录身份校验

**叙述**：开关决定登录要素。

1. NFR-01（可维护性）短信与密码过期策略参数通过 Apollo 配置，调整不需修改代码。
2. 密码过期后强制修改密码。

## 8 术语表与变更记录

### 8.1 术语表

| 词条 | 定义 |
|---|---|
| 短信验证码 | 服务端生成的 6 位数字 |
| 短信验证码开关 | Apollo 配置项 |
"""


def test_convert_chapters_and_hierarchy():
    p = md_to_payload(MD, {})
    ids = {c['id']: c for c in (c.model_dump() for c in p.chapters)}
    assert ids['c3-1']['parent'] == 'c3'          # ### N.M 挂 ## N
    assert ids['c5-0']['parent'] == 'c5'
    assert any(c['title'] == '登录身份校验' for c in ids.values())


def test_rule_three_formats_and_inline_clean():
    p = md_to_payload(MD, {3: mat()})
    r = {k: v.model_dump() for k, v in p.rules.items()}
    # 三种行格式:- **编号** / - 编号 / 1. 编号（标签）
    assert set(r) == {'GP-01', 'FR-101', 'NFR-01'}
    import re as _re
    assert '脱敏' in r['GP-01']['text']
    assert '138****2344' in r['GP-01']['text']    # 四连星脱敏号不被粗体转换误伤
    assert not _re.search(r'\*\*[^*]+\*\*', r['GP-01']['text'])  # 无成对粗体标记残留


def test_quote_auto_match_and_material():
    p = md_to_payload(MD, {3: mat()})
    r = {k: v.model_dump() for k, v in p.rules.items()}
    assert r['FR-101']['material_id'] == 3
    matched = [k for k, v in r.items() if v['quote']]
    assert 'GP-01' in matched                      # 「手机号…一律脱敏显示」与素材句高相似
    assert all(v['quote'] == '' or v['quote'] in MATERIAL for v in r.values())


def test_rules_meta_override():
    p = md_to_payload(MD, {3: mat()},
                      rules_meta={"FR-101": {"violation": "开关开启却未校验短信即放行",
                                              "quote": "登录时需同时进行密码与短信验证码校验"}})
    r = {k: v.model_dump() for k, v in p.rules.items()}
    assert r['FR-101']['violation'] == '开关开启却未校验短信即放行'
    assert r['FR-101']['quote'] in MATERIAL


def test_violation_fallback_not_equal_text():
    p = md_to_payload(MD, {})
    r = {k: v.model_dump() for k, v in p.rules.items()}
    for v in r.values():
        assert v['violation'].strip()              # 模板兜底非空
        assert v['violation'] != v['text']         # 不触发「可判定存疑」雷同判定


def test_blocks_table_para_figure_mermaid():
    p = md_to_payload(MD, {3: mat()})
    d = [c.model_dump() for c in p.chapters]
    user_tbl = [b for c in d if c['title'] == '用户类清单' for b in c['blocks'] if b['type'] == 'table']
    assert user_tbl and user_tbl[0]['rows'][0][0] == '登录用户'
    flows = [b for c in d for b in c['blocks'] if b['type'] == 'figure']
    assert flows and any('打开登录页' in f for f in flows[0]['flows'])
    assert not any(f.startswith('→') for fl in flows for f in fl['flows'])  # 行首续链已剥
    dg = [b for c in d for b in c['blocks'] if b['type'] == 'diagram']
    assert dg and 'flowchart LR' in dg[0]['text']   # mermaid 源码原样入 diagram 块


def test_glossary_from_term_section():
    p = md_to_payload(MD, {})
    names = [g.name for g in p.glossary]
    assert '短信验证码' in names and '短信验证码开关' in names


def test_match_quote_threshold():
    assert match_quote('密码超过配置周期未修改时强制修改', MATERIAL)
    assert match_quote('完全无关的一句话内容', MATERIAL) == ''


def test_container_parent_not_shell():  # 容器父章(仅子章)经 validators 不再出空壳题
    from app.services.validators import check_draft
    p = md_to_payload(MD, {3: mat()})
    rpt = check_draft(p, rules_existing={}, materials={3: mat()}, terms=set())
    shells = [q for q in rpt.auto_questions if '没有任何正文与规则' in q.payload['q']]
    assert not shells


def test_flow_continuation_merge_and_mermaid_table():
    md = """## 4 系统总览

```
打开登录页 → 校验
→ 登录成功
  ├─ 未过期 → 进入系统
```

```mermaid
flowchart LR
  U[登录用户] -->|输入凭证| SYS[风控云]
  SYS --> EXT[外部系统]
```
"""
    p = md_to_payload(md, {})
    d = [c.model_dump() for c in p.chapters]
    fig = next(b for c in d for b in c['blocks'] if b['type'] == 'figure')
    assert fig['flows'] == ['打开登录页 → 校验 → 登录成功', '未过期 → 进入系统']  # 续行合并
    dg = next(b for c in d for b in c['blocks'] if b['type'] == 'diagram')
    assert 'U[登录用户]' in dg['text'] and 'SYS[风控云]' in dg['text']  # mermaid 源码原样保留
