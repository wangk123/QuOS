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

describe('澄清池材料级回答', () => {
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

  it('reviewClars POST /clarifications/review 传 ev_ids', async () => {
    const { setProject, reviewClars } = await import('./api')
    setProject('p1')
    await reviewClars(['E1', 'E2'])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/clarifications\/review$/)
    expect((init as RequestInit).method).toBe('POST')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ ev_ids: ['E1', 'E2'] })
  })

  it('adoptClar/ignoreClar 分别 POST adopt/ignore', async () => {
    const { adoptClar, ignoreClar } = await import('./api')
    await adoptClar(3)
    await ignoreClar(5)
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
      no: 3,
      action: 'adopt',
    })
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual({
      no: 5,
      action: 'ignore',
    })
  })

  it('answerClarOpen POST answer 且关联材料 id', async () => {
    const { answerClarOpen } = await import('./api')
    await answerClarOpen(2, '看图作答', ['E9'])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/clarifications$/)
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      no: 2,
      action: 'answer',
      text: '看图作答',
      ev_ids: ['E9'],
    })
  })

  it('answerClarOpen 缺省 ev_ids 为空数组', async () => {
    const { answerClarOpen } = await import('./api')
    await answerClarOpen(2, '纯文本作答')
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
      no: 2,
      action: 'answer',
      text: '纯文本作答',
      ev_ids: [],
    })
  })

  it('addEvidenceFile 带 source 时 URL 追加 query', async () => {
    const { addEvidenceFile } = await import('./api')
    await addEvidenceFile(new File(['x'], 'a.png'), 'clar')
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/evidence\?source=clar$/)
  })

  it('addEvidenceFile 无 source 时 URL 不带 query（旧调用不变）', async () => {
    const { addEvidenceFile } = await import('./api')
    await addEvidenceFile(new File(['x'], 'a.png'))
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/evidence$/)
  })

  it('addEvidence 文本入池同样透传 source', async () => {
    const { addEvidence } = await import('./api')
    await addEvidence('补充材料', 'clar')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/evidence\?source=clar$/)
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ raw: '补充材料' })
  })
})
