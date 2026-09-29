// Task 8：AskDrawerV2 正式化——接真实澄清 API，api 全 mock
// Task 9：追加 AI 代答区（quote/conf/来源、采纳/忽略）与材料投递条（入池→重检任务→完成重拉）
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import {
  ApiError,
  addEvidenceFile,
  adoptClar,
  answerClar,
  answerClarOpen,
  getClarifications,
  ignoreClar,
  reviewClars,
  verifyClar,
  type Clarification,
  type EvidenceItem,
} from '../../api'
import { jobRunning, startJobPolling } from '../../jobs'

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
  verifyClar: vi.fn(),
  addEvidenceFile: vi.fn(),
  reviewClars: vi.fn(),
  adoptClar: vi.fn(),
  ignoreClar: vi.fn(),
}))

vi.mock('../../jobs', async () => {
  const { ref } = await import('vue')
  return { startJobPolling: vi.fn(), jobRunning: ref(false) }
})

const CLARS: Clarification[] = [
  { no: 1, q: '冷却期多久？', kind: 'choice', opts: ['7天', '30天'], st: 'wait', answer: null, ref: 'R1' },
  { no: 2, q: '退款阈值？', kind: 'open', opts: [], st: 'wait', answer: null, ref: null },
  { no: 3, q: '已答题', kind: 'choice', opts: ['a'], st: 'answered', answer: 'a', ref: 'R2',
    ans: { kind: 'opt', text: 'a', ev_ids: [] } },
]

const evItem = (id: string): EvidenceItem => ({
  id, name: `${id}.pdf`, ext: 'pdf', type: '文档', stars: 1, reg: '2026-09-29',
  state: 'ready', count: 0, path: '', missing: false,
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getClarifications).mockResolvedValue(CLARS.map(c => ({ ...c })))
  vi.mocked(answerClar).mockResolvedValue(CLARS[0])
  vi.mocked(answerClarOpen).mockResolvedValue(CLARS[1])
  vi.mocked(verifyClar).mockResolvedValue(CLARS[2])
  vi.mocked(addEvidenceFile).mockResolvedValue(evItem('EV1'))
  vi.mocked(reviewClars).mockResolvedValue({ job_id: 'job-1', total: 1, questions: 2 })
  vi.mocked(adoptClar).mockResolvedValue({ ...CLARS[1], st: 'answered', answer: '1万以下主管审批', ai: null })
  vi.mocked(ignoreClar).mockResolvedValue({ ...CLARS[1], ai: null })
  jobRunning.value = false
})

let lastW: VueWrapper<any> | null = null
async function mountDrawer(toast?: (msg: string, cls?: string) => void, attachTo?: HTMLElement) {
  const AskDrawerV2 = (await import('../AskDrawerV2.vue')).default
  lastW?.unmount() // MaterialDrop 挂 document paste 监听 + jobRunning watch：卸旧实例防跨用例串扰
  lastW = mount(AskDrawerV2, {
    props: { open: true },
    ...(toast ? { global: { provide: { toast } } } : {}),
    ...(attachTo ? { attachTo } : {}),
  })
  await flushPromises()
  return lastW
}

describe('AskDrawerV2（澄清池抽屉）', () => {
  it('渲染待问 choice/open 题与已答折叠行', async () => {
    const w = await mountDrawer()
    expect(w.find('[role="dialog"][aria-modal="true"]').exists()).toBe(true)
    expect(w.text()).toContain('冷却期多久？')
    expect(w.text()).toContain('A. 7天') // choice 题选项带字母前缀
    expect(w.text()).toContain('补材料') // open 题题型徽章
    await w.findAll('.tab').find(t => t.text().includes('已答'))!.trigger('click')
    expect(w.findAll('.qc-row').length).toBeGreaterThanOrEqual(1) // 已答折叠行
  })

  it('choice 点选后「记录答案」调 answerClar 并 emit changed', async () => {
    const w = await mountDrawer()
    await w.findAll('.opt')[1].trigger('click') // 选 B（30天）
    await w.findAll('button').find(b => b.text() === '记录答案')!.trigger('click')
    await flushPromises()
    expect(answerClar).toHaveBeenCalledWith(1, 1)
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('open 题提交补充调 answerClarOpen 并 emit changed', async () => {
    const w = await mountDrawer()
    await w.find('textarea').setValue('1 万元以下客服主管审批')
    await w.findAll('button').find(b => b.text() === '提交补充')!.trigger('click')
    await flushPromises()
    expect(answerClarOpen).toHaveBeenCalledWith(2, '1 万元以下客服主管审批', [])
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('展开已答行点「标记已确认」调 verifyClar 并 emit changed', async () => {
    const w = await mountDrawer()
    await w.findAll('.tab').find(t => t.text().includes('已答'))!.trigger('click')
    await w.find('.qc-row').trigger('click')
    await w.findAll('button').find(b => b.text() === '标记已确认')!.trigger('click')
    await flushPromises()
    expect(verifyClar).toHaveBeenCalledWith(3)
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('旧数据无 kind 时按 opts 兜底判定题型', async () => {
    vi.mocked(getClarifications).mockResolvedValue([
      { no: 1, q: '旧选择题？', opts: ['x'], st: 'wait', answer: null, ref: null },
      { no: 2, q: '旧开放题？', opts: [], st: 'wait', answer: null, ref: null },
    ])
    const w = await mountDrawer()
    expect(w.text()).toContain('旧选择题？')
    const badges = w.findAll('.badge').map(b => b.text())
    expect(badges).toContain('选择题')
    expect(badges).toContain('补材料')
  })

  it('加载失败展示 HTTP 错误信息', async () => {
    vi.mocked(getClarifications).mockRejectedValueOnce(new ApiError(500, '后端炸了'))
    const w = await mountDrawer()
    expect(w.text()).toContain('加载失败（HTTP 500）：后端炸了')
  })

  it('导出提问文本区分选择题与补材料段', async () => {
    const w = await mountDrawer()
    await w.findAll('button').find(b => b.text().includes('导出提问文本'))!.trigger('click')
    const text = w.find('.q-export').text()
    expect(text).toContain('【需求确认 ×2】')
    expect(text).toContain('1. 冷却期多久？')
    expect(text).toContain('—— 需补充材料')
    expect(text).toContain('2. 退款阈值？')
  })
})

describe('AskDrawerV2（AI 代答 + 材料投递）', () => {
  const AI_CARD: Clarification = {
    no: 2, q: '退款阈值？', kind: 'open', opts: [], st: 'wait', answer: null, ref: null,
    ai: { answer: '1万以下主管审批', quote: '制度原文：1万以下客服主管审批', ev_ids: ['E1'], conf: 'high', quote_ok: true },
  }

  it('代答区渲染答案/摘录/来源数与高置信徽章，采纳调 adoptClar 并 emit changed', async () => {
    vi.mocked(getClarifications).mockResolvedValueOnce([{ ...AI_CARD }])
    const w = await mountDrawer()
    expect(w.text()).toContain('制度原文：1万以下客服主管审批') // 摘录原文
    expect(w.text()).toContain('高置信') // conf 徽章（high）
    expect(w.text()).toContain('AI 代答')
    expect(w.text()).toContain('1 份材料') // 来源数
    expect(w.find('textarea').exists()).toBe(false) // 代答态不渲染人工作答输入
    await w.findAll('button').find(b => b.text() === '采纳')!.trigger('click')
    await flushPromises()
    expect(adoptClar).toHaveBeenCalledWith(2)
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('quote_ok=false 时摘录后标注「摘录未校验」', async () => {
    vi.mocked(getClarifications).mockResolvedValueOnce([{
      ...AI_CARD, ai: { ...AI_CARD.ai!, quote_ok: false, conf: 'low' },
    }])
    const w = await mountDrawer()
    expect(w.text()).toContain('摘录未校验')
    expect(w.text()).toContain('低置信') // conf 徽章（low）
  })

  it('忽略代答调 ignoreClar，重拉后回归普通补材料题', async () => {
    vi.mocked(getClarifications).mockResolvedValueOnce([{ ...AI_CARD }])
    const w = await mountDrawer()
    await w.findAll('button').find(b => b.text() === '忽略')!.trigger('click')
    await flushPromises()
    expect(ignoreClar).toHaveBeenCalledWith(2)
    expect(w.find('textarea').exists()).toBe(true) // 回归普通 open 题人工输入
    expect(w.findAll('button').some(b => b.text() === '采纳')).toBe(false)
  })

  it('卡头按 ref 前缀显示来源徽章（R12→① 规则提取）', async () => {
    vi.mocked(getClarifications).mockResolvedValueOnce([
      { no: 5, q: '无依据规则转来的题？', kind: 'open', opts: [], st: 'wait', answer: null, ref: 'R12' },
      { no: 6, q: '无来源题？', kind: 'open', opts: [], st: 'wait', answer: null, ref: null },
    ])
    const w = await mountDrawer()
    expect(w.text()).toContain('① 规则提取')
    expect(w.text()).toContain('R12')
    expect(w.findAll('.badge').filter(b => b.text().includes('规则提取'))).toHaveLength(1) // ref=null 不显示
  })

  it('投递条选文件：逐份入池→reviewClars→startJobPolling', async () => {
    const w = await mountDrawer()
    const input = w.find('input[type="file"]')
    const f = new File(['制度内容'], '退款制度.pdf', { type: 'application/pdf' })
    Object.defineProperty(input.element, 'files', { value: [f], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(addEvidenceFile).toHaveBeenCalledWith(f, 'clar')
    expect(reviewClars).toHaveBeenCalledWith(['EV1'])
    expect(vi.mocked(startJobPolling)).toHaveBeenCalledWith('job-1', expect.any(Function))
  })

  it('超过 10MB 的文件拦截入池并 toast 提示', async () => {
    const toasts: string[] = []
    const w = await mountDrawer((msg, cls) => toasts.push(`${msg}|${cls ?? ''}`))
    const input = w.find('input[type="file"]')
    const big = new File([new ArrayBuffer(10 * 1024 * 1024 + 1)], '超大附件.pdf')
    Object.defineProperty(input.element, 'files', { value: [big], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(toasts.some(t => t.includes('文件超过 10MB：超大附件.pdf') && t.includes('warn'))).toBe(true)
    expect(addEvidenceFile).not.toHaveBeenCalled()
    expect(reviewClars).not.toHaveBeenCalled()
  })

  it('材料投递后任务完成（jobRunning→false）自动重拉列表', async () => {
    const w = await mountDrawer()
    const input = w.find('input[type="file"]')
    const f = new File(['制度内容'], '退款制度.pdf')
    Object.defineProperty(input.element, 'files', { value: [f], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(getClarifications).toHaveBeenCalledTimes(1) // 仅首拉
    jobRunning.value = true
    await nextTick()
    jobRunning.value = false
    await flushPromises()
    expect(getClarifications).toHaveBeenCalledTimes(2) // 任务完成重拉
  })

  it('粘贴文件走同一提交流（target 在抽屉内，冒泡到 document）', async () => {
    vi.mocked(addEvidenceFile).mockResolvedValueOnce(evItem('EV9'))
    vi.mocked(reviewClars).mockResolvedValueOnce({ job_id: 'job-9', total: 1, questions: 1 })
    // attachTo 才能让抽屉 DOM 进入 document 树，粘贴事件冒泡到 document 级监听
    const w = await mountDrawer(undefined, document.body)
    const f = new File(['截图内容'], '截图.png', { type: 'image/png' })
    const ev = new Event('paste', { bubbles: true })
    Object.defineProperty(ev, 'clipboardData', { value: { files: [f] }, configurable: true })
    w.find('.drawer').element.dispatchEvent(ev) // 粘贴焦点在抽屉内
    await flushPromises()
    expect(addEvidenceFile).toHaveBeenCalledWith(f, 'clar')
    expect(reviewClars).toHaveBeenCalledWith(['EV9'])
    expect(vi.mocked(startJobPolling)).toHaveBeenCalledWith('job-9', expect.any(Function))
  })

  it('粘贴 target 在抽屉外不投递（防与证据池视图的 window 粘贴双投递）', async () => {
    const w = await mountDrawer()
    expect(w.find('.drawer').exists()).toBe(true)
    const f = new File(['外部粘贴'], '外部.png')
    const ev = new Event('paste', { bubbles: true })
    Object.defineProperty(ev, 'clipboardData', { value: { files: [f] }, configurable: true })
    document.body.dispatchEvent(ev) // 粘贴焦点在抽屉外（证据池视图本体）
    await flushPromises()
    expect(addEvidenceFile).not.toHaveBeenCalled()
    expect(reviewClars).not.toHaveBeenCalled()
  })
})

// Task 10：open 题「+附件」——先逐份入池（source=clar）收 evIds，再随文本一起 answerClarOpen
describe('AskDrawerV2（open 题附件）', () => {
  async function attach(w: VueWrapper<any>, f: File) {
    const input = w.find('input[aria-label="问题 2 补充材料附件"]')
    Object.defineProperty(input.element, 'files', { value: [f], configurable: true })
    await input.trigger('change')
    await flushPromises()
  }

  it('选附件显示 chip，提交时先入池再随文本一起 answerClarOpen', async () => {
    vi.mocked(addEvidenceFile).mockResolvedValueOnce(evItem('E9'))
    const w = await mountDrawer()
    await attach(w, new File(['截图内容'], '阈值截图.png', { type: 'image/png' }))
    expect(w.text()).toContain('阈值截图.png') // 已选附件 chip
    await w.find('textarea').setValue('看图作答：阈值 1 万')
    await w.findAll('button').find(b => b.text() === '提交补充')!.trigger('click')
    await flushPromises()
    expect(addEvidenceFile).toHaveBeenCalledWith(expect.any(File), 'clar')
    expect(answerClarOpen).toHaveBeenCalledWith(2, '看图作答：阈值 1 万', ['E9'])
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('附件超过 10MB 拦截 toast，不进 chip 不入池', async () => {
    const toasts: string[] = []
    const w = await mountDrawer((msg, cls) => toasts.push(`${msg}|${cls ?? ''}`))
    await attach(w, new File([new ArrayBuffer(10 * 1024 * 1024 + 1)], '超大附件.pdf'))
    expect(toasts.some(t => t.includes('文件超过 10MB：超大附件.pdf') && t.includes('warn'))).toBe(true)
    expect(w.text()).not.toContain('超大附件.pdf')
    expect(addEvidenceFile).not.toHaveBeenCalled()
  })

  it('chip 可移除，移除后提交 evIds=[]', async () => {
    const w = await mountDrawer()
    await attach(w, new File(['x'], '废弃.png'))
    await w.find('.qc-chip button').trigger('click') // 移除附件
    expect(w.text()).not.toContain('废弃.png')
    await w.find('textarea').setValue('仅文本作答')
    await w.findAll('button').find(b => b.text() === '提交补充')!.trigger('click')
    await flushPromises()
    expect(addEvidenceFile).not.toHaveBeenCalled()
    expect(answerClarOpen).toHaveBeenCalledWith(2, '仅文本作答', [])
  })
})
