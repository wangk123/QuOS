// 项目首页三态渲染与交互（api 全 mock，同 views.spec.ts 惯例）
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Home from '../Home.vue'

vi.mock('../../api', () => ({
  ApiError: class ApiError extends Error {
    status = 0
  },
  getProjects: vi.fn(),
  getArchivedProjects: vi.fn(),
  createProject: vi.fn(),
  openProject: vi.fn(),
  patchProject: vi.fn(),
  archiveProject: vi.fn(),
  restoreProject: vi.fn(),
  purgeProject: vi.fn(),
  setProject: vi.fn(),
}))
import {
  archiveProject,
  createProject,
  getArchivedProjects,
  getProjects,
  openProject,
  patchProject,
  purgeProject,
} from '../../api'
import { top } from '../../router'

const findBtn = (w: ReturnType<typeof mount>, text: string) =>
  w.findAll('button').find((b) => b.text() === text)!

describe('Home 项目首页', () => {
  beforeEach(() => {
    vi.mocked(getProjects).mockReset().mockResolvedValue([
      { slug: '风控云', name: '风控云', description: '核心账务', created_at: '2026-09-23T10:00:00', last_opened_at: null },
    ])
    vi.mocked(getArchivedProjects).mockReset().mockResolvedValue([])
    vi.mocked(createProject).mockReset().mockResolvedValue({} as never)
    vi.mocked(openProject).mockReset().mockResolvedValue(undefined as never)
    vi.mocked(archiveProject).mockReset().mockResolvedValue(undefined as never)
    vi.mocked(patchProject).mockReset().mockResolvedValue({} as never)
    vi.mocked(purgeProject).mockReset().mockResolvedValue(undefined as never)
    location.hash = ''
    top.value = 'home'
  })

  it('渲染项目用户画像与新建入口', async () => {
    const w = mount(Home)
    await flushPromises()
    expect(w.text()).toContain('风控云')
    expect(w.text()).toContain('核心账务')
    expect(w.text()).toContain('新建项目')
  })

  it('空列表渲染引导态', async () => {
    vi.mocked(getProjects).mockResolvedValue([])
    const w = mount(Home)
    await flushPromises()
    expect(w.text()).toContain('还没有项目')
  })

  it('新建提交调 createProject 并刷新', async () => {
    const w = mount(Home)
    await flushPromises()
    await w.find('input[data-test="new-name"]').setValue('新项目')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(createProject).toHaveBeenCalledWith('新项目', '')
    expect(getProjects).toHaveBeenCalledTimes(2)
  })

  it('点击用户画像进入项目', async () => {
    const w = mount(Home)
    await flushPromises()
    await w.find('[data-test="proj-card"]').trigger('click')
    await flushPromises()
    expect(openProject).toHaveBeenCalledWith('风控云')
    expect(location.hash).toBe('#/p/%E9%A3%8E%E6%8E%A7%E4%BA%91')
    expect(top.value).toBe('proj')
  })

  it('归档项目后刷新列表', async () => {
    vi.stubGlobal('confirm', () => true)
    const w = mount(Home)
    await flushPromises()
    await findBtn(w, '归档').trigger('click')
    await flushPromises()
    expect(archiveProject).toHaveBeenCalledWith('风控云')
    expect(getProjects).toHaveBeenCalledTimes(2)
    vi.unstubAllGlobals()
  })

  it('编辑保存调 patchProject 改名改描述并刷新', async () => {
    const w = mount(Home)
    await flushPromises()
    await findBtn(w, '编辑').trigger('click')
    await w.find('input[data-test="edit-name"]').setValue('风控云 Pro')
    await w.find('input[data-test="edit-desc"]').setValue('账务中台')
    await w.find('[data-test="edit-form"]').trigger('submit')
    await flushPromises()
    expect(patchProject).toHaveBeenCalledWith('风控云', { name: '风控云 Pro', description: '账务中台' })
    expect(getProjects).toHaveBeenCalledTimes(2)
  })

  it('编辑取消不调 patchProject', async () => {
    const w = mount(Home)
    await flushPromises()
    await findBtn(w, '编辑').trigger('click')
    await findBtn(w, '取消').trigger('click')
    expect(w.find('[data-test="edit-form"]').exists()).toBe(false)
    expect(patchProject).not.toHaveBeenCalled()
  })

  it('删除需输名确认后归档+彻底删除', async () => {
    vi.stubGlobal('prompt', () => '风控云')
    const w = mount(Home)
    await flushPromises()
    await findBtn(w, '删除').trigger('click')
    await flushPromises()
    expect(archiveProject).toHaveBeenCalledWith('风控云')
    expect(purgeProject).toHaveBeenCalledWith('风控云')
    vi.unstubAllGlobals()
  })

  it('删除输名不一致则取消', async () => {
    vi.stubGlobal('prompt', () => '别的名字')
    const w = mount(Home)
    await flushPromises()
    await findBtn(w, '删除').trigger('click')
    await flushPromises()
    expect(archiveProject).not.toHaveBeenCalled()
    expect(purgeProject).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('加载失败渲染错误条', async () => {
    vi.mocked(getProjects).mockRejectedValue(new Error('network'))
    const w = mount(Home)
    await flushPromises()
    expect(w.text()).toContain('无法连接后端')
  })

  it('加载失败置 err 后再次 load 成功清除', async () => {
    vi.mocked(getProjects).mockRejectedValueOnce(new Error('network'))
    const w = mount(Home)
    await flushPromises()
    expect(w.text()).toContain('无法连接后端')
    vi.mocked(getProjects).mockResolvedValue([])
    vi.mocked(getArchivedProjects).mockResolvedValue([])
    await w.find('input[data-test="new-name"]').setValue('恢复项目')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.text()).not.toContain('无法连接后端')
    expect(w.text()).toContain('还没有项目')
  })
})
