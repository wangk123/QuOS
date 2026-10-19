import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import DiagramView from '../src/components/rev/DiagramView.vue'

const HTML_SRC = '<!DOCTYPE html><html><body><svg viewBox="0 0 4 4">'
  + '<title id="a-title">a</title></svg></body></html>'

describe('DiagramView HTML 图 sandbox 渲染', () => {
  it('HTML 源走 iframe:sandbox 禁脚本,srcdoc 含图源', () => {
    const w = mount(DiagramView, { props: { source: HTML_SRC } })
    const iframe = w.find('iframe')
    expect(iframe.exists()).toBe(true)
    expect(iframe.attributes('sandbox')).not.toContain('allow-scripts')
    expect(iframe.attributes('srcdoc')).toContain('<svg')
  })

  it('存量 mermaid 源降级:显示重画提示与源码', () => {
    const w = mount(DiagramView, { props: { source: 'flowchart TD\nA-->B' } })
    expect(w.find('iframe').exists()).toBe(false)
    expect(w.text()).toContain('重画')
    expect(w.find('pre').exists()).toBe(true)
  })

  it('flows 线性链路渲染流程条(主路径,不再自动转 mermaid)', () => {
    const w = mount(DiagramView, { props: { flows: ['A → B → C'] } })
    expect(w.find('.flowbox').exists()).toBe(true)
    expect(w.text()).toContain('B')
  })
})
