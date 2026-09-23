import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FuncTree from '../FuncTree.vue'

const tree = [
  {
    name: '放款',
    open: true,
    children: [
      { name: '放款执行', open: true, children: [{ name: '发起放款', open: true, children: [] }] },
      { name: '放款失败处理', open: false, children: [{ name: '放款失败登记', open: true, children: [] }] },
    ],
  },
  { name: '贷后', open: true, children: [] },
]

describe('FuncTree', () => {
  it('渲染嵌套层级（open 的子节点可见，closed 的不可见）', () => {
    const w = mount(FuncTree, { props: { nodes: tree, curPath: '' } })
    expect(w.text()).toContain('放款')
    expect(w.text()).toContain('放款执行')
    expect(w.text()).toContain('发起放款') // 三层：根 → 子 → 孙
    expect(w.text()).toContain('贷后')
    expect(w.text()).not.toContain('放款失败登记') // 父 open:false 折叠
    // 两层缩进引导线：孙节点 depth=2
    expect(w.findAll('.node .ig').length).toBeGreaterThan(2)
  })

  it('点击节点 emit pick(path)', async () => {
    const w = mount(FuncTree, { props: { nodes: tree, curPath: '' } })
    await w.findAll('.node')[0].trigger('click')
    expect(w.emitted('pick')![0]).toEqual(['0'])
    // 点击孙节点
    await w.findAll('.node')[1].trigger('click')
    expect(w.emitted('pick')![1]).toEqual(['0,0'])
  })

  it('每个节点 hover 出三个操作按钮（add/rename/del）', () => {
    const w = mount(FuncTree, { props: { nodes: tree, curPath: '' } })
    const ops = w.findAll('.node .nops button')
    expect(ops.length).toBe(5 * 3) // 5 个可见节点 × 3 个按钮
    expect(ops.filter(b => b.attributes('data-op') === 'add').length).toBe(5)
    expect(ops.filter(b => b.attributes('data-op') === 'rename').length).toBe(5)
    expect(ops.filter(b => b.attributes('data-op') === 'del').length).toBe(5)
  })

  it('curPath 节点带 active 样式', () => {
    const w = mount(FuncTree, { props: { nodes: tree, curPath: '0,0' } })
    expect(w.findAll('.node.active').length).toBe(1)
    expect(w.find('.node.active .nm').text()).toBe('放款执行')
  })
})
