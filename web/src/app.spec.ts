// App 壳冒烟：全局 AI 进度条（aiBusy 挂 App 级，Workbench/弹窗共用）；api 全 mock
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { getClarifications, getEvidence, listBaselines, wbSummary } from './api'
import { aiBusy, top } from './router'

vi.mock('./api', () => ({
  curSlug: ref('演示项目'),
  setProject: vi.fn(),
  openProject: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number
    unqualified: string[] | null
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
  deleteEvidence: vi.fn(),
  generateReq: vi.fn(),
  getRules: vi.fn(),
  verifyJob: vi.fn(),
  confirmRule: vi.fn(),
  askRule: vi.fn(),
  getConflicts: vi.fn(),
  resolveConflict: vi.fn(),
  getGaps: vi.fn(),
  disposeGap: vi.fn(),
  getDims: vi.fn(),
  setDims: vi.fn(),
  getTree: vi.fn(),
  treeOp: vi.fn(),
  setRuleNode: vi.fn(),
  listJobs: vi.fn(),
  getProfile: vi.fn(),
  patchProfileGoal: vi.fn(),
  listProfiles: vi.fn(),
  getDoc: vi.fn(),
  getClarifications: vi.fn(),
  answerClar: vi.fn(),
  answerClarOpen: vi.fn(),
  adoptClar: vi.fn(),
  ignoreClar: vi.fn(),
  reviewClars: vi.fn(),
  verifyClar: vi.fn(),
  createBaseline: vi.fn(),
  listBaselines: vi.fn(),
  wbSummary: vi.fn(),
  generateCancel: vi.fn(),
  impactAnalyse: vi.fn(),
  regen: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
  aiBusy.value = null
  top.value = 'proj' // App 挂载处于工作台态（默认 home 会渲染项目首页）
  location.hash = '#/p/演示项目' // 配套工作台 hash：App onMounted 的 syncFromHash 需一致才不被拉回 home
  vi.mocked(getEvidence).mockResolvedValue([])
  vi.mocked(getClarifications).mockResolvedValue([])
  vi.mocked(listBaselines).mockResolvedValue([])
  // listJobs 不设默认：resumeJobs 拿到 undefined 抛错被吞，不清 aiBusy（进度条用例依赖预设值）
  vi.mocked(wbSummary).mockResolvedValue({ tree: [], root: null }) // 空树 → Landing 导入态
})

describe('全局 AI 进度条（aiBusy 挂 App 级）', () => {
  it('aiBusy 非空时 App 渲染进度条，含 x/y 真实进度', async () => {
    aiBusy.value = { label: 'AI 生成画像 · 支付/放款重试', cur: 2, total: 5 }
    const App = (await import('./App.vue')).default
    const w = mount(App)
    await flushPromises()
    expect(w.find('.global-ai').exists()).toBe(true)
    expect(w.find('.global-ai').text()).toContain('AI 生成画像 · 支付/放款重试')
    expect(w.find('.global-ai').text()).toContain('（2/5）')
    expect((w.find('.global-ai .bar i').element as HTMLElement).style.width).toBe('40%')
    expect(w.find('.global-ai .cancel-btn').exists()).toBe(true) // B3：进度条自带取消入口
    w.unmount()
  })

  it('aiBusy 为 null 时进度条不渲染', async () => {
    const App = (await import('./App.vue')).default
    const w = mount(App)
    await flushPromises()
    expect(w.find('.global-ai').exists()).toBe(false)
    w.unmount()
  })
})
