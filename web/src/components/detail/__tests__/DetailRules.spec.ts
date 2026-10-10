// 规则 tab（统一折叠）：四类问题交互——冲突选择+统一确认 / 缺口补写 / 规则核验+修正 / 开放记录
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DetailRules from '../DetailRules.vue'
import type { Conflict, Gap, Rule } from '../../../api'

const api = vi.hoisted(() => ({
  confirmRule: vi.fn(), verifyJob: vi.fn(), disposeGap: vi.fn(),
  resolveConflict: vi.fn(), correctRule: vi.fn(), addRuleManual: vi.fn(), deleteRule: vi.fn(),
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
    // total 模拟 wb 行口径：3 规则 + 1 open 冲突 + 1 open 缺口（本例无跨节点参与方）
    props: { rules, conflicts, gaps, allRules, nodeFull: '支付', total: 5 },
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

  it('行内 ✎ 编辑：hover 出图标 → 预填文本 → 保存调 correctRule', async () => {
    api.correctRule.mockResolvedValue({ ...rules[2], text: '改后' })
    const w = mountIt()
    const row = w.findAll('.fold').find(f => f.text().includes('R3'))!
    await row.findAll('.editops button')[0].trigger('click') // ✎（hover 显示，jsdom 不拦 display:none）
    const ta = w.find('.editbox textarea')
    expect((ta.element as HTMLTextAreaElement).value).toBe('普通未核条目') // 预填当前文本
    await ta.setValue('实际是重试 2 次')
    await w.findAll('button').find(b => b.text() === '保存')!.trigger('click')
    await flushPromises()
    expect(api.correctRule).toHaveBeenCalledWith('R3', '实际是重试 2 次')
  })

  it('行内 ✕ 删除：二次确认条 → 确认调 deleteRule', async () => {
    api.deleteRule.mockResolvedValue(undefined)
    const w = mountIt()
    const row = w.findAll('.fold').find(f => f.text().includes('R3'))!
    await row.findAll('.editops button')[1].trigger('click') // ✕
    expect(w.text()).toContain('确认删除')
    await w.findAll('button').find(b => b.text() === '删除')!.trigger('click')
    await flushPromises()
    expect(api.deleteRule).toHaveBeenCalledWith('R3')
  })

  it('新增规则：＋ 按钮 → 内联输入 → addRuleManual(text, nodeFull)', async () => {
    api.addRuleManual.mockResolvedValue({ ...rules[0], id: 'R9' })
    const w = mountIt()
    await w.findAll('button').find(b => b.text().includes('＋ 新增规则'))!.trigger('click')
    await w.find('.newrule textarea').setValue('回调地址支持 HTTP 与 HTTPS')
    await w.findAll('button').find(b => b.text() === '确认新增')!.trigger('click')
    await flushPromises()
    expect(api.addRuleManual).toHaveBeenCalledWith('回调地址支持 HTTP 与 HTTPS', '支付')
  })

  it('chips 唯一口径：总数=已核过+待处理（含 open 冲突/缺口/冲突中规则），与树行 total 同数', async () => {
    const w = mountIt()
    // R1/R2 参与 C1（open）：显示为冲突中行，不显示「已核过」
    expect(w.text()).toContain('冲突中')
    expect(w.findAll('.badge.b-green').length).toBe(0)  // 无绿「已核过」行徽章
    // chips：全部 = 3 规则 + 1 冲突 + 1 缺口 = 5；待处理 = 5（R3 待核+R1/R2 冲突中+冲突+缺口）；已核过 = 0
    const chips = w.findAll('.chip').map(c => c.text())
    expect(chips).toContain('全部 5')
    expect(chips).toContain('⚠ 待处理 5')
    expect(chips).toContain('✅ 已核过 0')
    // 标题数 = 总数（与树行 total 同口径）
    expect(w.find('h3').text()).toContain('规则 · 5 条')
    // filter=ok：只剩已核规则（此刻 0 条），冲突中/待核不进
    await w.findAll('.chip').find(c => c.text().includes('已核过'))!.trigger('click')
    expect(w.findAll('.fold').length).toBe(0)
    expect(w.text()).toContain('还没有已核过的条目')
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

  it('AI 辅助核验：调 verifyJob({only_doc:true}) + startJobPolling', async () => {
    api.verifyJob.mockResolvedValue({ job_id: 'J1' })
    const w = mountIt()
    await w.findAll('button').find(b => b.text().includes('AI 辅助核验'))!.trigger('click')
    await flushPromises()
    expect(api.verifyJob).toHaveBeenCalledWith({ only_doc: true })
  })
})
