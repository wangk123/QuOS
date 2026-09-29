// Task 12 视图冒烟测试：api 全 mock，断言各视图渲染核心数据行与交互按钮
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import {
  ApiError,
  answerClar,
  assembleBatch,
  createBaseline,
  listJobs,
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
  scaffoldTree,
  setAssertionNode,
  type Assertion,
  type Card,
  type Clarification,
  type Conflict,
  type EvidenceItem,
  type Gap,
  type TreeNode,
} from '../../api'
import { aiBusy, baseTag, curName, curPath, view, top } from '../../router'

vi.mock('../../api', () => ({
  curSlug: ref('演示项目'),
  setProject: vi.fn(),
  openProject: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number
    unqualified: string[] | null
    // 与真实实现一致：detail 可能是 FastAPI 包裹体 {detail: {unqualified: [...]}}
    constructor(status: number, detail: unknown) {
      const d = detail instanceof Object && 'detail' in detail ? (detail as any).detail : detail
      super(typeof d === 'string' ? d : `HTTP ${status}`)
      this.status = status
      this.unqualified = d && typeof d === 'object' && Array.isArray((d as any).unqualified) ? (d as any).unqualified : null
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
  scaffoldTree: vi.fn(),
  setAssertionNode: vi.fn(),
  assemble: vi.fn(),
  assembleBatch: vi.fn(),
  listJobs: vi.fn(),
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
// Fact 分组场景：树带 P0/P1/P2 标记，规则分挂各功能点
const FACT_TREE: TreeNode[] = [
  { name: '支付', children: [{ name: '放款重试', children: [], open: true, priority: 'P1' }], open: true, priority: '' },
  { name: '风控', children: [
    { name: '额度', children: [], open: true, priority: 'P0' },
    { name: '黑名单', children: [], open: true, priority: '' },
  ], open: true, priority: 'P2' },
]
const GROUPED: Assertion[] = [
  asrt({ id: 'A1', text: '回调超时 30s 触发重试', src: 'retry.py:15', node: '支付/放款重试', verified: true }),
  asrt({ id: 'A2', text: '重试上限为 3 次', src: 'retry.py:42', node: '风控/额度', verified: true }),
  asrt({ id: 'A3', text: '重试上限为 5 次', src: '设计文档§2', conf: '文档', node: '风控/额度' }),
  asrt({ id: 'A4', text: '黑名单 T+1 生效', src: 'risk.py:7', node: '风控/黑名单' }),
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
  aiBusy.value = null
  curName.value = '（未选中节点）'
  view.value = 'v-ev'
  baseTag.value = '未建基线'
  top.value = 'proj' // App 挂载处于工作台态（默认 home 会渲染项目首页）
  location.hash = '#/p/演示项目' // 配套工作台 hash：App onMounted 的 syncFromHash 需一致才不被拉回 home
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
  it('无树时规则落未归类桶，行内含置信度徽章与单点「核」按钮', async () => {
    const Fact = (await import('../Fact.vue')).default
    const w = mount(Fact)
    await flushPromises()
    expect(w.find('.unclass-box').text()).toContain('未归类 · 3 条')
    expect(w.text()).toContain('回调超时 30s 触发重试')
    expect(w.text()).toContain('retry.py:42')
    const badges = w.findAll('.badge').map(b => b.text())
    expect(badges).toContain('代码实证') // conf=实证 的徽章文案
    expect(w.findAll('button').some(b => b.text() === '核')).toBe(true)
  })

  it('按模块›功能点分组：组头序列、P0 先行、功能点头带核验 x/y（默认收起，全部展开后可见）', async () => {
    vi.mocked(getTree).mockResolvedValue(FACT_TREE)
    vi.mocked(getAssertions).mockResolvedValue(GROUPED)
    const Fact = (await import('../Fact.vue')).default
    const w = mount(Fact)
    await flushPromises()
    expect(w.findAll('.grp-hd').map(h => h.find('b').text())).toEqual(['支付', '风控']) // 组按树序
    expect(w.findAll('.pt-hd')).toHaveLength(0) // 默认收起：长列表不整页铺开
    await w.findAll('button').find(b => b.text() === '全部展开')!.trigger('click')
    const pts = w.findAll('.pt-hd').map(h => h.text())
    expect(pts).toHaveLength(3)
    expect(pts[0]).toContain('支付/放款重试')
    expect(pts[1]).toContain('风控/额度')
    expect(pts[1]).toContain('P0') // P0 排在同组无标记的黑名单前
    expect(pts[1]).toContain('核验 1/2')
    expect(pts[2]).toContain('风控/黑名单')
    expect(w.text()).toContain('重试上限为 3 次') // 组内规则行照常渲染
  })

  it('点击组头折叠/展开该组', async () => {
    vi.mocked(getTree).mockResolvedValue(FACT_TREE)
    vi.mocked(getAssertions).mockResolvedValue(GROUPED)
    const Fact = (await import('../Fact.vue')).default
    const w = mount(Fact)
    await flushPromises()
    await w.findAll('button').find(b => b.text() === '全部展开')!.trigger('click')
    await w.findAll('.grp-hd')[1].trigger('click') // 折叠「风控」
    expect(w.text()).not.toContain('重试上限为 3 次')
    expect(w.findAll('.pt-hd')).toHaveLength(1) // 只剩「支付」组的功能点
    await w.findAll('.grp-hd')[1].trigger('click') // 再点展开
    expect(w.text()).toContain('重试上限为 3 次')
  })

  it('选中节点时规则表聚焦其子树（父节点含子节点，统计联动）', async () => {
    vi.mocked(getTree).mockResolvedValue(FACT_TREE)
    vi.mocked(getAssertions).mockResolvedValue(GROUPED)
    curPath.value = '1' // 风控（父节点）
    curName.value = '风控' // curName 由 App 的 watch 计算，单挂 Fact 需手动同步
    const Fact = (await import('../Fact.vue')).default
    const w = mount(Fact)
    await flushPromises()
    expect(w.text()).toContain('风控（含子树）')
    expect(w.find('.stat b').text()).toBe('3') // A2/A3/A4 都在 风控 子树内
    await w.findAll('button').find(b => b.text() === '全部展开')!.trigger('click')
    expect(w.findAll('.grp-hd').map(h => h.find('b').text())).toEqual(['风控']) // 只剩风控组
    expect(w.text()).not.toContain('回调超时 30s 触发重试') // 支付组规则不进视野
  })

  it('未归类行选路径挂载调 setAssertionNode（选项 2 空格缩进/层）', async () => {
    vi.mocked(getTree).mockResolvedValue(FACT_TREE)
    const Fact = (await import('../Fact.vue')).default
    const w = mount(Fact)
    await flushPromises()
    const row = w.findAll('.unclass-box tbody tr').find(r => r.text().includes('回调超时'))!
    const sel = row.find('select')
    const opt = sel.findAll('option').find(o => o.text().includes('风控/额度'))!
    expect((opt.element as HTMLOptionElement).textContent).toBe('  风控/额度') // 二级节点缩进两格，value 为原始路径
    await sel.setValue('风控/额度')
    await flushPromises()
    expect(setAssertionNode).toHaveBeenCalledWith('A1', '风控/额度')
  })

  it('树空时渲染骨架引导块，点击「AI 从证据池生成」调 scaffoldTree', async () => {
    vi.mocked(scaffoldTree).mockResolvedValue(FACT_TREE)
    const Fact = (await import('../Fact.vue')).default
    const w = mount(Fact)
    await flushPromises()
    const guide = w.find('.scaffold-guide')
    expect(guide.exists()).toBe(true)
    expect(guide.text()).toContain('功能树还没有骨架')
    expect(guide.text()).toContain('手工在左侧添加节点')
    const aiBtn = w.findAll('button').find(b => b.text() === 'AI 从证据池生成')!
    expect((aiBtn.element as HTMLButtonElement).disabled).toBe(false) // 证据池非空可点
    await aiBtn.trigger('click')
    await flushPromises()
    expect(scaffoldTree).toHaveBeenCalledTimes(1)
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
    expect(texts).toContain('转澄清')
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
    expect(texts).toContain('转澄清')
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
    w.unmount() // 卸载 curPath watcher，避免残留组件抢先消耗后续用例的一次性 mock
  })

  it('切换树节点时重新拉取该节点画像（同视图不重挂载）', async () => {
    curPath.value = '0,0'
    const Card = (await import('../Card.vue')).default
    const w = mount(Card)
    await flushPromises()
    expect(getCard).toHaveBeenCalledWith('0,0')
    curPath.value = '0,1'
    await flushPromises()
    expect(getCard).toHaveBeenCalledWith('0,1')
    w.unmount() // 卸载 curPath watcher，避免残留组件抢先消耗后续用例的一次性 mock
  })
})

describe('AskDrawer（顶栏澄清池抽屉）', () => {
  it('open 时拉取并渲染待问行：问题、选项与状态徽章', async () => {
    const AskDrawer = (await import('../../components/AskDrawer.vue')).default
    const w = mount(AskDrawer, { props: { open: false } })
    await w.setProps({ open: true })
    await flushPromises()
    expect(w.find('[role="dialog"][aria-modal="true"]').exists()).toBe(true)
    expect(w.text()).toContain('幂等键用哪个字段？')
    expect(w.text()).toContain('A. 放款流水号')
    expect(w.text()).toContain('待问')
  })

  it('空态文案指向冲突/缺口/无依据规则来源', async () => {
    vi.mocked(getClarifications).mockResolvedValueOnce([])
    const AskDrawer = (await import('../../components/AskDrawer.vue')).default
    const w = mount(AskDrawer, { props: { open: false } })
    await w.setProps({ open: true })
    await flushPromises()
    expect(w.text()).toContain('空——②冲突、④缺口、①无依据规则可转到这里')
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
    w.unmount() // 卸载 curPath watcher，避免残留组件抢先消耗后续用例的一次性 mock
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
    w.unmount() // 同上
  })
})

describe('Ask 交互', () => {
  it('记录答案调 answerClar 并 emit changed（App 重算角标）', async () => {
    vi.mocked(answerClar).mockResolvedValue({ ...CLARS[0], st: 'answered', answer: '放款流水号' })
    const AskDrawer = (await import('../../components/AskDrawer.vue')).default
    const w = mount(AskDrawer, { props: { open: false } })
    await w.setProps({ open: true })
    await flushPromises()
    await w.findAll('button').find(b => b.text() === '记录')!.trigger('click')
    await flushPromises()
    expect(answerClar).toHaveBeenCalledWith(1, 0)
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('已答行显示「标记已确认」按钮（非「落码验证」）', async () => {
    vi.mocked(getClarifications).mockResolvedValue([
      { ...CLARS[0], st: 'answered', answer: '放款流水号' },
    ])
    const AskDrawer = (await import('../../components/AskDrawer.vue')).default
    const w = mount(AskDrawer, { props: { open: false } })
    await w.setProps({ open: true })
    await flushPromises()
    const texts = w.findAll('button').map(b => b.text())
    expect(texts).toContain('标记已确认')
    expect(texts).not.toContain('落码验证')
  })

  it('点击「标记已确认」调 verifyClar、emit changed 且 toast 不再宣称已实证', async () => {
    const toasts: string[] = []
    vi.mocked(verifyClar).mockResolvedValue({ ...CLARS[0], st: 'verified', answer: '放款流水号' })
    vi.mocked(getClarifications).mockResolvedValue([
      { ...CLARS[0], st: 'answered', answer: '放款流水号' },
    ])
    const AskDrawer = (await import('../../components/AskDrawer.vue')).default
    const w = mount(AskDrawer, {
      props: { open: false },
      global: { provide: { toast: (msg: string) => { toasts.push(msg) } } },
    })
    await w.setProps({ open: true })
    await flushPromises()
    await w.findAll('button').find(b => b.text() === '标记已确认')!.trigger('click')
    await flushPromises()
    expect(verifyClar).toHaveBeenCalledWith(1)
    expect(w.emitted('changed')).toBeTruthy()
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
    expect(w.text()).toContain('生成选中（含子树）')
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

describe('全局 AI 进度条（aiBusy 挂 App，切视图不丢）', () => {
  it('aiBusy 非空时 App 渲染进度条，含 x/y 真实进度', async () => {
    aiBusy.value = { label: 'AI 生成画像 · 支付/放款重试', cur: 2, total: 5 }
    const App = (await import('../../App.vue')).default
    const w = mount(App)
    await flushPromises()
    expect(w.find('.global-ai').exists()).toBe(true)
    expect(w.find('.global-ai').text()).toContain('AI 生成画像 · 支付/放款重试')
    expect(w.find('.global-ai').text()).toContain('（2/5）')
    expect((w.find('.global-ai .bar i').element as HTMLElement).style.width).toBe('40%')
    w.unmount()
  })

  it('aiBusy 为 null 时进度条不渲染', async () => {
    const App = (await import('../../App.vue')).default
    const w = mount(App)
    await flushPromises()
    expect(w.find('.global-ai').exists()).toBe(false)
    w.unmount()
  })
})

describe('Card.vue 批量生成（后台任务 + 轮询）', () => {
  it('点「生成全部叶子」创建任务并轮询到 done：进度/汇总来自后端 job', async () => {
    vi.mocked(assembleBatch).mockResolvedValue({ job_id: 'J1', total: 2 })
    vi.mocked(listJobs).mockResolvedValue([
      { id: 'J1', kind: 'assemble-batch', label: 'AI 生成画像 · 风控', cur: 2, total: 2,
        status: 'done', ok: 1, skipped: ['支付/放款重试'], blocked: ['风控'], failed: 0,
        started_at: 1, finished_at: 2 },
    ])
    const { jobRunning } = await import('../../jobs')
    const Card = (await import('../Card.vue')).default
    const toasts: string[] = []
    const w = mount(Card, { global: { provide: { toast: (m: string) => { toasts.push(m) } } } })
    await flushPromises()
    await w.findAll('button').find(b => b.text().includes('生成全部叶子'))!.trigger('click')
    await flushPromises()
    expect(assembleBatch).toHaveBeenCalledWith('')
    expect(toasts.join()).toContain('批量任务已创建')
    expect(toasts.join()).toContain('成功 1 张')
    expect(toasts.join()).toContain('跳过 1')
    expect(toasts.join()).toContain('阻断 1')
    expect(jobRunning.value).toBe(false) // done 后复位
    expect(aiBusy.value).toBeNull()
    w.unmount()
  })
})
