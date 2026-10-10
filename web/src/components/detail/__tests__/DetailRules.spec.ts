// Task 10 条目 tab 写操作：核验/转待确认（自定义问法）/AI 辅助核验
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DetailRules from '../DetailRules.vue'
import type { Conflict, Gap, Rule } from '../../../api'

const api = vi.hoisted(() => ({ confirmRule: vi.fn(), askRule: vi.fn(), verifyJob: vi.fn(), disposeGap: vi.fn(), resolveConflict: vi.fn() }))
vi.mock('../../../api', () => api)
vi.mock('../../../jobs', () => ({ startJobPolling: vi.fn(), jobRunning: ref(false) }))
vi.mock('../../../wb', () => ({ refreshWb: vi.fn() }))

const rules: Rule[] = [
  { id: 'R1', text: '已核条目', src: 'a.py:1', conf: '实证', st: '', verified: true, suspect: false },
  { id: 'R2', text: '未核条目', src: 'b.py:2', conf: '推测', st: '', verified: false, suspect: false },
  { id: 'R3', text: '另一个未核', src: 'c.py:3', conf: '待实证', st: '', verified: false, suspect: false },
]

const conflicts: Conflict[] = []
const gaps: Gap[] = []
const allRules: Rule[] = rules

function mountIt() {
  return mount(DetailRules, { props: { rules, conflicts, gaps, allRules }, global: { provide: { toast: vi.fn() } } })
}
const btn = (w: ReturnType<typeof mountIt>, text: string) =>
  w.findAll('button').find(b => b.text() === text)!

describe('DetailRules 写操作', () => {
  beforeEach(() => vi.clearAllMocks())

  it('核验：点击调 confirmRule → 行内变绿「已核过」+ 进度前进', async () => {
    api.confirmRule.mockResolvedValue(undefined)
    const w = mountIt()
    expect(w.text()).toContain('⚠ 待处理 2')
    await btn(w, '核验').trigger('click')
    await flushPromises()
    expect(api.confirmRule).toHaveBeenCalledWith('R2')
    expect(w.text()).toContain('已核过')
    expect(w.text()).toContain('✅ 核验通过 2') // 1 已核 + 本地核过 1
    expect(w.text()).toContain('67% 已确认')
  })

  it('待确认：行内展开表单预填建议问法，改文本后投递 askRule(id, q) 并 emit clar-changed', async () => {
    api.askRule.mockResolvedValue(undefined)
    const w = mountIt()
    await btn(w, '待确认？').trigger('click')
    const ta = w.find('textarea')
    expect(ta.exists()).toBe(true)
    expect((ta.element as HTMLTextAreaElement).value).toBe('「R2」的具体触发条件/兜底行为是什么？')
    await ta.setValue('自定义问法：兜底是什么？')
    await btn(w, '投递到待确认').trigger('click')
    await flushPromises()
    expect(api.askRule).toHaveBeenCalledWith('R2', '自定义问法：兜底是什么？')
    expect(w.emitted('clar-changed')).toHaveLength(1)
    expect(w.find('textarea').exists()).toBe(false) // 表单收起
  })

  it('AI 辅助核验（文档级）：调 verifyJob({only_doc:true}) + startJobPolling', async () => {
    api.verifyJob.mockResolvedValue({ job_id: 'J1', total: 2, rules: 2 })
    const w = mountIt()
    await btn(w, '✦ AI 辅助核验（文档级）').trigger('click')
    await flushPromises()
    expect(api.verifyJob).toHaveBeenCalledWith({ only_doc: true })
    const { startJobPolling } = await import('../../../jobs')
    expect(startJobPolling).toHaveBeenCalledWith('J1', expect.any(Function))
  })
})
