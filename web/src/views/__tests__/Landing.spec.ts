// Task 6 Landing（空项目导入态）：api 全 mock；startJobPolling mock 掉避免轮询
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { generateReq, getEvidence, type EvidenceItem } from '../../api'
import Landing from '../Landing.vue'

vi.mock('../../api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail: unknown
    unqualified: string[] | null
    constructor(status: number, detail: unknown) {
      const d = detail instanceof Object && 'detail' in detail ? (detail as any).detail : detail
      super(typeof d === 'string' ? d : `HTTP ${status}`)
      this.status = status
      this.detail = d
      this.unqualified = null
    }
  },
  getEvidence: vi.fn().mockResolvedValue([]),
  addEvidence: vi.fn(),
  addEvidenceFile: vi.fn(),
  deleteEvidence: vi.fn(),
  generateReq: vi.fn().mockResolvedValue({ job_id: 'J1', total: 6 }),
}))
vi.mock('../../jobs', () => ({ startJobPolling: vi.fn() }))

const ev = (over: Partial<EvidenceItem>): EvidenceItem => ({
  id: 'DOC1', name: '整体方案.docx', ext: '', type: '文档', stars: 3, reg: '',
  state: 'pending', count: 0, path: '', missing: false, ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getEvidence).mockResolvedValue([])
  vi.mocked(generateReq).mockResolvedValue({ job_id: 'J1', total: 6 })
})

describe('Landing', () => {
  it('空池时渲染导入框，生成按钮禁用', async () => {
    const w = mount(Landing)
    await flushPromises()
    expect(w.text()).toContain('拖拽材料')
    const btn = w.findAll('button').find(b => b.text().includes('生成需求'))!
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    w.unmount()
  })

  it('有材料时点击生成按钮调 generateReq + startJobPolling 并 emit generated', async () => {
    vi.mocked(getEvidence).mockResolvedValue([ev({ id: 'DOC1', name: '整体方案.docx', type: '文档' })])
    const { startJobPolling } = await import('../../jobs')
    const w = mount(Landing)
    await flushPromises()
    expect(w.text()).toContain('整体方案.docx')
    const btn = w.findAll('button').find(b => b.text().includes('生成需求'))!
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
    await btn.trigger('click')
    await flushPromises()
    expect(generateReq).toHaveBeenCalledTimes(1)
    expect(startJobPolling).toHaveBeenCalledWith('J1', expect.any(Function))
    expect(w.emitted('generated')).toBeTruthy()
    w.unmount()
  })
})
