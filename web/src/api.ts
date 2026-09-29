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
  /** 节点重要度：'' | 'P0' | 'P1' | 'P2'（Task 7 树标记） */
  priority?: string
  /** M1 后端无徽章聚合端点，stats 仅预留 T12 使用 */
  stats?: { rule?: number; warn?: number; ok?: boolean }
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
  /** 入池入口：'clar' = 澄清池补料；空 = 证据池直入 */
  source?: string
}

export type RuleConf = '实证' | '文档' | '推测' | '待实证' | '旧文档'

export interface Rule {
  id: string
  text: string
  src: string
  conf: RuleConf
  st: string
  verified: boolean
  suspect: boolean
  /** 归属功能点全路径；空串 = 未归类（Task 5 绑定） */
  node?: string
  nb?: string
  clar?: number | null
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

/** 澄清重检 AI 代答结果（待人工采纳） */
export interface AiReview {
  answer: string
  quote: string
  ev_ids: string[]
  conf: string
  quote_ok: boolean
}

/** open 题人工作答内容 */
export interface ClarAnswer {
  kind: 'opt' | 'text' | 'material'
  text: string
  ev_ids: string[]
}

export interface Clarification {
  no: number
  q: string
  /** choice=选择题 open=开放题；旧数据无此字段按 choice 兼容 */
  kind?: 'choice' | 'open'
  opts: string[]
  st: string
  answer: string | null
  ref: string | null
  ai?: AiReview | null
  ans?: ClarAnswer | null
}

export interface ProfileRule {
  id: string
  text: string
  src: string
  conf: string
}

export interface Profile {
  node: string
  goal: string
  entry: string
  flow: string
  rules: ProfileRule[]
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

export type TreeOpName = 'add' | 'rename' | 'del' | 'prio'

// ---------- 错误：FastAPI 错误体统一包在 detail 里 ----------

export class ApiError extends Error {
  status: number
  detail: unknown
  /** POST /profiles/assemble 409：{detail:{unqualified:[规则id]}} */
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

/** 文本入池：source='clar' 标记澄清池补料入口 */
export const addEvidence = (raw: string, source?: string) =>
  req<EvidenceItem>(`/evidence${source ? `?source=${source}` : ''}`, json('POST', { raw }))

/** 文件入池：后端无 python-multipart，用原始 body + X-Filename 头传文件名；source 标记补料入口 */
export const addEvidenceFile = (file: File, source?: string) =>
  req<EvidenceItem>(`/evidence${source ? `?source=${source}` : ''}`, {
    method: 'POST',
    headers: { 'X-Filename': encodeURIComponent(file.name), 'Content-Type': 'application/octet-stream' },
    body: file,
  })

export const extractEvidence = (id: string) =>
  req<{ added: number }>(`/evidence/${encodeURIComponent(id)}/extract`, {
    method: 'POST',
  })

/** 删除证据：连同其提取产出的规则一并移除 */
export const deleteEvidence = (id: string) =>
  req<void>(`/evidence/${encodeURIComponent(id)}`, { method: 'DELETE' })

// ---------- 规则 ----------

export const getRules = () => req<Rule[]>('/rules')

export const verifyAll = () =>
  req<{ applied: string[]; results: unknown[] }>('/rules/verify', json('POST', {}))

/** 全量核验后台任务：立即返回 job_id，进度/汇总由 GET /jobs 轮询 */
export const verifyJob = () =>
  req<{ job_id: string; total: number; rules: number }>('/rules/verify-job', { method: 'POST' })

export const verifyOne = (id: string) =>
  req<{ applied: string[]; results: unknown[] }>('/rules/verify', json('POST', { rule_id: id }))

/** 人工核过：不经 AI 直接确认 */
export const confirmRule = (id: string) =>
  req<void>(`/rules/${encodeURIComponent(id)}/confirm`, { method: 'POST' })

/** 转问人：进「问人」清单，答案确认后自动核过 */
export const askRule = (id: string) =>
  req<void>(`/rules/${encodeURIComponent(id)}/ask`, { method: 'POST' })

/** 人工挂载/改归属；node 为空串 = 回未归类 */
export const setRuleNode = (id: string, node: string) =>
  req<void>(`/rules/${encodeURIComponent(id)}/node`, json('PUT', { node }))

// ---------- 矛盾 ----------

export const getConflicts = () => req<Conflict[]>('/conflicts')

export const rescanConflicts = () => req<Conflict[]>('/conflicts/rescan', { method: 'POST' })

export const resolveConflict = (id: string, action: 'code' | 'clar', side?: 'a' | 'b') =>
  req<Conflict>('/conflicts', json('POST', { id, action, side }))

// ---------- 空白 ----------

export const getGaps = () => req<Gap[]>('/gaps')

export const rescanGaps = (nodePath?: string) =>
  req<Gap[]>(`/gaps/rescan${nodePath ? `?node_path=${encodeURIComponent(nodePath)}` : ''}`, { method: 'POST' })

export const disposeGap = (id: string, action: 'clar' | 'ok') => req<Gap>('/gaps', json('POST', { id, action }))

// ---------- 维度 ----------

export const getDims = () => req<string[]>('/dims')

export const setDims = (dims: string[]) => req<string[]>('/dims', json('PUT', { dims }))

// ---------- 功能树 ----------

export const getTree = () => req<TreeNode[]>('/tree')

/** op: add/rename/del；path 为空字符串表示根层级（add） */
export const treeOp = (op: TreeOpName, path?: string, name?: string) =>
  req<TreeNode[]>('/tree', json('POST', { op, path: path || undefined, name }))

/** AI 从证据池生成树骨架（仅树空时；后端 409/422 抛 ApiError） */
export const scaffoldTree = () => req<TreeNode[]>('/tree/scaffold', { method: 'POST' })

// ---------- 用户画像 ----------

/** 409 时抛 ApiError（unqualified 为未实证规则 id 列表） */
export const assemble = (nodePath: string, note = '') =>
  req<{ profile: Profile; file: string }>('/profiles/assemble', json('POST', { node_path: nodePath, note }))

/** 提取+核验两阶段后台任务：立即返回 job_id（阶段一逐份提取→阶段二自动分批核验） */
export const extractJob = () =>
  req<{ job_id: string; total: number }>('/evidence/extract-job', { method: 'POST' })

/** 后台任务（批量画像）：进度源——前端轮询、刷新后可恢复 */
export interface Job {
  id: string
  kind: string
  label: string
  cur: number
  total: number
  status: 'running' | 'done'
  ok: number
  extracted?: number  // extract-verify：阶段一提取条数
  corrected?: number  // verify-batch：读错已修正条数
  nobasis?: number    // verify-batch：材料无依据条数
  skipped: string[]
  blocked: string[]
  failed: number
  started_at: number
  finished_at?: number
}

/** 创建批量画像任务：立即返回（node_path 空=全部叶子，给定=该子树叶子）；运行中重复创建后端 409 */
export const assembleBatch = (nodePath = '') =>
  req<{ job_id: string; total: number }>('/profiles/assemble-batch', json('POST', { node_path: nodePath }))

export const listJobs = () => req<Job[]>('/jobs')

export const getProfile = (nodePath: string) => req<Profile>(`/profiles/${encodeURIComponent(nodePath)}`)

export const getDoc = () => req<string>('/doc')

// ---------- 问人 ----------

export const getClarifications = () => req<Clarification[]>('/clarifications')

export const answerClar = (no: number, idx: number) =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'answer', idx }))

export const verifyClar = (no: number) =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'verify' }))

/** 澄清重检：选定材料 × 全部待问 → AI 代答（待采纳），进度走 GET /jobs */
export const reviewClars = (evIds: string[]) =>
  req<{ job_id: string; total: number; questions: number }>('/clarifications/review', json('POST', { ev_ids: evIds }))

/** 采纳 AI 代答（触发规则核过联动） */
export const adoptClar = (no: number) =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'adopt' }))

/** 忽略 AI 代答 */
export const ignoreClar = (no: number) =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'ignore' }))

/** open 题文本作答，可关联材料（人工看图作答场景） */
export const answerClarOpen = (no: number, text: string, evIds: string[] = []) =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'answer', text, ev_ids: evIds }))

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
