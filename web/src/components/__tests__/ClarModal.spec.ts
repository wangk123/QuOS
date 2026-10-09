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
  listJobs,
  reviewClars,
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
  listJobs: vi.fn(),
  reviewClars: vi.fn(),
}))

const CLARS: Clarification[] = [
  { no: 1, q: '冷却期多久？', kind: 'choice', type: 'confirm', opts: ['7天', '30天'], st: 'wait', answer: null, ref: 'R1' },
  { no: 2, q: '退款阈值？', kind: 'open', type: 'custom', opts: [], st: 'wait', answer: null, ref: null },
  { no: 3, q: '已答题', kind: 'choice', type: 'confirm', opts: ['a'], st: 'answered', answer: 'a', ref: 'R2' },
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
    expect(w.text()).toContain('条目未动（未核过）') // 联动说明（confirm 题答案非一致/不符 → 未核过分支）
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
  it('open 题材料佐证：文本+佐证材料 chips 点选一并提交 answerClarOpen 并 emit changed', async () => {
    const w = await mountModal()
    await w.find('textarea[aria-label="问题 2 记下答复"]').setValue('1 万元以下主管审批')
    await w.find('input[type="radio"][value="material"]').setValue()
    await w.find('[aria-label="问题 2 佐证材料"] .evchip').trigger('click') // 点「退款制度.pdf」chip 选中 E1
    await w.find('button[aria-label="问题 2 提交答复"]').trigger('click')
    await flushPromises()
    expect(answerClarOpen).toHaveBeenCalledWith(2, '1 万元以下主管审批', ['E1'])
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('open 题口头确认为默认来源：ev_ids 空提交', async () => {
    const w = await mountModal()
    expect(w.find('[aria-label="问题 2 佐证材料"]').exists()).toBe(false) // 默认口头：不渲染材料选择器
    await w.find('textarea[aria-label="问题 2 记下答复"]').setValue('口头说 7 天')
    await w.find('button[aria-label="问题 2 提交答复"]').trigger('click')
    await flushPromises()
    expect(answerClarOpen).toHaveBeenCalledWith(2, '口头说 7 天', [])
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('choice 题点选项记答复调 answerClar（extra 缺省空串）', async () => {
    const w = await mountModal()
    await w.findAll('.opt')[0].trigger('click') // 选 A（7天；confirm 一致侧，无需 extra）
    await w.find('button[aria-label="问题 1 提交答复"]').trigger('click')
    await flushPromises()
    expect(answerClar).toHaveBeenCalledWith(1, 0, '')
    expect(w.emitted('changed')).toBeTruthy()
  })
})

describe('ClarModal（AI 代答卡）', () => {
  const AI_WAIT: Clarification = {
    no: 4, q: '退款阈值？', kind: 'open', type: 'confirm', opts: [], st: 'wait', answer: null, ref: 'R9',
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

describe('ClarModal（题型四态：confirm 扩展交互 + done 按类型反馈）', () => {
  const TYPE_CLARS: Clarification[] = [
    { no: 1, q: '推测与实际一致吗？', opts: ['确认一致', '与实际不符', '不清楚'], kind: 'choice', type: 'confirm',
      st: 'wait', answer: null, ref: 'R12', ai: null, ans: null },
    { no: 2, q: '重试几次？', opts: ['重试 3 次', '重试 5 次'], kind: 'choice', type: 'choose',
      st: 'wait', answer: null, ref: 'C1', ai: null, ans: null },
  ]

  it('确认题：选「不符」展开必填框，提交带 extra；答后 done 卡显示改写反馈', async () => {
    vi.mocked(getClarifications).mockResolvedValue(TYPE_CLARS.map(c => ({ ...c })))
    const w = await mountModal(vi.fn())
    expect(w.text()).toContain('确认题') // 四态徽章
    const opts = w.findAll('.opt')
    await opts[1].trigger('click') // 与实际不符
    const ta = w.find('textarea[data-test="confirm-extra"]')
    expect(ta.exists()).toBe(true)
    expect(w.findAll('button').some(b => b.text() === '记下答复' && (b.element as HTMLButtonElement).disabled)).toBe(true)
    await ta.setValue('实际是静默跳过')
    vi.mocked(getClarifications).mockResolvedValue([{ ...TYPE_CLARS[0], st: 'answered', answer: '与实际不符',
      ans: { kind: 'opt', text: '与实际不符', ev_ids: [], extra: '实际是静默跳过' } }])
    vi.mocked(answerClar).mockResolvedValue(TYPE_CLARS[0])
    await w.findAll('button').find(b => b.text() === '记下答复')!.trigger('click')
    await flushPromises()
    expect(answerClar).toHaveBeenCalledWith(1, 1, '实际是静默跳过')
  })

  it('done 卡按类型反馈：confirm 不符=改写黄标 / choose=另一侧作废 / supply=入材料池', async () => {
    vi.mocked(getClarifications).mockResolvedValue([
      { ...TYPE_CLARS[0], st: 'answered', answer: '与实际不符',
        ans: { kind: 'opt', text: '与实际不符', ev_ids: [], extra: '实际是静默跳过' } },
      { ...TYPE_CLARS[1], st: 'answered', answer: '重试 3 次', ans: { kind: 'opt', text: '重试 3 次', ev_ids: [], extra: '' } },
      { no: 3, q: '未说明幂等键', opts: [], kind: 'open', type: 'supply', st: 'answered',
        answer: '受理单号+指纹', ref: 'G1', ai: null, ans: { kind: 'text', text: '受理单号+指纹', ev_ids: [] } },
    ])
    const w = await mountModal()
    await w.findAll('.tab').find(t => t.text().includes('已答复'))!.trigger('click')
    const dones = w.findAll('.q-card.done')
    expect(dones[0].text()).toContain('已按答复改写并标黄')
    expect(dones[0].text()).toContain('实际是静默跳过')
    expect(dones[1].text()).toContain('另一侧作废')
    expect(dones[2].text()).toContain('答复已存为材料池')
  })
})

describe('ClarModal（✦ AI 重检投递条）', () => {
  const EV = EVS[0] // 既有 EvidenceItem fixture（退款制度.pdf）

  it('AI 重检：选材料 → reviewClars + 轮询 job → 重拉列表并显示跳过说明', async () => {
    vi.mocked(getClarifications).mockResolvedValue([
      { no: 1, q: '推测一致吗？', opts: ['确认一致', '与实际不符', '不清楚'], kind: 'choice', type: 'confirm',
        st: 'wait', answer: null, ref: 'R1', ai: null, ans: null },
      { no: 2, q: '阈值边界行为？', opts: [], kind: 'open', type: 'supply',
        st: 'wait', answer: null, ref: 'G1', ai: null, ans: null },
    ])
    vi.mocked(reviewClars).mockResolvedValue({ job_id: 'J9', total: 1, questions: 1 })
    vi.mocked(listJobs).mockResolvedValue([{ id: 'J9', status: 'done' } as never])
    vi.mocked(getClarifications).mockResolvedValueOnce([]) // 初始
    const w = await mountModal(vi.fn())
    await w.find('[data-test="rb-evs"] .evchip').trigger('click') // 点材料 chip 选中 EV（退款制度.pdf）
    await w.find('button[data-test="rb-btn"]').trigger('click')
    await flushPromises()
    await new Promise(r => setTimeout(r, 700)) // 轮询间隔 500ms
    await flushPromises()
    expect(reviewClars).toHaveBeenCalledWith([EV.id])
    expect(w.text()).toContain('本次跳过：1 个确认题')
  })
})
