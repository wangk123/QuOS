import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

/* mermaid.render 失败时会向容器插入炸弹错误卡再 throw——组件必须自备容器并清理,不得残留到 body */
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async (id: string, _src: string) => {
      // 模拟 mermaid 失败行为:临时 #id 容器(含炸弹卡)插到 body,另留 d#id 样式容器,再 throw
      const holder = document.createElement('div')
      holder.id = id
      const card = document.createElement('div')
      card.className = 'error-card'
      card.textContent = 'Syntax error in text'
      holder.appendChild(card)
      const styleBox = document.createElement('style')
      styleBox.id = 'd' + id
      document.body.append(holder, styleBox)
      throw new Error('Parse error')
    }),
  },
}))
import DiagramView from '../src/components/rev/DiagramView.vue'

describe('DiagramView 渲染失败清理', () => {
  beforeEach(() => { document.body.innerHTML = '' })

  it('失败后 body 无 mermaid 残留错误卡,组件显示降级提示', async () => {
    const w = mount(DiagramView, { props: { source: 'flowchart LR\n  a-->graph[x]' } })
    await flushPromises()
    expect(document.querySelectorAll('.error-card')).toHaveLength(0)
    expect(w.text()).toContain('渲染失败')
  })

  it('多实例多次失败也不累积残留', async () => {
    for (let i = 0; i < 2; i++) {
      const w = mount(DiagramView, { props: { source: 'flowchart LR\n  a-->b' } })
      await flushPromises()
      w.unmount()
    }
    expect(document.querySelectorAll('.error-card')).toHaveLength(0)
  })
})

/* 竞态守卫:两轮渲染(先基线快照后草案),旧一轮结果晚归不得覆盖新一轮 */
describe('DiagramView 竞态', () => {
  it('旧一轮失败晚归,新一轮成功的结果不被覆盖', async () => {
    const mermaidMod = await import('mermaid')
    const render = mermaidMod.default.render as any
    let n = 0
    render.mockImplementation(async (_id: string, _s: string) => {
      n += 1
      if (n === 1) { await new Promise(r => setTimeout(r, 50)); throw new Error('stale fails late') }
      return { svg: '<svg>ok</svg>' + n }
    })
    const w = mount(DiagramView, { props: { source: 'flowchart LR\n a-->graph[x]' } })
    await new Promise(r => setTimeout(r, 5))
    await w.setProps({ source: 'flowchart LR\n a-->b' })   // 数据翻新(基线快照→草案)
    await new Promise(r => setTimeout(r, 150))
    expect(w.find('.mmd').text()).toContain('ok2')          // 新一轮成功生效
    expect(w.find('.mmd-degraded').exists()).toBe(false)    // 旧一轮晚归失败不降级
  })
  it('旧一轮成功晚归,也不覆盖新一轮的失败降级', async () => {
    const mermaidMod = await import('mermaid')
    const render = mermaidMod.default.render as any
    let n = 0
    render.mockImplementation(async (_id: string, _s: string) => {
      n += 1
      if (n === 1) { await new Promise(r => setTimeout(r, 50)); return { svg: '<svg>stale-ok</svg>' } }
      throw new Error('new fails')
    })
    const w = mount(DiagramView, { props: { source: 'flowchart LR\n a-->b' } })
    await new Promise(r => setTimeout(r, 5))
    await w.setProps({ source: 'flowchart LR\n a-->graph[x]' })
    await new Promise(r => setTimeout(r, 150))
    expect(w.find('.mmd-degraded').exists()).toBe(true)
    expect(w.find('.mmd').exists()).toBe(false)
  })
})
