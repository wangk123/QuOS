// 版本弹窗：时间线/新增版本表单/回滚废弃确认/预览双模式（api 全 mock）
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createBaseline, deprecateBaseline, getDoc, listBaselines, restoreBaseline } from '../../api'

vi.mock('../../api', () => {
  return {
    ApiError: class ApiError extends Error {
      status: number
      constructor(status: number, detail: unknown) {
        const d = detail instanceof Object && 'detail' in detail ? (detail as any).detail : detail
        super(typeof d === 'string' ? d : `HTTP ${status}`)
        this.status = status
      }
    },
    listBaselines: vi.fn(),
    createBaseline: vi.fn(),
    restoreBaseline: vi.fn(),
    deprecateBaseline: vi.fn(),
    getDoc: vi.fn(),
  }
})

const DOC = '# 需求文档\n\n## 需求总览\n\n| ID | 规则 |\n|---|---|\n| R1 | 目标 |'

let baselines: any[] = []

beforeEach(() => {
  vi.clearAllMocks()
  baselines = []
  vi.mocked(listBaselines).mockImplementation(async () => baselines.map(b => ({ ...b })))
  vi.mocked(createBaseline).mockImplementation(async (version: string, note?: string) => {
    const r = { commit: 'cccc123', tag: `v${version}`, version, cur: true, time: 1760000000, note }
    baselines.push({ ...r, cur: false })
    return r
  })
  vi.mocked(restoreBaseline).mockResolvedValue({ ok: true })
  vi.mocked(deprecateBaseline).mockResolvedValue({ ok: true })
  vi.mocked(getDoc).mockResolvedValue(DOC)
})

let lastW: VueWrapper<any> | null = null
async function mountModal(provide?: Record<string, unknown>) {
  const VerModal = (await import('../VerModal.vue')).default
  lastW?.unmount()
  lastW = mount(VerModal, { props: { open: true }, ...(provide ? { global: { provide } } : {}) })
  await flushPromises()
  return lastW
}

const openForm = async (w: VueWrapper<any>) => {
  // 主弹窗 foot 的「新增版本」开表单；表单内确认按钮用 data-testid 区分（同名不同按钮）
  await w.findAll('button').find(b => b.text() === '新增版本' && !b.attributes('data-testid'))!.trigger('click')
}
const submitForm = async (w: VueWrapper<any>) => {
  await w.find('[data-testid="commit-ver"]').trigger('click')
}

describe('VerModal（版本弹窗）', () => {
  it('无版本时展示空态文案', async () => {
    const w = await mountModal()
    expect(w.find('.mask.open').exists()).toBe(true)
    expect(w.text()).toContain('还没有版本——需要留底时点新增版本')
  })

  it('时间线渲染版本号/时间/说明；cur 字段标当前（非末位）', async () => {
    vi.mocked(listBaselines).mockResolvedValue([
      { tag: 'v1.0.0', commit: 'aaaa1111bbbb2222', version: '1.0.0', time: 1760000000, note: '初版' },
      { tag: 'v1.1.0', commit: 'ffff9999dddd8888', version: '1.1.0', time: 1760000600, note: '评审版', cur: true },
    ])
    const w = await mountModal()
    const items = w.findAll('.vitem')
    expect(items.length).toBe(2)
    expect(items[0].classes()).not.toContain('cur')
    expect(items[1].classes()).toContain('cur')
    expect(w.text()).toContain('1.1.0')
    expect(w.text()).toContain('当前')
    expect(w.text()).toContain('评审版')
    expect(w.text()).toContain('aaaa111')  // commit 短 hash
    expect(w.text()).toMatch(/2025-10-0[89] \d{2}:\d{2}/)  // 1760000000 → 本地 YYYY-MM-DD HH:mm（UTC+8 为 10-09）
  })

  it('新增版本：表单填版本号+说明，提交调 createBaseline 并重拉', async () => {
    const w = await mountModal()
    await openForm(w)
    await w.find('input[type="text"]').setValue('1.0.1')
    await w.find('textarea').setValue('评审前留底')
    await submitForm(w)
    await flushPromises()
    expect(createBaseline).toHaveBeenCalledWith('1.0.1', '评审前留底')
    expect(w.emitted('saved')).toBeTruthy()
    expect(listBaselines).toHaveBeenCalledTimes(2)
    expect(w.text()).toContain('1.0.1')  // 时间线显示裸版本号（v 前缀剥掉，同原型）
  })

  it('版本号格式错：红字提示且不提交', async () => {
    const w = await mountModal()
    await openForm(w)
    await w.find('input[type="text"]').setValue('1.2')
    await submitForm(w)
    await flushPromises()
    expect(w.text()).toContain('格式须为 x.y.z')
    expect(createBaseline).not.toHaveBeenCalled()
  })

  it('回滚：确认弹层文案含丢弃警示，确认调 restoreBaseline 并 emit restored', async () => {
    vi.mocked(listBaselines).mockResolvedValue([
      { tag: 'v1.0.0', commit: 'aaaa1111bbbb2222', version: '1.0.0', time: 1760000000 },
      { tag: 'v1.1.0', commit: 'ffff9999dddd8888', version: '1.1.0', time: 1760000600, cur: true },
    ])
    const w = await mountModal()
    await w.findAll('.vact').find(b => b.text().includes('回滚'))!.trigger('click')
    expect(w.text()).toContain('回滚到 1.0.0')
    expect(w.text()).toContain('不可恢复')
    await w.findAll('button').find(b => b.text() === '确认回滚')!.trigger('click')
    await flushPromises()
    expect(restoreBaseline).toHaveBeenCalledWith('v1.0.0')
    expect(w.emitted('restored')).toBeTruthy()
    expect(listBaselines).toHaveBeenCalledTimes(2)
  })

  it('废弃：确认后调 deprecateBaseline 并重拉', async () => {
    vi.mocked(listBaselines).mockResolvedValue([
      { tag: 'v1.0.0', commit: 'aaaa1111bbbb2222', version: '1.0.0', time: 1760000000 },
      { tag: 'v1.1.0', commit: 'ffff9999dddd8888', version: '1.1.0', time: 1760000600, cur: true },
    ])
    const w = await mountModal()
    await w.findAll('.vact').find(b => b.text().includes('废弃'))!.trigger('click')
    expect(w.text()).toContain('废弃版本 1.0.0')
    await w.findAll('button').find(b => b.text() === '确认废弃')!.trigger('click')
    await flushPromises()
    expect(deprecateBaseline).toHaveBeenCalledWith('v1.0.0')
    expect(listBaselines).toHaveBeenCalledTimes(2)
  })

  it('预览双模式：默认渲染 markdown（表格/标题成 HTML），可切源码 pre', async () => {
    const w = await mountModal()
    await w.findAll('button').find(b => b.text().includes('预览 / 导出需求文档'))!.trigger('click')
    await flushPromises()
    expect(getDoc).toHaveBeenCalled()
    const view = w.find('.md-view')
    expect(view.exists()).toBe(true)
    expect(view.find('table').exists()).toBe(true)
    expect(view.find('h1').text()).toContain('需求文档')
    await w.findAll('button').find(b => b.text() === '源码')!.trigger('click')
    expect(w.find('.doc-outline').exists()).toBe(true)
    expect(w.findAll('button').some(b => b.text() === '下载 .md')).toBe(true)
  })

  it('预览章节导航：h2/h4 入导航（h1 不入），点击按偏移手动滚动，源码模式隐藏', async () => {
    const scrollTo = vi.fn()
    Element.prototype.scrollTo = scrollTo
    const w = await mountModal()
    await w.findAll('button').find(b => b.text().includes('预览 / 导出需求文档'))!.trigger('click')
    await flushPromises()
    const nav = w.find('.doc-nav')
    expect(nav.exists()).toBe(true)
    const items = w.findAll('.doc-nav .nav-item')
    expect(items.some(i => i.text() === '需求总览')).toBe(true)   // h2 入导航
    expect(items.some(i => i.text() === '需求文档')).toBe(false)  // h1（文档唯一标题）不入导航
    // 目标标题在滚动容器下方 420px → 手动滚动到该偏移（scrollIntoView 在嵌套滚动容器不可靠）
    const heads = (w.element as HTMLElement).querySelectorAll('.md-view h2')
    ;(heads[0] as HTMLElement).getBoundingClientRect = () => ({ top: 420 } as DOMRect)
    const idx = items.findIndex(i => i.text() === '需求总览')
    await items[idx].trigger('click')
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 412 }))  // 420 - 8 顶部留白
    // 源码模式无标题结构，导航隐藏
    await w.findAll('button').find(b => b.text() === '源码')!.trigger('click')
    expect(w.find('.doc-nav').exists()).toBe(false)
  })

  it('章节导航可折叠：收起出浮动目录钮，点钮恢复', async () => {
    const w = await mountModal()
    await w.findAll('button').find(b => b.text().includes('预览 / 导出需求文档'))!.trigger('click')
    await flushPromises()
    expect(w.find('.doc-nav').exists()).toBe(true)
    await w.find('.nav-fold').trigger('click')
    expect(w.find('.doc-nav').exists()).toBe(false)
    const fab = w.find('.nav-fab')
    expect(fab.exists()).toBe(true)
    await fab.trigger('click')
    expect(w.find('.doc-nav').exists()).toBe(true)
  })

  it('同 commit 多 tag（无变更连续存版）：仅一行标当前，各行仍有废弃入口', async () => {
    vi.mocked(listBaselines).mockResolvedValue([
      { tag: 'v1.0.0', commit: 'aaaa1111bbbb2222', version: '1.0.0', time: 1760000000, note: '一', cur: false },
      { tag: 'v1.0.1', commit: 'aaaa1111bbbb2222', version: '1.0.1', time: 1760000600, note: '无变更再存', cur: true },
      { tag: 'v1.0.2', commit: 'aaaa1111bbbb2222', version: '1.0.2', time: 1760001200, note: '又无变更', cur: true },
    ])
    const w = await mountModal()
    const badges = w.findAll('.badge.b-green')
    expect(badges.length).toBe(1)  // 「当前」徽章只标最后一个 cur 行
    expect(badges[0].text()).toBe('当前')
    // 每行（含当前行）都有废弃入口；回滚入口仅非当前行——同 commit 行互滚无意义
    const rows = w.findAll('.vitem')
    expect(rows[2].findAll('.vact').some(b => b.text().includes('废弃'))).toBe(true)
    expect(rows[2].findAll('.vact').some(b => b.text().includes('回滚'))).toBe(false)
  })

  it('新增版本失败 toast warn', async () => {
    const toasts: string[] = []
    vi.mocked(createBaseline).mockRejectedValueOnce(new ApiError(422, '版本号已存在: 1.0.0'))
    const w = await mountModal({ toast: (msg: string, cls?: string) => toasts.push(`${msg}|${cls ?? ''}`) })
    await openForm(w)
    await w.find('input[type="text"]').setValue('1.0.0')
    await submitForm(w)
    await flushPromises()
    expect(toasts.some(t => t.includes('新增失败') && t.includes('warn'))).toBe(true)
  })
})
