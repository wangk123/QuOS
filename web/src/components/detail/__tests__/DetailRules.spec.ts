// 规则 tab（统一折叠）：四类问题交互——冲突选择+统一确认 / 缺口补写 / 规则核验+修正 / 开放记录
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DetailRules from '../DetailRules.vue'
import type { Conflict, Gap, Rule } from '../../../api'

const api = vi.hoisted(() => ({
  confirmRule: vi.fn(), verifyJob: vi.fn(), disposeGap: vi.fn(),
  resolveConflict: vi.fn(), correctRule: vi.fn(), addRuleManual: vi.fn(),
}))
vi.mock('../../../api', () => api)
vi.mock('../../../jobs', () => ({ startJobPolling: vi.fn(), jobRunning: ref(false) }))
vi.mock('../../../wb', () => ({ refreshWb: vi.fn() }))

const rules: Rule[] = [
  { id: 'R1', text: '已核条目', src: 'a.py:1', conf: '实证', st: '', verified: true, suspect: false },
  { id: 'R2', text: '未核条目', src: 'b.py:2', conf: '文档', st: '', verified: false, suspect: false },
  { id: 'R3', text: '普通未核条目', src: 'c.py:3', conf: '文档', st: '', verified: false, suspect: false },
]
const conflicts: Conflict[] = [
  { id: 'C1', parties: ['R1', 'R2'], q: '重试几次？', st: 'open', resolution: null },
]
const gaps: Gap[] = [
  { id: 'G1', dim: '边界', text: '上限后行为未说明', st: 'open', node: '支付' },
]
const allRules = rules

function mountIt() {
  return mount(DetailRules, {
    props: { rules, conflicts, gaps, allRules, nodeFull: '支付' },
    global: { provide: { toast: vi.fn() } },
  })
}

describe('DetailRules 折叠交互', () => {
  beforeEach(() => vi.clearAllMocks())

  it('待核规则折叠：点击行展开 → 核验调 confirmRule', async () => {
    api.confirmRule.mockResolvedValue(undefined)
    const w = mountIt()
    expect(w.text()).not.toContain('核验（与实际一致') // 未展开无按钮
    await w.findAll('.fold').find(f => f.text().includes('R3'))!.trigger('click')
    expect(w.text()).toContain('核验（与实际一致')
    await w.findAll('button').find(b => b.text().includes('核验（与实际一致'))!.trigger('click')
    await flushPromises()
    expect(api.confirmRule).toHaveBeenCalledWith('R3')
  })

  it('规则修正：展开 → ✎ 修正 → 输入 → 确认调 correctRule', async () => {
    api.correctRule.mockResolvedValue({ ...rules[2], text: '改后' })
    const w = mountIt()
    await w.findAll('.fold').find(f => f.text().includes('R3'))!.trigger('click')
    await w.findAll('button').find(b => b.text().includes('修正实际行为'))!.trigger('click')
    const ta = w.find('textarea')
    expect(ta.exists()).toBe(true)
    await ta.setValue('实际是重试 2 次')
    const btn = w.findAll('button').find(b => b.text() === '确认修正')!
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
    await btn.trigger('click')
    await flushPromises()
    expect(api.correctRule).toHaveBeenCalledWith('R3', '实际是重试 2 次')
  })

  it('open 冲突参与规则不算已核过：R1(verified) 不进核验通过区，计数归待处理且恒等式保持', async () => {
    const w = mountIt()
    // R1 verified 但参与 C1（open）→ 核验通过区不显示、无绿徽章
    await w.findAll('.chip').find(c => c.text().includes('核验通过'))!.trigger('click')
    expect(w.text()).not.toContain('已核过')
    // R2/R3 未核且 R2 参与 C1：待核规则区只显示 R3（R2 由冲突行承载，不重复设行）
    expect(w.findAll('.fold').filter(f => f.text().includes('R2')).length).toBe(0)
    // 恒等式：全部 5 = 核验通过 0 + 待处理 5（1 冲突+1 缺口+R3 待核+R1/R2 冲突中）
    const chips = w.findAll('.chip').map(c => c.text())
    expect(chips).toContain('全部 5')
    expect(chips).toContain('⚠ 待处理 5')
    expect(chips).toContain('✅ 核验通过 0')
  })

  it('冲突：点选说法启用统一确认；未选禁用；选其他需输入', async () => {
    api.resolveConflict.mockResolvedValue({ ...conflicts[0], st: 'done', resolution: 'R2' })
    const w = mountIt()
    await w.findAll('.fold').find(f => f.text().includes('C1'))!.trigger('click')
    const btn = w.findAll('button').find(b => b.text() === '确认裁决')!
    expect((btn.element as HTMLButtonElement).disabled).toBe(true) // 未选禁用
    await w.findAll('.opt')[1].trigger('click') // 选 B
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
    await btn.trigger('click')
    await flushPromises()
    expect(api.resolveConflict).toHaveBeenCalledWith('C1', 'code', 1)
  })

  it('冲突其他：选其他 → 输入 → manual 裁决', async () => {
    api.resolveConflict.mockResolvedValue({ ...conflicts[0], st: 'done', resolution: 'manual' })
    const w = mountIt()
    await w.findAll('.fold').find(f => f.text().includes('C1'))!.trigger('click')
    const btn = w.findAll('button').find(b => b.text() === '确认裁决')!
    const other = w.findAll('.opt')[w.findAll('.opt').length - 1]
    await other.trigger('click')
    expect(w.find('textarea').exists()).toBe(true)
    expect((btn.element as HTMLButtonElement).disabled).toBe(true) // 空输入禁用
    await w.find('textarea').setValue('固定重试 2 次后转人工')
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
    await btn.trigger('click')
    await flushPromises()
    expect(api.resolveConflict).toHaveBeenCalledWith('C1', 'manual', undefined, '固定重试 2 次后转人工')
  })

  it('缺口：展开 → 补写说明输入 → disposeGap(note, text)', async () => {
    api.disposeGap.mockResolvedValue({ ...gaps[0], st: 'answered' })
    const w = mountIt()
    await w.findAll('.fold').find(f => f.text().includes('上限后行为未说明'))!.trigger('click')
    await w.findAll('button').find(b => b.text().includes('✎ 补写说明'))!.trigger('click')
    await w.find('textarea').setValue('上限后转人工工单')
    await w.findAll('button').find(b => b.text() === '确认补写')!.trigger('click')
    await flushPromises()
    expect(api.disposeGap).toHaveBeenCalledWith('G1', 'note', '上限后转人工工单')
  })

  it('缺口：设计如此直调 ok', async () => {
    api.disposeGap.mockResolvedValue({ ...gaps[0], st: 'ok' })
    const w = mountIt()
    await w.findAll('.fold').find(f => f.text().includes('上限后行为未说明'))!.trigger('click')
    await w.findAll('button').find(b => b.text() === '设计如此')!.trigger('click')
    await flushPromises()
    expect(api.disposeGap).toHaveBeenCalledWith('G1', 'ok', '')
  })

  it('自定义开放：展开输入 → addRuleManual(text, nodeFull)', async () => {
    api.addRuleManual.mockResolvedValue({ ...rules[0], id: 'R9' })
    const w = mountIt()
    await w.findAll('.fold').find(f => f.text().includes('想核实什么'))!.trigger('click')
    await w.find('textarea').setValue('回调地址支持 HTTP 与 HTTPS')
    await w.findAll('button').find(b => b.text() === '确认记录')!.trigger('click')
    await flushPromises()
    expect(api.addRuleManual).toHaveBeenCalledWith('回调地址支持 HTTP 与 HTTPS', '支付')
  })

  it('AI 辅助核验：调 verifyJob({only_doc:true}) + startJobPolling', async () => {
    api.verifyJob.mockResolvedValue({ job_id: 'J1' })
    const w = mountIt()
    await w.findAll('button').find(b => b.text().includes('AI 辅助核验'))!.trigger('click')
    await flushPromises()
    expect(api.verifyJob).toHaveBeenCalledWith({ only_doc: true })
  })
})
