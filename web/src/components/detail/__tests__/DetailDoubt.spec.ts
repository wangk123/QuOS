// Task 11 存疑 tab 写操作：冲突三选一裁决 + 缺口两按钮处置
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DetailDoubt from '../DetailDoubt.vue'
import type { Conflict, Gap, Rule } from '../../../api'

const api = vi.hoisted(() => ({ resolveConflict: vi.fn(), disposeGap: vi.fn() }))
vi.mock('../../../api', () => api)
vi.mock('../../../wb', () => ({ refreshWb: vi.fn() }))

const conflicts: Conflict[] = [
  { id: 'C1', a: 'R1', b: 'R2', q: '重试次数：代码 3 次 vs 文档 5 次', st: 'open', resolution: null },
]
const gaps: Gap[] = [
  { id: 'G1', dim: '幂等', text: '未说明重复提交的幂等键', st: 'open' },
]
const allRules: Rule[] = [
  { id: 'R1', text: '重试 3 次', src: 'retry.py:15', conf: '实证', st: '', verified: true, suspect: false },
  { id: 'R2', text: '重试 5 次', src: 'spec.md#3', conf: '文档', st: '', verified: false, suspect: false },
]

function mountIt() {
  return mount(DetailDoubt, {
    props: { conflicts, gaps, allRules },
    global: { provide: { toast: vi.fn() } },
  })
}
const btn = (w: ReturnType<typeof mountIt>, text: string) =>
  w.findAll('button').find(b => b.text() === text)!

describe('DetailDoubt 冲突三选一', () => {
  beforeEach(() => vi.clearAllMocks())

  it('信A：resolveConflict(id, code, a)，裁决后卡片转结论行', async () => {
    api.resolveConflict.mockResolvedValue({ ...conflicts[0], st: 'code', resolution: 'R1' })
    const w = mountIt()
    await btn(w, '信A').trigger('click')
    await flushPromises()
    expect(api.resolveConflict).toHaveBeenCalledWith('C1', 'code', 'a')
    expect(w.find('.resolved').exists()).toBe(true)
    expect(w.text()).not.toContain('两处材料说法冲突') // 冲突卡按钮区消失
  })

  it('信B：resolveConflict(id, code, b)', async () => {
    api.resolveConflict.mockResolvedValue({ ...conflicts[0], st: 'code', resolution: 'R2' })
    const w = mountIt()
    await btn(w, '信B').trigger('click')
    await flushPromises()
    expect(api.resolveConflict).toHaveBeenCalledWith('C1', 'code', 'b')
    expect(w.find('.resolved').exists()).toBe(true)
  })

  it('转待确认：resolveConflict(id, clar) + emit clar-changed', async () => {
    api.resolveConflict.mockResolvedValue({ ...conflicts[0], st: 'clar', resolution: null })
    const w = mountIt()
    await btn(w, '转待确认').trigger('click')
    await flushPromises()
    expect(api.resolveConflict).toHaveBeenCalledWith('C1', 'clar', undefined)
    expect(w.emitted('clar-changed')).toHaveLength(1)
    expect(w.find('.resolved').exists()).toBe(true)
  })
})

describe('DetailDoubt 缺口处置', () => {
  beforeEach(() => vi.clearAllMocks())

  it('转澄清：disposeGap(id, clar) + emit clar-changed', async () => {
    api.disposeGap.mockResolvedValue({ ...gaps[0], st: 'clar' })
    const w = mountIt()
    await btn(w, '转澄清').trigger('click')
    await flushPromises()
    expect(api.disposeGap).toHaveBeenCalledWith('G1', 'clar')
    expect(w.emitted('clar-changed')).toHaveLength(1)
    expect(w.text()).toContain('已转待确认')
  })

  it('设计如此：disposeGap(id, ok)，行变灰且按钮消失', async () => {
    api.disposeGap.mockResolvedValue({ ...gaps[0], st: 'ok' })
    const w = mountIt()
    await btn(w, '设计如此').trigger('click')
    await flushPromises()
    expect(api.disposeGap).toHaveBeenCalledWith('G1', 'ok')
    expect(w.find('.rrow.done').exists()).toBe(true)
    expect(btn(w, '设计如此')).toBeUndefined()
  })
})
