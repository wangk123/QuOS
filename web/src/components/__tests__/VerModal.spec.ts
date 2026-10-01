// Task 14：版本弹窗——时间线 / 存为版本 / 导出预览（api 全 mock）
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createBaseline, getDoc, listBaselines } from '../../api'

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
    getDoc: vi.fn(),
  }
})

const DOC = '# 需求文档 · AI 访前调查\n\n## 需求总览\n  这是什么 · 给谁 · 端到端主线'

let baselines: { tag: string; commit: string; time?: string; note?: string }[] = []

beforeEach(() => {
  vi.clearAllMocks()
  baselines = []
  vi.mocked(listBaselines).mockImplementation(async () => baselines.map(b => ({ ...b })))
  vi.mocked(createBaseline).mockImplementation(async (note?: string) => {
    const v = baselines.length + 1
    const r = { commit: `cccc${v}222deadbeef`, tag: `v${v}`, v }
    baselines.push({ tag: r.tag, commit: r.commit, note: note })
    return r
  })
  vi.mocked(getDoc).mockResolvedValue(DOC)
  vi.spyOn(window, 'prompt').mockReturnValue('')
})

let lastW: VueWrapper<any> | null = null
async function mountModal(provide?: Record<string, unknown>) {
  const VerModal = (await import('../VerModal.vue')).default
  lastW?.unmount()
  lastW = mount(VerModal, {
    props: { open: true },
    ...(provide ? { global: { provide } } : {}),
  })
  await flushPromises()
  return lastW
}

describe('VerModal（版本弹窗）', () => {
  it('无版本时展示空态文案', async () => {
    const w = await mountModal()
    expect(w.find('.mask.open').exists()).toBe(true)
    expect(w.text()).toContain('还没有版本——需要留底时点存为版本')
  })

  it('时间线渲染各版 tag/说明/commit 短 hash，末项标当前绿点', async () => {
    vi.mocked(listBaselines).mockResolvedValue([
      { tag: 'v1', commit: 'aaaa1111bbbb2222' },
      { tag: 'v2', commit: 'ffff9999dddd8888', time: '2026-10-01 10:00', note: '外部评审版' },
    ])
    const w = await mountModal()
    const items = w.findAll('.vitem')
    expect(items.length).toBe(2)
    expect(items[0].classes()).not.toContain('cur')
    expect(items[1].classes()).toContain('cur') // 末项=当前
    expect(w.text()).toContain('v2')
    expect(w.text()).toContain('当前')
    expect(w.text()).toContain('外部评审版')
    expect(w.text()).toContain('aaaa111') // commit 短 hash（前 7 位）
  })

  it('存为版本：prompt 填说明调 createBaseline，成功后 emit saved 并重拉列表', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue('评审前留底')
    const w = await mountModal()
    expect(listBaselines).toHaveBeenCalledTimes(1)
    await w.findAll('button').find(b => b.text() === '存为版本')!.trigger('click')
    await flushPromises()
    expect(createBaseline).toHaveBeenCalledWith('评审前留底')
    expect(w.emitted('saved')).toBeTruthy()
    expect(listBaselines).toHaveBeenCalledTimes(2) // 重拉时间线
    expect(w.text()).toContain('v1') // 新版本入列
  })

  it('prompt 说明留空走 createBaseline 默认 note；取消则不存', async () => {
    const w = await mountModal()
    await w.findAll('button').find(b => b.text() === '存为版本')!.trigger('click')
    await flushPromises()
    expect(createBaseline).toHaveBeenCalledWith(undefined) // 空 note → api 默认「基线存档」
    vi.mocked(createBaseline).mockClear()
    vi.spyOn(window, 'prompt').mockReturnValue(null) // 取消
    await w.findAll('button').find(b => b.text() === '存为版本')!.trigger('click')
    await flushPromises()
    expect(createBaseline).not.toHaveBeenCalled()
  })

  it('存版失败 toast warn 且不 emit saved', async () => {
    const toasts: string[] = []
    vi.mocked(createBaseline).mockRejectedValueOnce(new ApiError(500, 'git 不可用'))
    const w = await mountModal({ toast: (msg: string, cls?: string) => toasts.push(`${msg}|${cls ?? ''}`) })
    await w.findAll('button').find(b => b.text() === '存为版本')!.trigger('click')
    await flushPromises()
    expect(toasts.some(t => t.includes('存版失败') && t.includes('warn'))).toBe(true)
    expect(w.emitted('saved')).toBeFalsy()
  })

  it('预览：getDoc 文本进二级弹层 doc-outline，含下载与关闭', async () => {
    const w = await mountModal()
    await w.findAll('button').find(b => b.text().includes('预览 / 导出需求文档'))!.trigger('click')
    await flushPromises()
    expect(getDoc).toHaveBeenCalled()
    const pres = w.findAll('.doc-outline')
    expect(pres.length).toBe(1)
    expect(pres[0].text()).toContain('# 需求文档 · AI 访前调查')
    expect(w.text()).toContain('需求文档 · 导出预览')
    expect(w.findAll('button').some(b => b.text() === '下载 .md')).toBe(true)
    // 关闭二级弹层回到版本弹窗
    await w.findAll('button').find(b => b.text() === '关闭')!.trigger('click')
    expect(w.findAll('.doc-outline').length).toBe(0)
    expect(w.find('.mask.open').exists()).toBe(true) // 主弹窗仍在
  })
})
