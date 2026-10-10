import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import WbTree from '../WbTree.vue'

// 弹窗 Teleport 到 body（穿出 sticky 左栏的层叠上下文），不在组件 DOM 内——经 document 查询包 DOMWrapper
const dlg = (sel: string) => new DOMWrapper(document.querySelector(sel) as Element)

// 可变 mock 数据（vi.hoisted 保证 vi.mock 工厂执行时可引用）：根卡统计/doing 用例需换树
const wbSummary = vi.hoisted(() => ({
  root: { goal: '总览' },
  tree: [
    { path: '0', name: '工具模块', full: '工具模块', goal: '五技能', kind: 'module', rules: 73, total: 75, unverified: 3, conf: 1, profiled: true, state: 'done' },
    { path: '0,0', name: '工商信息查询', full: '工具模块/工商信息查询', goal: '注册登录→查询', kind: 'leaf', rules: 39, total: 40, unverified: 2, conf: 1, profiled: true, state: '' },
  ],
}))
vi.mock('../../wb', () => ({ wb: ref(wbSummary), refreshWb: vi.fn() }))
const DEFAULT_TREE = wbSummary.tree

// api 模块 mock：goal 编辑断言 patchProfileGoal 入参（数字路径）
const api = vi.hoisted(() => ({ patchProfileGoal: vi.fn(), treeOp: vi.fn() }))
vi.mock('../../api', () => api)

describe('WbTree', () => {
  it('渲染模块卡+叶行+徽章', () => {
    const w = mount(WbTree, { props: { selected: '' } })
    expect(w.text()).toContain('工具模块')
    expect(w.text()).toContain('工商信息查询')
    expect(w.text()).toContain('40 条') // .nbadge.cnt（total 口径）
    expect(w.text()).toContain('2 待核') // .nbadge.unv（模块行 0+叶行 2，子树聚合）
    expect(w.find('.nbadge.conf').text()).toBe('⚠1')
    expect(w.findAll('.modhead').length).toBe(1)
  })

  it('点击叶行 emit pick 全路径', async () => {
    const w = mount(WbTree, { props: { selected: '' } })
    await w.findAll('.leaf')[0].trigger('click')
    expect(w.emitted('pick')![0]).toEqual(['工具模块/工商信息查询'])
  })

  it('概要文本纯展示：点击不弹编辑窗、不触发选中（编辑只走 ✎）', async () => {
    api.patchProfileGoal.mockResolvedValue({})
    api.treeOp.mockResolvedValue([])
    const w = mount(WbTree, { props: { selected: '' } })
    await w.find('.leaf .ldesc').trigger('click')
    await flushPromises()
    expect(document.querySelector('[data-test="dlg-name"]')).toBe(null) // 不弹窗
    expect(api.patchProfileGoal).not.toHaveBeenCalled()
    // ✎ 是唯一编辑入口：数字路径 PATCH 由该入口覆盖（见下一用例）
    const btns = w.find('.leaf').findAll('.editops button')
    await btns[0].trigger('click')
    await dlg('[data-test="dlg-goal"]').setValue('新目标')
    await dlg('[data-test="dlg-save"]').trigger('click')
    await flushPromises()
    expect(api.patchProfileGoal).toHaveBeenCalledWith('0,0', '新目标')
    expect(api.patchProfileGoal).not.toHaveBeenCalledWith('工具模块/工商信息查询', '新目标')
  })

  it('✎ 编辑弹窗：名称+概要一并保存（rename + patchProfileGoal，未改项不重复提交）', async () => {
    api.patchProfileGoal.mockResolvedValue({})
    api.treeOp.mockResolvedValue([])
    const w = mount(WbTree, { props: { selected: '' } })
    await w.find('.modhead .editops button').trigger('click') // 模块 ✎
    await dlg('[data-test="dlg-name"]').setValue('工具模块2')
    await dlg('[data-test="dlg-goal"]').setValue('新概要')
    await dlg('[data-test="dlg-save"]').trigger('click')
    await flushPromises()
    expect(api.treeOp).toHaveBeenCalledWith('rename', '0', '工具模块2')
    expect(api.patchProfileGoal).toHaveBeenCalledWith('0', '新概要')
  })

  it('＋ 加子：弹窗名称+概要 → treeOp add + patchProfileGoal 按新数字路径补概要', async () => {
    api.patchProfileGoal.mockResolvedValue({})
    api.treeOp.mockResolvedValue([])
    const w = mount(WbTree, { props: { selected: '' } })
    await w.findAll('.modhead .editops button')[1].trigger('click') // 模块 ＋
    await dlg('[data-test="dlg-name"]').setValue('新叶')
    await dlg('[data-test="dlg-goal"]').setValue('新叶目标')
    await dlg('[data-test="dlg-save"]').trigger('click')
    await flushPromises()
    expect(api.treeOp).toHaveBeenCalledWith('add', '0', '新叶')
    expect(api.patchProfileGoal).toHaveBeenCalledWith('0,1', '新叶目标') // 现有子 0,0 → 新路径 0,1
  })

  it('树尾「＋ 加模块」：顶层新增（无 path），概要留空不补', async () => {
    api.patchProfileGoal.mockResolvedValue({})
    api.treeOp.mockResolvedValue([])
    const w = mount(WbTree, { props: { selected: '' } })
    await w.find('.add-root').trigger('click')
    await dlg('[data-test="dlg-name"]').setValue('风控')
    await dlg('[data-test="dlg-save"]').trigger('click')
    await flushPromises()
    expect(api.treeOp).toHaveBeenCalledWith('add', undefined, '风控')
    expect(api.patchProfileGoal).not.toHaveBeenCalled()
  })

  it('✕ 删除：应用内确认弹窗——取消不删，确认 treeOp del；选中在被删子树内回根详情', async () => {
    api.treeOp.mockResolvedValue([])
    const w = mount(WbTree, { props: { selected: '工具模块/工商信息查询' } })
    const btns = w.find('.leaf').findAll('.editops button') // ✎ ＋ ✕
    await btns[2].trigger('click') // ✕ → 应用内确认弹窗（非原生 confirm）
    expect(document.querySelector('[data-test="del-ok"]')).not.toBe(null)
    expect(document.body.textContent).toContain('工商信息查询')
    await dlg('[data-test="del-cancel"]').trigger('click') // 取消：不删
    expect(api.treeOp).not.toHaveBeenCalled()
    await btns[2].trigger('click')
    await dlg('[data-test="del-ok"]').trigger('click')
    await flushPromises()
    expect(api.treeOp).toHaveBeenCalledWith('del', '0,0')
    expect(w.emitted('pick')![0]).toEqual(['__root__'])
  })

  it('第 5 层节点不渲染 ＋（canAdd 深度闸门）', () => {
    wbSummary.tree = [
      { path: '0', name: 'L1', full: 'L1', goal: '', kind: 'module', rules: 0, total: 0, unverified: 0, conf: 0, profiled: false, state: '' },
      { path: '0,0', name: 'L2', full: 'L1/L2', goal: '', kind: 'module', rules: 0, total: 0, unverified: 0, conf: 0, profiled: false, state: '' },
      { path: '0,0,0', name: 'L3', full: 'L1/L2/L3', goal: '', kind: 'module', rules: 0, total: 0, unverified: 0, conf: 0, profiled: false, state: '' },
      { path: '0,0,0,0', name: 'L4', full: 'L1/L2/L3/L4', goal: '', kind: 'leaf', rules: 0, total: 0, unverified: 0, conf: 0, profiled: false, state: '' },
      { path: '0,0,0,0,0', name: 'L5', full: 'L1/L2/L3/L4/L5', goal: '', kind: 'leaf', rules: 0, total: 0, unverified: 0, conf: 0, profiled: false, state: '' },
    ]
    const w = mount(WbTree, { props: { selected: '' } })
    const leaves = w.findAll('.leaf') // L2..L5（L1 是模块头）
    expect(leaves[2].findAll('.editops button')).toHaveLength(3) // L4（第 4 层）：✎ ＋ ✕
    expect(leaves[3].findAll('.editops button')).toHaveLength(2) // L5（第 5 层）：✎ ✕，＋ 被闸门隐藏
    wbSummary.tree = DEFAULT_TREE
  })

  it('点击根卡片 emit pick __root__，角标按钮 emit refresh-root/edit-root', async () => {
    const w = mount(WbTree, { props: { selected: '' } })
    await w.find('.rootcard').trigger('click')
    expect(w.emitted('pick')![0]).toEqual(['__root__'])
    await w.find('.corner button.refresh').trigger('click')
    expect(w.emitted('refresh-root')).toHaveLength(1)
    await w.find('.corner button.edit').trigger('click')
    expect(w.emitted('edit-root')).toHaveLength(1)
    // 角标按钮 stopPropagation：不额外触发 pick
    expect(w.emitted('pick')).toHaveLength(1)
  })

  it('根卡统计只计顶层行——模块聚合不与叶行双计', () => {
    wbSummary.tree = [
      { path: '0', name: '模块A', full: '模块A', goal: '', kind: 'module', rules: 73, total: 75, unverified: 3, conf: 1, profiled: true, state: '' },
      { path: '0,0', name: '叶A', full: '模块A/叶A', goal: '', kind: 'leaf', rules: 39, total: 40, unverified: 2, conf: 1, profiled: true, state: '' },
      { path: '1', name: '模块B', full: '模块B', goal: '', kind: 'module', rules: 4, total: 4, unverified: 1, conf: 0, profiled: false, state: '' },
      { path: '1,0', name: '叶B', full: '模块B/叶B', goal: '', kind: 'leaf', rules: 4, total: 4, unverified: 1, conf: 0, profiled: false, state: '' },
    ]
    const w = mount(WbTree, { props: { selected: '' } })
    const rmeta = w.find('.rootcard .rmeta').text()
    expect(rmeta).toContain('79 条目') // 顶层 total 75+4，非全平铺（模块聚合不双计）
    expect(rmeta).toContain('4 待核') // 顶层 3+1，非 3+1+2+1=7
    wbSummary.tree = DEFAULT_TREE
  })

  it('state=doing 行渲染「处理中」蓝徽章', () => {
    wbSummary.tree = [
      { path: '0', name: '工具模块', full: '工具模块', goal: '', kind: 'module', rules: 73, total: 73, unverified: 0, conf: 0, profiled: true, state: '' },
      { path: '0,0', name: '工商信息查询', full: '工具模块/工商信息查询', goal: '', kind: 'leaf', rules: 39, total: 39, unverified: 1, conf: 0, profiled: false, state: 'doing' },
    ]
    const w = mount(WbTree, { props: { selected: '' } })
    expect(w.find('.leaf .nbadge.doing').text()).toBe('处理中')
    wbSummary.tree = DEFAULT_TREE
  })

  it('点击模块头折叠/展开（open 类切换，不触发 pick）', async () => {
    const w = mount(WbTree, { props: { selected: '' } })
    expect(w.find('.mod').classes()).toContain('open') // 默认展开
    await w.find('.modhead').trigger('click')
    expect(w.find('.mod').classes()).not.toContain('open') // 折叠：leaves 随 CSS display:none 收起
    expect(w.emitted('pick')).toBeUndefined() // 模块头只折叠不选中
    await w.find('.modhead').trigger('click')
    expect(w.find('.mod').classes()).toContain('open')
  })
})
