// 受限 md 渲染器：导出文档语法子集 + XSS escape（无依赖手写，见 spec §4）
import { describe, expect, it } from 'vitest'
import { renderMd } from '../md'

describe('renderMd（语法子集）', () => {
  it('标题按层级渲染', () => {
    expect(renderMd('# 结果文档\n## 需求总览\n### 目标')).toBe(
      '<h1>结果文档</h1><h2>需求总览</h2><h3>目标</h3>')
  })

  it('无序列表聚组', () => {
    expect(renderMd('- 目标：x\n- 入口：y')).toBe('<ul><li>目标：x</li><li>入口：y</li></ul>')
  })

  it('表格：表头+分隔行+数据行，\\| 还原为字面竖线', () => {
    const md = '| ID | 规则 |\n|---|---|\n| R1 | 支持 a\\|b |\n| R2 | 普通规则 |'
    expect(renderMd(md)).toBe(
      '<table><thead><tr><th>ID</th><th>规则</th></tr></thead>' +
      '<tbody><tr><td>R1</td><td>支持 a|b</td></tr><tr><td>R2</td><td>普通规则</td></tr></tbody></table>')
  })

  it('段落：连续行聚为一个 p，段内换行转 br', () => {
    expect(renderMd('主流程：\n第一步\n第二步\n\n第二段')).toBe(
      '<p>主流程：<br>第一步<br>第二步</p><p>第二段</p>')
  })

  it('空串与纯空白返回空串', () => {
    expect(renderMd('')).toBe('')
    expect(renderMd('\n\n')).toBe('')
  })
})

describe('renderMd（安全）', () => {
  it('HTML 全量转义：script/onerror 不构成标签', () => {
    const out = renderMd('<script>alert(1)</script>\n- <img onerror="x">')
    expect(out).not.toMatch(/<(script|img)/)
    expect(out).toContain('&lt;script&gt;')
    expect(out).toContain('&lt;img onerror=')
  })

  it('标题/单元格内的 HTML 也转义', () => {
    expect(renderMd('# <b>粗</b>')).toBe('<h1>&lt;b&gt;粗&lt;/b&gt;</h1>')
  })
})
