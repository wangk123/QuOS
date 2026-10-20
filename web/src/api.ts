// 后端 API 封装:统一错误抛出(HTTP 语义 404/409/422)
const BASE = '/api/v1'

export class ApiError extends Error {
  status: number
  detail: any
  constructor(status: number, detail: any) {
    super(`API ${status}`)
    this.status = status
    this.detail = detail
  }
}

async function request(method: string, path: string, body?: any, isForm = false): Promise<any> {
  const opts: RequestInit = { method, headers: {}, cache: 'no-store' } // 列表数据随写操作变化,禁浏览器启发式缓存
  if (body !== undefined) {
    if (isForm) opts.body = body // FormData:multipart 上传
    else {
      opts.headers = { 'Content-Type': 'application/json' }
      opts.body = JSON.stringify(body)
    }
  }
  const res = await fetch(BASE + path, opts)
  if (res.status === 204) return null
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data)
  return data
}

export const api = {
  get: (p: string) => request('GET', p),
  post: (p: string, b?: any) => request('POST', p, b),
  patch: (p: string, b?: any) => request('PATCH', p, b),
  del: (p: string) => request('DELETE', p),
  upload: (p: string, f: File) => {
    const fd = new FormData()
    fd.append('file', f)
    return request('POST', p, fd, true)
  },
}

// ── 项目 ──
export interface ProjStats { materials: number; pending_annos: number; version: string | null; draft_status: string | null }
export interface Project { id: number; name: string; description: string; created_at: string; stats: ProjStats }
export const listProjects = () => api.get('/projects') as Promise<Project[]>
export const getProject = (pid: number) => api.get(`/projects/${pid}`) as Promise<Project>
export const createProject = (name: string, description: string) => api.post('/projects', { name, description })
export const patchProject = (pid: number, b: { name?: string; description?: string }) => api.patch(`/projects/${pid}`, b)
export const deleteProject = (pid: number) => api.del(`/projects/${pid}`) as Promise<{ ok: boolean }>

// ── 材料 ──
export interface Material { id: number; filename: string; type: string; sha256: string; size: number; parsed_text: string; created_at: string }
export const listMaterials = (pid: number) => api.get(`/projects/${pid}/materials`) as Promise<Material[]>
export const uploadMaterial = (pid: number, file: File) => api.upload(`/projects/${pid}/materials`, file)
export const deleteMaterial = (pid: number, mid: number) => api.del(`/projects/${pid}/materials/${mid}`)

// ── 文档 ──
export interface RuleP { no: string; text: string; violation: string; quote: string; material_id: number | null; status: string; replaced_by: string | null }
export interface BlockP {
  type: 'para' | 'states' | 'table' | 'figure' | 'exceptions' | 'diagram' | 'diagram'
  text?: string
  title?: string
  columns?: string[]
  rows?: string[][]
  flows?: string[]
  items?: string[]
}
export interface ChapterP { id: string; title: string; pri: string; parent: string | null; background: string; blocks: BlockP[]; rule_nos: string[] }
export interface DocPayload { meta: any; overview: any; glossary: any[]; new_terms: any[]; chapters: ChapterP[]; rules: Record<string, RuleP> }
export const getBaseline = (pid: number) => api.get(`/projects/${pid}/doc/baseline`)
export const getDraft = (pid: number) => api.get(`/projects/${pid}/doc/draft`)
export const getVersions = (pid: number) => api.get(`/projects/${pid}/doc/versions`)
export const getChanges = (pid: number, version: string) => api.get(`/projects/${pid}/doc/changes?version=${encodeURIComponent(version)}`)
export const finalizeDoc = (pid: number, draft_id: number, version: string, note: string) =>
  api.post(`/projects/${pid}/doc/finalize`, { draft_id, version, note })
export const revertDoc = (pid: number, version: string) => api.post(`/projects/${pid}/doc/revert`, { version })

// ── 批注 ──
export interface Question { id: number; batch_id: string; kind: string; payload: any; anchor: any; status: string; answer: any; answered_at: string | null; source: string; draft_id: number | null; created_at: string }
export const listQuestions = (pid: number, status?: string) =>
  api.get(`/projects/${pid}/questions${status ? `?status=${status}` : ''}`) as Promise<Question[]>
export const submitQuestions = (pid: number, items: any[]) => api.post(`/projects/${pid}/questions`, items)
export const answerQuestion = (qid: number, answer: any) => api.post(`/questions/${qid}/answer`, { answer })
