// Task 13：待确认弹窗——分段 / 记答复（口头+材料佐证）/ AI 代答采纳忽略 / 联动说明（api 全 mock）
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  adoptClar,
  answerClar,
  answerClarOpen,
  getClarifications,
  ignoreClar,
  type Clarification,
  type EvidenceItem,
} from '../../api'

vi.mock('../../api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number, detail: unknown) {
      const d = detail instanceof Object && 'detail' in detail ? (detail as any).detail : detail
      super(typeof d === 'string' ? d : `HTTP ${status}`)
      this.status = status
    }
  },
  getClarifications: vi.fn(),
  answerClar: vi.fn(),
  answerClarOpen: vi.fn(),
  adoptClar: vi.fn(),
  ignoreClar: vi.fn(),
}))

const CLARS: Clarification[] = [
  { no: 1, q: '冷却期多久？', kind: 'choice', opts: ['7天', '30天'], st: 'wait', answer: null, ref: 'R1' },
  { no: 2, q: '退款阈值？', kind: 'open', opts: [], st: 'wait', answer: null, ref: null },
  { no: 3, q: '已答题', kind: 'choice', opts: ['a'], st: 'answered', answer: 'a', ref: 'R2' },
]

const EVS: EvidenceItem[] = ['E1', 'E2'].map((id, i) => ({
  id, name: i ? '沟通记录.png' : '退款制度.pdf', ext: i ? 'png' : 'pdf', type: i ? '截图' : '文档',
  stars: 2, reg: '2026-09-29', state: 'ready', count: 0, path: '', missing: false,
}))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getClarifications).mockResolvedValue(CLARS.map(c => ({ ...c })))
  vi.mocked(answerClar).mockResolvedValue(CLARS[0])
  vi.mocked(answerClarOpen).mockResolvedValue(CLARS[1])
  vi.mocked(adoptClar).mockResolvedValue({ ...CLARS[1], st: 'answered', answer: '1万以下主管审批', ai: null })
  vi.mocked(ignoreClar).mockResolvedValue({ ...CLARS[1], ai: null })
})

let lastW: VueWrapper<any> | null = null
async function mountModal(toast?: (msg: string, cls?: string) => void) {
  const ClarModal = (await import('../ClarModal.vue')).default
  lastW?.unmount()
  lastW = mount(ClarModal, {
    props: { open: true, evidence: EVS },
    ...(toast ? { global: { provide: { toast } } } : {}),
  })
  await flushPromises()
  return lastW
}

describe('ClarModal（待确认弹窗·分段）', () => {
  it('分段 tab 实时计数，切换后已答复段显示答案与联动说明', async () => {
    const w = await mountModal()
    expect(w.find('.mask.open').exists()).toBe(true)
    const tabs = w.findAll('.tab').map(t => t.text())
    expect(tabs).toContain('等待 2')
    expect(tabs).toContain('已答复 1')
    expect(w.text()).toContain('冷却期多久？') // 默认等待段
    expect(w.text()).not.toContain('已答题')
    await w.findAll('.tab').find(t => t.text().includes('已答复'))!.trigger('click')
    expect(w.text()).toContain('已答题')
    expect(w.text()).toContain('答：a')
    expect(w.text()).toContain('R2 已自动核过') // 联动说明
  })

  it('等待空态与加载失败提示', async () => {
    vi.mocked(getClarifications).mockResolvedValueOnce([])
    const w = await mountModal()
    expect(w.text()).toContain('没有待确认项')
    vi.mocked(getClarifications).mockRejectedValueOnce(new ApiError(500, '后端炸了'))
    await w.setProps({ open: false })
    await w.setProps({ open: true })
    await flushPromises()
    expect(w.text()).toContain('加载失败（HTTP 500）：后端炸了')
  })
})

describe('ClarModal（记下答复）', () => {
  it('open 题材料佐证：文本+佐证材料一并提交 answerClarOpen 并 emit changed', async () => {
    const w = await mountModal()
    await w.find('textarea[aria-label="问题 2 记下答复"]').setValue('1 万元以下主管审批')
    await w.find('input[type="radio"][value="material"]').setValue()
    await w.find('select[aria-label="问题 2 佐证材料"]').setValue(['E1'])
    await w.find('button[aria-label="问题 2 提交答复"]').trigger('click')
    await flushPromises()
    expect(answerClarOpen).toHaveBeenCalledWith(2, '1 万元以下主管审批', ['E1'])
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('open 题口头确认为默认来源：ev_ids 空提交', async () => {
    const w = await mountModal()
    expect(w.find('select[aria-label="问题 2 佐证材料"]').exists()).toBe(false) // 默认口头：不渲染材料选择器
    await w.find('textarea[aria-label="问题 2 记下答复"]').setValue('口头说 7 天')
    await w.find('button[aria-label="问题 2 提交答复"]').trigger('click')
    await flushPromises()
    expect(answerClarOpen).toHaveBeenCalledWith(2, '口头说 7 天', [])
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('choice 题点选项记答复调 answerClar', async () => {
    const w = await mountModal()
    await w.findAll('.opt')[1].trigger('click') // 选 B（30天）
    await w.find('button[aria-label="问题 1 提交答复"]').trigger('click')
    await flushPromises()
    expect(answerClar).toHaveBeenCalledWith(1, 1)
    expect(w.emitted('changed')).toBeTruthy()
  })
})

describe('ClarModal（AI 代答卡）', () => {
  const AI_WAIT: Clarification = {
    no: 4, q: '退款阈值？', kind: 'open', opts: [], st: 'wait', answer: null, ref: 'R9',
    ai: { answer: '1万以下主管审批', quote: '制度原文：1万以下客服主管审批', ev_ids: ['E1'], conf: 'high', quote_ok: true },
  }
  const AI_DONE: Clarification = { ...AI_WAIT, st: 'answered', answer: '1万以下主管审批', ai: null }

  it('蓝条计数+材料名反查+摘录+置信徽章；采纳调 adoptClar 并从等待段落到已答复段', async () => {
    const toasts: string[] = []
    vi.mocked(getClarifications)
      .mockResolvedValueOnce([AI_WAIT, { ...CLARS[0] }])
      .mockResolvedValueOnce([AI_DONE, { ...CLARS[0] }])
    const w = await mountModal((msg, cls) => toasts.push(`${msg}|${cls ?? ''}`))
    expect(w.text()).toContain('AI 从材料找到 1 个可能答案') // 蓝条（等待段 ai 非空数）
    expect(w.text()).toContain('制度原文：1万以下客服主管审批') // ai.quote 摘录
    expect(w.text()).toContain('退款制度.pdf') // ai.ev_ids 反查材料名
    expect(w.text()).toContain('高置信')
    expect(w.find('textarea[aria-label="问题 4 记下答复"]').exists()).toBe(false) // 代答态不渲染人工表单
    await w.find('button[aria-label="问题 4 采纳"]').trigger('click')
    await flushPromises()
    expect(adoptClar).toHaveBeenCalledWith(4)
    expect(toasts.some(t => t.includes('R9 已自动核过') && t.includes('ok'))).toBe(true) // 联动核过 toast
    expect(w.emitted('changed')).toBeTruthy()
    expect(w.text()).not.toContain('AI 从材料找到') // 重拉后等待段无代答卡
    await w.findAll('.tab').find(t => t.text().includes('已答复'))!.trigger('click')
    expect(w.text()).toContain('答：1万以下主管审批') // 落到已答复段
  })

  it('忽略代答调 ignoreClar，卡片回归普通记答复表单', async () => {
    vi.mocked(getClarifications)
      .mockResolvedValueOnce([AI_WAIT])
      .mockResolvedValueOnce([{ ...AI_WAIT, ai: null }])
    const w = await mountModal()
    await w.find('button[aria-label="问题 4 忽略"]').trigger('click')
    await flushPromises()
    expect(ignoreClar).toHaveBeenCalledWith(4)
    expect(w.find('textarea[aria-label="问题 4 记下答复"]').exists()).toBe(true) // 回归人工作答
    expect(w.text()).not.toContain('AI 从材料找到')
  })
})
