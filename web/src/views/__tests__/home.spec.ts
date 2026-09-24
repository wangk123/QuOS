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
  archiveProject: vi.fn(),
  restoreProject: vi.fn(),
  purgeProject: vi.fn(),
  setProject: vi.fn(),
}))
import { archiveProject, createProject, getArchivedProjects, getProjects, openProject } from '../../api'
import { top } from '../../router'

describe('Home 项目首页', () => {
  beforeEach(() => {
    vi.mocked(getProjects).mockReset().mockResolvedValue([
      { slug: '风控云', name: '风控云', description: '核心账务', created_at: '2026-09-23T10:00:00', last_opened_at: null },
    ])
    vi.mocked(getArchivedProjects).mockReset().mockResolvedValue([])
    vi.mocked(createProject).mockReset().mockResolvedValue({} as never)
    vi.mocked(openProject).mockReset().mockResolvedValue(undefined as never)
    vi.mocked(archiveProject).mockReset().mockResolvedValue(undefined as never)
    location.hash = ''
    top.value = 'home'
  })

  it('渲染项目卡片与新建入口', async () => {
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

  it('点击卡片进入项目', async () => {
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
    await w.find('[data-test="proj-card"] .ghost').trigger('click')
    await flushPromises()
    expect(archiveProject).toHaveBeenCalledWith('风控云')
    expect(getProjects).toHaveBeenCalledTimes(2)
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
