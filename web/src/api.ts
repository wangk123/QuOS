// QuOS reqspec API 封装：路由与 server/app/api/router.py 一一对应。
// 项目上下文动态化：curSlug 由首页进入工作台时设置（见 router.ts enterProject）。
import { ref } from 'vue'

export const curSlug = ref('')
export function setProject(slug: string) {
  curSlug.value = slug
}
const base = () => `/api/projects/${encodeURIComponent(curSlug.value)}`

// ---------- 类型（对应 server/app/core/models.py、cards.py） ----------

export interface TreeNode {
  name: string
  children: TreeNode[]
  open: boolean
  /** M1 后端无徽章聚合端点，stats 仅预留 T12 使用 */
  stats?: { asrt?: number; warn?: number; ok?: boolean }
}

export interface EvidenceItem {
  id: string
  name: string
  ext: string
  type: string
  stars: number
  reg: string
  state: string
  count: number
  path: string
  missing: boolean
}

export type AssertConf = '实证' | '文档' | '推测' | '待实证' | '旧文档'

export interface Assertion {
  id: string
  text: string
  src: string
  conf: AssertConf
  st: string
  verified: boolean
  suspect: boolean
}

export interface Conflict {
  id: string
  a: string
  b: string
  q: string
  st: string
  resolution: string | null
}

export interface Gap {
  id: string
  dim: string
  text: string
  st: string
}

export interface Clarification {
  no: number
  q: string
  opts: string[]
  st: string
  answer: string | null
  ref: string | null
}

export interface CardRule {
  id: string
  text: string
  src: string
  conf: string
}

export interface Card {
  node: string
  goal: string
  entry: string
  flow: string
  rules: CardRule[]
  states: string
  boundaries: string
  note: string
  deps: string
  unconfirmed: string[]
}

/** GET /baseline 仅含 tag/commit；v 仅 POST /baseline 创建时返回 */
export interface Baseline {
  commit: string
  tag: string
  v?: number
}

export type TreeOpName = 'add' | 'rename' | 'del'

// ---------- 错误：FastAPI 错误体统一包在 detail 里 ----------

export class ApiError extends Error {
  status: number
  detail: unknown
  /** POST /cards/assemble 409：{detail:{unqualified:[断言id]}} */
  unqualified: string[] | null

  constructor(status: number, detail: unknown) {
    const d = detail instanceof Object && 'detail' in detail ? (detail as any).detail : detail
    super(typeof d === 'string' ? d : `HTTP ${status}`)
    this.status = status
    this.detail = d
    this.unqualified =
      d && typeof d === 'object' && Array.isArray((d as any).unqualified) ? (d as any).unqualified : null
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(base() + path, init)
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null))
  const ct = res.headers.get('content-type') ?? ''
  return (ct.includes('json') ? res.json() : res.text()) as Promise<T>
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

// ---------- 证据 ----------

export const getEvidence = () => req<EvidenceItem[]>('/evidence')

/** 文本入池 */
export const addEvidence = (raw: string) => req<EvidenceItem>('/evidence', json('POST', { raw }))

/** 文件入池：后端无 python-multipart，用原始 body + X-Filename 头传文件名 */
export const addEvidenceFile = (file: File) =>
  req<EvidenceItem>('/evidence', {
    method: 'POST',
    headers: { 'X-Filename': encodeURIComponent(file.name), 'Content-Type': 'application/octet-stream' },
    body: file,
  })

export const extractEvidence = (id: string) =>
  req<{ added: number; assertions: Assertion[] }>(`/evidence/${encodeURIComponent(id)}/extract`, {
    method: 'POST',
  })

// ---------- 断言 ----------

export const getAssertions = () => req<Assertion[]>('/assertions')

export const verifyAll = () =>
  req<{ applied: string[]; results: unknown[] }>('/assertions/verify', json('POST', {}))

export const verifyOne = (id: string) =>
  req<{ applied: string[]; results: unknown[] }>('/assertions/verify', json('POST', { assert_id: id }))

// ---------- 矛盾 ----------

export const getConflicts = () => req<Conflict[]>('/conflicts')

export const rescanConflicts = () => req<Conflict[]>('/conflicts/rescan', { method: 'POST' })

export const resolveConflict = (id: string, action: 'code' | 'clar', side?: 'a' | 'b') =>
  req<Conflict>('/conflicts', json('POST', { id, action, side }))

// ---------- 空白 ----------

export const getGaps = () => req<Gap[]>('/gaps')

export const rescanGaps = () => req<Gap[]>('/gaps/rescan', { method: 'POST' })

export const disposeGap = (id: string, action: 'clar' | 'ok') => req<Gap>('/gaps', json('POST', { id, action }))

// ---------- 维度 ----------

export const getDims = () => req<string[]>('/dims')

export const setDims = (dims: string[]) => req<string[]>('/dims', json('PUT', { dims }))

// ---------- 功能树 ----------

export const getTree = () => req<TreeNode[]>('/tree')

/** op: add/rename/del；path 为空字符串表示根层级（add） */
export const treeOp = (op: TreeOpName, path?: string, name?: string) =>
  req<TreeNode[]>('/tree', json('POST', { op, path: path || undefined, name }))

// ---------- 卡片 ----------

/** 409 时抛 ApiError（unqualified 为未实证断言 id 列表） */
export const assemble = (nodePath: string, note = '') =>
  req<{ card: Card; file: string }>('/cards/assemble', json('POST', { node_path: nodePath, note }))

export const getCard = (nodePath: string) => req<Card>(`/cards/${encodeURIComponent(nodePath)}`)

export const getDoc = () => req<string>('/doc')

// ---------- 问人 ----------

export const getClarifications = () => req<Clarification[]>('/clarifications')

export const answerClar = (no: number, idx: number) =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'answer', idx }))

export const verifyClar = (no: number) =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'verify' }))

// ---------- 基线 ----------

export const createBaseline = (note = '基线存档') =>
  req<Baseline>('/baseline', json('POST', { note }))

export const listBaselines = () => req<Baseline[]>('/baseline')

// ---------- 项目管理（无 proj 前缀，对应 server/app/api/projects.py） ----------

export interface ProjectInfo {
  slug: string
  name: string
  description: string
  created_at: string
  last_opened_at: string | null
}

/** /api/projects 不含 proj 段，独立于 req 的项目级 BASE */
async function reqRoot<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/projects${path}`, init)
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null))
  // 204 无响应体（archive/restore/purge），跳过解析
  if (res.status === 204) return undefined as T
  return (await res.json()) as Promise<T>
}

export const getProjects = () => reqRoot<ProjectInfo[]>('')
export const getArchivedProjects = () => reqRoot<ProjectInfo[]>('/archived')
export const createProject = (name: string, description = '') =>
  reqRoot<ProjectInfo>('', json('POST', { name, description }))
export const openProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}/open`, { method: 'POST' })
export const patchProject = (slug: string, description: string) =>
  reqRoot<{ slug: string }>(`/${encodeURIComponent(slug)}`, json('PATCH', { description }))
export const archiveProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}/archive`, { method: 'POST' })
export const restoreProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}/restore`, { method: 'POST' })
export const purgeProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}`, { method: 'DELETE' })
