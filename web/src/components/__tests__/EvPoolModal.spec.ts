// Task 12：证据池弹窗——渲染列表 / 删除联动 / 重新生成入口 / 追加材料（api 全 mock）
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { addEvidenceFile, deleteEvidence, type EvidenceItem } from '../../api'

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
    addEvidenceFile: vi.fn(),
    deleteEvidence: vi.fn(),
  }
})

const EVS: EvidenceItem[] = [
  { id: 'E1', name: '工商信息查询制度.docx', ext: 'docx', type: '文档', stars: 3, reg: '2026-09-28',
    state: 'extracted', count: 39, path: '', missing: false },
  { id: 'E2', name: '客户沟通记录.png', ext: 'png', type: '截图', stars: 2, reg: '2026-09-29',
    state: 'ready', count: 0, path: '', missing: false },
  { id: 'E3', name: '澄清补料-阈值说明.txt', ext: 'txt', type: '文本', stars: 1, reg: '2026-09-30',
    state: 'ready', count: 0, path: '', missing: false, source: 'clar' },
]

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(addEvidenceFile).mockImplementation(async (_f: File) => ({ ...EVS[0], id: 'E9', name: 'new.pdf' }))
  vi.mocked(deleteEvidence).mockResolvedValue(undefined)
})

let lastW: VueWrapper<any> | null = null
async function mountModal(props: Partial<{ open: boolean; evidence: EvidenceItem[] }> = {}, attachTo?: HTMLElement) {
  const EvPoolModal = (await import('../EvPoolModal.vue')).default
  lastW?.unmount() // window paste 监听随实例卸载清理，防跨用例串扰
  lastW = mount(EvPoolModal, {
    props: { open: true, evidence: EVS, ...props },
    ...(attachTo ? { attachTo } : {}),
  })
  await flushPromises()
  return lastW
}

describe('EvPoolModal（证据池弹窗）', () => {
  it('弹窗打开渲染材料行：名称/类型徽章/星级/并入态/澄清补料徽章', async () => {
    const w = await mountModal()
    expect(w.find('.mask.open').exists()).toBe(true)
    expect(w.findAll('.evrow').length).toBeGreaterThanOrEqual(3)
    expect(w.text()).toContain('工商信息查询制度.docx')
    const badges = w.findAll('.badge').map(b => b.text())
    expect(badges).toContain('已并入需求') // state=extracted
    expect(badges).toContain('未生成')
    expect(badges).toContain('澄清补料') // source=clar
    expect(w.text()).toContain('★★★')
  })

  it('✕ 删除：confirm 通过调 deleteEvidence 并 emit changed', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const w = await mountModal()
    await w.findAll('.evrow .x')[0].trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalled()
    expect(deleteEvidence).toHaveBeenCalledWith('E1')
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('confirm 取消不删除', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const w = await mountModal()
    await w.findAll('.evrow .x')[0].trigger('click')
    await flushPromises()
    expect(deleteEvidence).not.toHaveBeenCalled()
    expect(w.emitted('changed')).toBeFalsy()
  })

  it('「↻ 重新生成」emit impact（无载荷，ImpactModal T17 接）', async () => {
    const w = await mountModal()
    await w.findAll('button').find(b => b.text().includes('重新生成'))!.trigger('click')
    expect(w.emitted('impact')).toBeTruthy()
    expect(w.emitted('impact')!.length).toBe(1)
  })

  it('点击上传：隐藏 file input 逐份 addEvidenceFile（池直入无 source）并 emit changed', async () => {
    const w = await mountModal()
    const input = w.find('input[type="file"]')
    const f = new File(['补充材料'], '补充说明.pdf', { type: 'application/pdf' })
    Object.defineProperty(input.element, 'files', { value: [f], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(addEvidenceFile).toHaveBeenCalledWith(f)
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('⌘V 粘贴文件同流入池；弹窗关闭后粘贴不再入池', async () => {
    const w = await mountModal(undefined, document.body)
    const f = new File(['截图'], '新截图.png', { type: 'image/png' })
    const ev = new Event('paste', { bubbles: true })
    Object.defineProperty(ev, 'clipboardData', { value: { files: [f] }, configurable: true })
    window.dispatchEvent(ev)
    await flushPromises()
    expect(addEvidenceFile).toHaveBeenCalledWith(f)
    // 关闭弹窗：window paste 监听移除，再粘贴不投递
    vi.mocked(addEvidenceFile).mockClear()
    await w.setProps({ open: false })
    window.dispatchEvent(ev)
    await flushPromises()
    expect(addEvidenceFile).not.toHaveBeenCalled()
  })

  it('池空时展示空态行', async () => {
    const w = await mountModal({ evidence: [] })
    expect(w.text()).toContain('池是空的')
  })
})
