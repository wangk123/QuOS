import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WbDetail from '../WbDetail.vue'

// brief Step 1 测试改写 @vue/test-utils（T6 裁定：无 @testing-library/vue）
const api = vi.hoisted(() => ({
  getProfile: vi.fn(),
  getRules: vi.fn(),
  getConflicts: vi.fn(),
  getGaps: vi.fn(),
}))
vi.mock('../../api', () => api)

// 可变 mock：根详情用例走 wb 聚合（root + 顶层/子树行，验证顶层求和口径）
const wbData = vi.hoisted(() => ({
  root: { goal: '根目标', entry: '安装触发', flow: '登录 → 查询 → 输出', boundaries: '客户经理 · 一期文字', note: '', kind: 'root' },
  tree: [
    { path: '0', name: '登录', full: '登录', goal: '', kind: 'leaf', rules: 3, pend: 1, conf: 0, profiled: true, state: 'done' },
    { path: '1', name: '查询', full: '查询', goal: '', kind: 'leaf', rules: 4, pend: 0, conf: 0, profiled: true, state: 'done' },
    { path: '1,0', name: '子叶', full: '查询/子叶', goal: '', kind: 'leaf', rules: 4, pend: 2, conf: 0, profiled: false, state: '' },
  ],
}))
vi.mock('../../wb', () => ({
  wb: ref(wbData),
  refreshWb: vi.fn(),
  // 与真实实现同口径（走 mock 树）：full → 数字 path，行缺失返回 ''
  digitPathOf: (full: string) => (full === '__root__' ? full : wbData.tree.find(r => r.full === full)?.path ?? ''),
}))

describe('WbDetail', () => {
  beforeEach(() => vi.clearAllMocks())

  it('就绪节点渲染三 tab 与概要字段', async () => {
    api.getProfile.mockResolvedValue({ node: 'X', goal: 'g', entry: 'e', flow: 'f', states: 's', boundaries: 'b', deps: 'd', rules: [], unconfirmed: [] })
    api.getRules.mockResolvedValue([{ id: 'R1', text: 't', src: 's', conf: '文档', verified: true, node: 'X' }])
    api.getConflicts.mockResolvedValue([])
    api.getGaps.mockResolvedValue([])
    const w = mount(WbDetail, { props: { nodeFull: 'X', state: 'done' } })
    await flushPromises()
    expect(w.text()).toContain('概要')
    expect(w.text()).toContain('条目')
    expect(w.text()).toContain('存疑')
    expect(w.find('.spec').text()).toContain('目标') // 概要 spec 网格字段
    expect(w.find('.spec').text()).toContain('g')
    // 条目 tab：规则行 + 置信度徽章 + 已核过
    await w.findAll('.tab')[1].trigger('click')
    expect(w.text()).toContain('R1')
    expect(w.text()).toContain('已核过')
    expect(w.text()).toContain('文档')
    expect(api.getProfile).toHaveBeenCalledWith('X') // 行不在 wb 树：digitPathOf 空 → 兜底原 full
  })

  it('就绪态 getProfile 传数字路径而非含 / 的 full（/profiles/{node_path} 单段参数）', async () => {
    api.getProfile.mockResolvedValue({ node: '查询/子叶', goal: 'g', entry: '', flow: '', states: '', boundaries: '', deps: '', rules: [], unconfirmed: [] })
    api.getRules.mockResolvedValue([])
    api.getConflicts.mockResolvedValue([])
    api.getGaps.mockResolvedValue([])
    mount(WbDetail, { props: { nodeFull: '查询/子叶', state: 'done' } })
    await flushPromises()
    expect(api.getProfile).toHaveBeenCalledWith('1,0')
    expect(api.getProfile).not.toHaveBeenCalledWith('查询/子叶')
  })

  it('处理中显示骨架屏，排队显示排队文案', () => {
    const w = mount(WbDetail, { props: { nodeFull: 'X', state: 'doing' } })
    expect(w.text()).toContain('正在完善')
    expect(w.find('.skel').exists()).toBe(true)
    const q = mount(WbDetail, { props: { nodeFull: 'X', state: '' } })
    expect(q.text()).toContain('排队中')
  })

  it('根详情：wb 聚合渲染这份需求是什么+模块速览表，flow chips 可跳', async () => {
    const w = mount(WbDetail, { props: { nodeFull: '__root__', state: 'done' } })
    await flushPromises()
    expect(w.text()).toContain('这份需求是什么')
    expect(w.text()).toContain('根目标')
    expect(w.text()).toContain('模块速览')
    expect(w.findAll('.mtx tr.clickable')).toHaveLength(2) // 只顶层行，子叶不进表
    // 待你判断 = 顶层 pend 合计（1+0=1，子叶 2 不计）
    expect(w.text()).toContain('1 处待判断')
    expect(w.text()).not.toContain('3 处待判断')
    // 主线 chips：命中顶层模块名可跳（登录/查询），未命中（输出）只展示；边界 chips 不可点
    const chips = w.findAll('.jstep-chip')
    expect(chips).toHaveLength(5) // 边界 2 + 主线 3
    await chips[2].trigger('click') // 主线「登录」
    expect(w.emitted('jump')![0]).toEqual(['登录'])
    await chips[0].trigger('click') // 边界 chip 只展示
    expect(w.emitted('jump')).toHaveLength(1)
    await w.findAll('.mtx tr.clickable')[1].trigger('click') // 模块速览行跳转
    expect(w.emitted('jump')![1]).toEqual(['查询'])
    expect(api.getProfile).not.toHaveBeenCalled() // 根详情不走 getProfile
  })
})
