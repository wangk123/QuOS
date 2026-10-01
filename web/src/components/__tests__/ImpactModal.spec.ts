// Task 17：影响分析弹窗——打开即分析渲染方案卡 / 默认选中 AI 推荐 / 执行调 regen+startJobPolling / 空新材料提示（api、jobs 全 mock）
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { impactAnalyse, regen, type EvidenceItem, type ImpactPlan } from '../../api'
import { startJobPolling } from '../../jobs'

vi.mock('../../api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number, detail: unknown) {
      const d = detail instanceof Object && 'detail' in detail ? (detail as any).detail : detail
      super(typeof d === 'string' ? d : `HTTP ${status}`)
      this.status = status
    }
  },
  impactAnalyse: vi.fn(),
  regen: vi.fn(),
}))
vi.mock('../../jobs', () => ({ startJobPolling: vi.fn() }))

const PLAN: ImpactPlan = {
  nodes: ['工具模块/工商信息查询'],
  rule_ids: ['R11'],
  clar_nos: ['Q1'],
  mode: 'partial',
  reason: '新材料仅修正该节点的输入行为',
  recommend: 'partial',
}

const EVS: EvidenceItem[] = [
  { id: 'E1', name: '工商信息查询补充说明.docx', ext: 'docx', type: '文档', stars: 3, reg: '2026-10-01',
    state: 'ready', count: 0, path: '', missing: false },
  { id: 'E2', name: '已并入需求.pdf', ext: 'pdf', type: '文档', stars: 2, reg: '2026-09-30',
    state: 'extracted', count: 5, path: '', missing: false },
]

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(impactAnalyse).mockResolvedValue({ ...PLAN })
  vi.mocked(regen).mockResolvedValue({ job_id: 'J1' })
  vi.mocked(startJobPolling).mockImplementation(() => {})
})

let lastW: VueWrapper<any> | null = null
async function mountModal(props: Partial<{ open: boolean; evIds: string[]; evidence: EvidenceItem[] }> = {}) {
  const ImpactModal = (await import('../ImpactModal.vue')).default
  lastW?.unmount()
  lastW = mount(ImpactModal, { props: { open: true, evIds: ['E1'], evidence: EVS, ...props } })
  await flushPromises()
  return lastW
}

describe('ImpactModal（影响分析弹窗）', () => {
  it('加载中骨架 → 渲染新材料条/关联清单/reason，默认选中 AI 推荐的 partial 卡', async () => {
    let resolve!: (p: ImpactPlan) => void
    vi.mocked(impactAnalyse).mockReturnValueOnce(new Promise(r => (resolve = r)))
    const w = await mountModal()
    expect(impactAnalyse).toHaveBeenCalledWith(['E1'])
    expect(w.find('.doing-box').exists()).toBe(true) // 加载中 doing-box+skel
    expect(w.findAll('.skel').length).toBeGreaterThan(0)
    resolve({ ...PLAN })
    await flushPromises()
    expect(w.find('.doing-box').exists()).toBe(false)

    expect(w.findAll('.newev').length).toBe(1) // 只列 evIds 命中的 E1，不含已并入的 E2
    expect(w.find('.newev').text()).toContain('工商信息查询补充说明.docx')
    expect(w.find('.newev').text()).toContain('★★★')
    expect(w.text()).not.toContain('已并入需求.pdf')

    const rows = w.findAll('.relrow').map(r => r.text())
    expect(rows.some(t => t.includes('1 个节点') && t.includes('工具模块/工商信息查询'))).toBe(true)
    expect(rows.some(t => t.includes('1 条条目') && t.includes('R11'))).toBe(true)
    expect(rows.some(t => t.includes('1 个待确认') && t.includes('Q1'))).toBe(true)
    expect(w.text()).toContain('新材料仅修正该节点的输入行为') // reason

    expect(w.findAll('.optcard').length).toBe(3)
    const sel = w.find('.optcard.sel')
    expect(sel.exists()).toBe(true)
    expect(sel.text()).toContain('局部重新生成')
    expect(sel.text()).toContain('AI 推荐') // recommend=partial 卡带推荐徽章
  })

  it('空段显示「无关联」（对空 plan 的容错）', async () => {
    vi.mocked(impactAnalyse).mockResolvedValueOnce({ ...PLAN, nodes: [], rule_ids: [], clar_nos: [] })
    const w = await mountModal()
    expect(w.findAll('.relrow').filter(r => r.text().includes('无关联')).length).toBe(3)
  })

  it('点「按所选方案执行」→ regen(partial, evIds, nodes)+startJobPolling+emit done/close', async () => {
    const w = await mountModal()
    await w.findAll('button').find(b => b.text().includes('按所选方案执行'))!.trigger('click')
    await flushPromises()
    expect(regen).toHaveBeenCalledWith('partial', ['E1'], ['工具模块/工商信息查询'])
    expect(startJobPolling).toHaveBeenCalledWith('J1', expect.any(Function))
    expect(w.emitted('done')).toBeTruthy()
    expect(w.emitted('close')).toBeTruthy()
  })

  it('改选 full → nodes 不传局部目标（空数组）', async () => {
    const w = await mountModal()
    await w.findAll('.optcard').find(c => c.text().includes('全量重新生成'))!.trigger('click')
    expect(w.find('.optcard.sel').text()).toContain('全量重新生成')
    await w.findAll('button').find(b => b.text().includes('按所选方案执行'))!.trigger('click')
    await flushPromises()
    expect(regen).toHaveBeenCalledWith('full', ['E1'], [])
  })

  it('无新材料（evIds 空）显示提示、不分析、不出执行按钮', async () => {
    const w = await mountModal({ evIds: [] })
    expect(w.text()).toContain('没有新材料——重新生成前先补充材料')
    expect(impactAnalyse).not.toHaveBeenCalled()
    expect(w.findAll('button').some(b => b.text().includes('按所选方案执行'))).toBe(false)
  })

  it('分析失败显示错误，不出方案卡', async () => {
    const { ApiError } = await import('../../api')
    vi.mocked(impactAnalyse).mockRejectedValueOnce(new ApiError(500, '后端炸了'))
    const w = await mountModal()
    expect(w.text()).toContain('分析失败（HTTP 500）：后端炸了')
    expect(w.findAll('.optcard').length).toBe(0)
  })
})
