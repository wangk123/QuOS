// Task 12 视图冒烟测试：api 全 mock，断言各视图渲染核心数据行与交互按钮
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  answerClar,
  createBaseline,
  getAssertions,
  getCard,
  getClarifications,
  getConflicts,
  getDims,
  getDoc,
  getEvidence,
  getGaps,
  resolveConflict,
  verifyClar,
  listBaselines,
  getTree,
  type Assertion,
  type Card,
  type Clarification,
  type Conflict,
  type EvidenceItem,
  type Gap,
} from '../../api'
import { baseTag, curName, curPath, view } from '../../router'

vi.mock('../../api', () => ({
  PROJ: '风控云',
  ApiError: class ApiError extends Error {
    status: number
    unqualified: string[] | null = null
    constructor(status: number, detail: unknown) {
      super(typeof detail === 'string' ? detail : `HTTP ${status}`)
      this.status = status
    }
  },
  getEvidence: vi.fn(),
  addEvidence: vi.fn(),
  addEvidenceFile: vi.fn(),
  extractEvidence: vi.fn(),
  getAssertions: vi.fn(),
  verifyAll: vi.fn(),
  verifyOne: vi.fn(),
  getConflicts: vi.fn(),
  rescanConflicts: vi.fn(),
  resolveConflict: vi.fn(),
  getGaps: vi.fn(),
  rescanGaps: vi.fn(),
  disposeGap: vi.fn(),
  getDims: vi.fn(),
  setDims: vi.fn(),
  getTree: vi.fn(),
  treeOp: vi.fn(),
  assemble: vi.fn(),
  getCard: vi.fn(),
  getDoc: vi.fn(),
  getClarifications: vi.fn(),
  answerClar: vi.fn(),
  verifyClar: vi.fn(),
  createBaseline: vi.fn(),
  listBaselines: vi.fn(),
}))

const ev = (over: Partial<EvidenceItem>): EvidenceItem => ({
  id: 'TXT1', name: '材料', ext: '', type: '文本', stars: 2, reg: '2026-09-23',
  state: 'pending', count: 0, path: '', missing: false, ...over,
})
const asrt = (over: Partial<Assertion>): Assertion => ({
  id: 'A1', text: '断言', src: 'src', conf: '实证', st: 'open', verified: false, suspect: false, ...over,
})

const EVIDENCE: EvidenceItem[] = [ev({ id: 'REPO1', name: 'git@internal:loan.git', type: '仓库', stars: 3 })]
const ASSERTIONS: Assertion[] = [
  asrt({ id: 'A1', text: '回调超时 30s 触发重试', src: 'retry.py:15' }),
  asrt({ id: 'A2', text: '重试上限为 3 次', src: 'retry.py:42' }),
  asrt({ id: 'A3', text: '重试上限为 5 次', src: '设计文档§2', conf: '文档' }),
]
const CONFLICTS: Conflict[] = [
  { id: 'C1', a: 'A2', b: 'A3', q: '重试上限到底几次？', st: 'open', resolution: null },
]
const GAPS: Gap[] = [{ id: 'G1', dim: '状态', text: '「重试中」无出口', st: 'open' }]
const CLARS: Clarification[] = [
  { no: 1, q: '幂等键用哪个字段？', opts: ['放款流水号', '订单号'], st: 'wait', answer: null, ref: 'C1' },
]
const CARD: Card = {
  node: '放款/放款重试', goal: '不重复放款', entry: '回调超时 30s',
  flow: '① 入队 → ② 重发', rules: [
    { id: 'R1', text: '重试上限为 3 次', src: 'retry.py:42', conf: '实证' },
  ],
  states: '待放款 → 放款中', boundaries: '并发未覆盖', note: '口头约定', deps: '账务',
  unconfirmed: ['A3 重试上限为 5 次'],
}

beforeEach(() => {
  vi.clearAllMocks()
  curPath.value = '' // 共享视图状态复位
  view.value = 'v-ev'
  baseTag.value = '未建基线'
  vi.mocked(getEvidence).mockResolvedValue(EVIDENCE)
  vi.mocked(getAssertions).mockResolvedValue(ASSERTIONS)
  vi.mocked(getConflicts).mockResolvedValue(CONFLICTS)
  vi.mocked(getGaps).mockResolvedValue(GAPS)
  vi.mocked(getDims).mockResolvedValue(['状态', '异常'])
  vi.mocked(getCard).mockResolvedValue(CARD)
  vi.mocked(getClarifications).mockResolvedValue(CLARS)
  vi.mocked(listBaselines).mockResolvedValue([{ commit: 'abc1234', tag: 'v1', v: 1 }])
  vi.mocked(getTree).mockResolvedValue([])
  vi.mocked(getDoc).mockResolvedValue('# 结果文档\n正文')
})

describe('Pool.vue', () => {
  it('渲染智能输入框与材料行（类型徽章、提取按钮）', async () => {
    const Pool = (await import('../Pool.vue')).default
    const w = mount(Pool)
    await flushPromises()
    expect(w.find('input[placeholder*="粘贴"]').exists()).toBe(true)
    expect(w.text()).toContain('git@internal:loan.git')
    expect(w.text()).toContain('仓库')
    const btn = w.findAll('button').find(b => b.text() === '提取')
    expect(btn).toBeTruthy()
  })
})

describe('Fact.vue', () => {
  it('渲染断言行含置信度徽章与单点「核」按钮', async () => {
    const Fact = (await import('../Fact.vue')).default
    const w = mount(Fact)
    await flushPromises()
    expect(w.text()).toContain('回调超时 30s 触发重试')
    expect(w.text()).toContain('retry.py:42')
    const badges = w.findAll('.badge').map(b => b.text())
    expect(badges).toContain('代码实证') // conf=实证 的徽章文案
    expect(w.findAll('button').some(b => b.text() === '核')).toBe(true)
  })
})

describe('Conflict.vue', () => {
  it('渲染冲突对左右断言与三选裁决按钮', async () => {
    const Conflict = (await import('../Conflict.vue')).default
    const w = mount(Conflict)
    await flushPromises()
    expect(w.text()).toContain('重试上限为 3 次')
    expect(w.text()).toContain('重试上限为 5 次')
    expect(w.find('.vs').text()).toBe('VS')
    expect(w.text()).toContain('重试上限到底几次？')
    const texts = w.findAll('button').map(b => b.text())
    expect(texts).toContain('信 A2')
    expect(texts).toContain('信 A3')
    expect(texts).toContain('转问人')
  })

  it('点击「信 A2」调 resolveConflict(code/a)', async () => {
    vi.mocked(resolveConflict).mockResolvedValue(CONFLICTS[0])
    const Conflict = (await import('../Conflict.vue')).default
    const w = mount(Conflict)
    await flushPromises()
    await w.findAll('button').find(b => b.text() === '信 A2')!.trigger('click')
    await flushPromises()
    expect(resolveConflict).toHaveBeenCalledWith('C1', 'code', 'a')
  })
})

describe('Gap.vue', () => {
  it('按维度分组渲染空白项与处置按钮', async () => {
    const Gap = (await import('../Gap.vue')).default
    const w = mount(Gap)
    await flushPromises()
    const group = w.find('.gap-group')
    expect(group.exists()).toBe(true)
    expect(group.find('.g-hd').text()).toContain('状态')
    expect(w.text()).toContain('「重试中」无出口')
    const texts = w.findAll('button').map(b => b.text())
    expect(texts).toContain('转问人')
    expect(texts).toContain('设计如此')
    expect(w.findAll('button').some(b => b.text().includes('AI 重扫'))).toBe(true)
  })
})

describe('Card.vue', () => {
  it('渲染卡片字段与规则行', async () => {
    curPath.value = '0,1'
    const Card = (await import('../Card.vue')).default
    const w = mount(Card)
    await flushPromises()
    expect(w.text()).toContain('放款/放款重试')
    expect(w.text()).toContain('不重复放款')
    expect(w.text()).toContain('重试上限为 3 次')
    expect(w.find('.rule-row').exists()).toBe(true)
    expect(w.findAll('button').some(b => b.text().includes('预览结果文档'))).toBe(true)
  })
})

describe('Ask.vue', () => {
  it('渲染待问行：问题、选项与状态徽章', async () => {
    const Ask = (await import('../Ask.vue')).default
    const w = mount(Ask)
    await flushPromises()
    expect(w.text()).toContain('幂等键用哪个字段？')
    expect(w.text()).toContain('A. 放款流水号')
    expect(w.text()).toContain('待问')
  })
})

describe('Save.vue', () => {
  it('渲染存档预览、并入基线按钮与基线时间线', async () => {
    curPath.value = '0,1'
    const Save = (await import('../Save.vue')).default
    const w = mount(Save)
    await flushPromises()
    expect(w.text()).toContain('存档预览')
    expect(w.findAll('button').some(b => b.text().includes('并入基线'))).toBe(true)
    expect(w.find('.tl-item').text()).toContain('v1')
  })

  it('点击并入基线调 createBaseline 并刷新时间线', async () => {
    vi.mocked(createBaseline).mockResolvedValue({ commit: 'def5678', tag: 'v2', v: 2 })
    curPath.value = '0,1'
    const Save = (await import('../Save.vue')).default
    const w = mount(Save)
    await flushPromises()
    await w.findAll('button').find(b => b.text().includes('并入基线'))!.trigger('click')
    await flushPromises()
    expect(createBaseline).toHaveBeenCalled()
    expect(listBaselines).toHaveBeenCalled()
  })
})

describe('Ask 交互', () => {
  it('记录答案调 answerClar', async () => {
    vi.mocked(answerClar).mockResolvedValue({ ...CLARS[0], st: 'answered', answer: '放款流水号' })
    const Ask = (await import('../Ask.vue')).default
    const w = mount(Ask)
    await flushPromises()
    await w.findAll('button').find(b => b.text() === '记录')!.trigger('click')
    await flushPromises()
    expect(answerClar).toHaveBeenCalledWith(1, 0)
  })

  it('已答行显示「标记已确认」按钮（非「落码验证」）', async () => {
    vi.mocked(getClarifications).mockResolvedValue([
      { ...CLARS[0], st: 'answered', answer: '放款流水号' },
    ])
    const Ask = (await import('../Ask.vue')).default
    const w = mount(Ask)
    await flushPromises()
    const texts = w.findAll('button').map(b => b.text())
    expect(texts).toContain('标记已确认')
    expect(texts).not.toContain('落码验证')
  })

  it('点击「标记已确认」调 verifyClar 且 toast 不再宣称已实证', async () => {
    const toasts: string[] = []
    vi.mocked(verifyClar).mockResolvedValue({ ...CLARS[0], st: 'verified', answer: '放款流水号' })
    vi.mocked(getClarifications).mockResolvedValue([
      { ...CLARS[0], st: 'answered', answer: '放款流水号' },
    ])
    const Ask = (await import('../Ask.vue')).default
    const w = mount(Ask, { global: { provide: { toast: (msg: string) => { toasts.push(msg) } } } })
    await flushPromises()
    await w.findAll('button').find(b => b.text() === '标记已确认')!.trigger('click')
    await flushPromises()
    expect(verifyClar).toHaveBeenCalledWith(1)
    expect(toasts.some(t => t.includes('已标记确认'))).toBe(true)
    expect(toasts.some(t => t.includes('已实证'))).toBe(false)
  })
})

describe('Card 空态', () => {
  it('节点无卡片（404）时显示组装引导', async () => {
    vi.mocked(getCard).mockRejectedValueOnce(new ApiError(404, '节点无卡片'))
    curPath.value = '0,1'
    const Card = (await import('../Card.vue')).default
    const w = mount(Card)
    await flushPromises()
    expect(w.text()).toContain('AI 组装卡片草稿')
  })
})

describe('基线「当前」标记（gitops 升序返回，取最新）', () => {
  const TWO = [
    { commit: 'a1111111111111111111111111111', tag: 'v1', v: 1 },
    { commit: 'b2222222222222222222222222222', tag: 'v2', v: 2 },
  ]

  it('App 顶栏显示最新 v2，v-base 时间线最后一项带 cur', async () => {
    vi.mocked(listBaselines).mockResolvedValue(TWO)
    const App = (await import('../../App.vue')).default
    const w = mount(App)
    await flushPromises()
    expect(w.find('.baseline-tag').text()).toContain('v2')
    expect(w.find('.baseline-tag').text()).toContain('b222222')
    await w.findAll('nav .step').find(b => b.text() === '基线')!.trigger('click')
    await flushPromises()
    const items = w.findAll('.tl-item')
    expect(items.length).toBe(2)
    expect(items[0].classes()).not.toContain('cur')
    expect(items[0].text()).not.toContain('当前')
    expect(items[1].classes()).toContain('cur')
    expect(items[1].text()).toContain('v2')
    expect(items[1].text()).toContain('当前')
    w.unmount() // 卸载，避免残留 watcher 覆写共享 curName
  })

  it('Save 时间线最后一项带 cur（当前=v2）', async () => {
    vi.mocked(listBaselines).mockResolvedValue(TWO)
    curPath.value = '0,1'
    const Save = (await import('../Save.vue')).default
    const w = mount(Save)
    await flushPromises()
    const items = w.findAll('.tl-item')
    expect(items.length).toBe(2)
    expect(items[0].classes()).not.toContain('cur')
    expect(items[1].classes()).toContain('cur')
    expect(items[1].text()).toContain('v2')
  })

  it('Save 并入基线 note 用节点名而非数字路径', async () => {
    vi.mocked(createBaseline).mockResolvedValue({ commit: 'def5678', tag: 'v2', v: 2 })
    curPath.value = '0,1'
    curName.value = '放款重试'
    const Save = (await import('../Save.vue')).default
    const w = mount(Save)
    await flushPromises()
    await w.findAll('button').find(b => b.text().includes('并入基线'))!.trigger('click')
    await flushPromises()
    expect(createBaseline).toHaveBeenCalledWith('放款重试 并入基线')
  })
})
