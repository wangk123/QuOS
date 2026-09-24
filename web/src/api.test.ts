// api 基础层单测：项目上下文切换后请求打到新 BASE
import { describe, expect, it, vi, beforeEach } from 'vitest'

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

describe('项目上下文', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({}),
      text: async () => '',
    })
  })

  it('未进项目时项目级请求 URL 含空 slug 占位', async () => {
    const { getTree } = await import('./api')
    await getTree()
    expect(fetchMock.mock.calls[0][0]).toContain('/api/projects/')
  })

  it('setProject 后中文 slug 走 URL encode', async () => {
    const { setProject, getTree } = await import('./api')
    setProject('风控云')
    await getTree()
    expect(decodeURIComponent(fetchMock.mock.calls[0][0])).toContain('/api/projects/风控云/tree')
  })

  it('项目 API 打到无 proj 前缀的 /api/projects', async () => {
    const { createProject } = await import('./api')
    await createProject('新项目', '描述')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/projects')
    expect((init as RequestInit).method).toBe('POST')
  })

  it('204 空 body 端点（archive 等）不因解析响应体抛错', async () => {
    const { archiveProject } = await import('./api')
    fetchMock.mockResolvedValue({ ok: true, status: 204, headers: new Headers(), json: async () => ({}) })
    await expect(archiveProject('风控云')).resolves.toBeUndefined()
  })
})
