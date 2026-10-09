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
  /** 归属功能点全路径；__root__ = 根级；空 = 全局/旧数据（未绑定） */
  node: string
}

/** 澄清重检 AI 代答结果（待人工采纳） */
export interface AiReview {
  answer: string
  quote: string
  ev_ids: string[]
  conf: string
  quote_ok: boolean
}

export interface ClarAnswer {
  kind: string
  text: string
  ev_ids: string[]
  /** confirm 选「与实际不符」时补充的实际行为 */
  extra?: string
}

export interface Clarification {
  no: number
  q: string
  /** choice=选择题 open=开放题；旧数据无此字段按 choice 兼容 */
  kind?: 'choice' | 'open'
  /** confirm 确认 | choose 取舍 | supply 补全 | custom 自定义（后端读侧恒非空） */
  type: string
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

/** GET /baseline 仅含 tag/commit；v 仅 POST /baseline 创建时返回；time/note 后端补字段后时间线直接展示 */
export interface Baseline {
  commit: string
  tag: string
  v?: number
  time?: string
  note?: string
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

/** 删除证据：连同其提取产出的规则一并移除 */
export const deleteEvidence = (id: string) =>
  req<void>(`/evidence/${encodeURIComponent(id)}`, { method: 'DELETE' })

// ---------- 规则 ----------

export const getRules = () => req<Rule[]>('/rules')

/** 全量核验后台任务：立即返回 job_id，进度/汇总由 GET /jobs 轮询；only_doc=只核文档级（跳过推测） */
export const verifyJob = (opts?: { only_doc?: boolean }) =>
  req<{ job_id: string; total: number; rules: number }>(
    '/rules/verify-job', opts?.only_doc ? json('POST', { only_doc: true }) : { method: 'POST' })

/** 人工核过：不经 AI 直接确认 */
export const confirmRule = (id: string) =>
  req<void>(`/rules/${encodeURIComponent(id)}/confirm`, { method: 'POST' })

/** 转问人：进「问人」清单，答案确认后自动核过；q 为自定义问法（空 = 后端默认拼接问法） */
export const askRule = (id: string, q?: string) =>
  req<void>(`/rules/${encodeURIComponent(id)}/ask`, json('POST', { q: q ?? '' }))

/** 人工挂载/改归属；node 为空串 = 回未归类 */
export const setRuleNode = (id: string, node: string) =>
  req<void>(`/rules/${encodeURIComponent(id)}/node`, json('PUT', { node }))

// ---------- 矛盾 ----------

export const getConflicts = () => req<Conflict[]>('/conflicts')

export const resolveConflict = (id: string, action: 'code' | 'clar', side?: 'a' | 'b') =>
  req<Conflict>('/conflicts', json('POST', { id, action, side }))

// ---------- 空白 ----------

export const getGaps = () => req<Gap[]>('/gaps')

export const disposeGap = (id: string, action: 'clar' | 'ok') => req<Gap>('/gaps', json('POST', { id, action }))

// ---------- 存疑汇总（根详情「存疑汇总」卡） ----------

export interface DoubtGlobalGap {
  id: string
  dim: string
  text: string
  st: string
}

export interface DoubtModule {
  name: string
  rules: number
  conflicts: number
  gaps: number
  peek: string
}

export interface DoubtSummary {
  stats: { conflicts: number; gaps: number; clarified: number }
  global: DoubtGlobalGap[]
  modules: DoubtModule[]
}

export const getDoubtSummary = () => req<DoubtSummary>('/doubts/summary')

// ---------- 维度 ----------

export const getDims = () => req<string[]>('/dims')

export const setDims = (dims: string[]) => req<string[]>('/dims', json('PUT', { dims }))

// ---------- 功能树 ----------

export const getTree = () => req<TreeNode[]>('/tree')

/** op: add/rename/del；path 为空字符串表示根层级（add） */
export const treeOp = (op: TreeOpName, path?: string, name?: string) =>
  req<TreeNode[]>('/tree', json('POST', { op, path: path || undefined, name }))

// ---------- 用户画像 ----------

/** 项目级画像清单（node 全路径）——⑤ 定稿存档页统计「画像 x/功能点」 */
export const listProfiles = () => req<string[]>('/profiles')

/** 后台任务（批量画像）：进度源——前端轮询、刷新后可恢复 */
export interface Job {
  id: string
  kind: string
  label: string
  cur: number
  total: number
  status: 'running' | 'done' | 'cancelled' | 'failed'
  ok: number
  extracted?: number  // extract-verify：阶段一提取条数
  corrected?: number  // verify-batch：读错已修正条数
  nobasis?: number    // verify-batch：材料无依据条数
  phase?: string        // generate/regen：outline|extract|verify|conflict|assemble|gap|summary
  current_node?: string // generate/regen：assemble 阶段当前节点全路径
  done_nodes?: string[] // generate/regen：已完成节点全路径清单（总表 state 标记用）
  skipped: string[]
  blocked: string[]
  failed: number
  started_at: number
  finished_at?: number
}

export const listJobs = () => req<Job[]>('/jobs')

export const getProfile = (nodePath: string) => req<Profile>(`/profiles/${encodeURIComponent(nodePath)}`)

/** 行内编辑画像 goal：无画像节点后端自动建空画像；'__root__' 可用（根画像） */
export const patchProfileGoal = (full: string, goal: string) =>
  req<Profile>(`/profiles/${encodeURIComponent(full)}`, json('PATCH', { goal }))

export const getDoc = () => req<string>('/doc')

// ---------- 问人 ----------

export const getClarifications = () => req<Clarification[]>('/clarifications')

export const answerClar = (no: number, idx: number, extra = '') =>
  req<Clarification>('/clarifications', json('POST', { no, action: 'answer', idx, extra }))

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

// ---------- 工作台（总表 / 一键生成 / 重生成；对应 server/app/api/generate.py、router.py 工作台段） ----------

/** 总表行（server WbNode 十字段）：path=数字路径，full=全路径，state=''|'done'|'doing' */
export interface WbNodeRow {
  path: string
  name: string
  full: string
  goal: string
  kind: 'module' | 'leaf'
  rules: number
  pend: number
  conf: number
  profiled: boolean
  state: '' | 'done' | 'doing'
}

/** 根画像卡片（profiles/__root__.md；未建时为 null） */
export interface WbRoot {
  goal: string
  entry: string
  flow: string
  boundaries: string
  note: string
  kind: 'root'
}

export interface WbSummary {
  tree: WbNodeRow[]
  root: WbRoot | null
}

export type RegenMode = 'partial' | 'rescan' | 'full'

/** POST /regen/impact 方案卡：关联清单 + AI 建议 mode；recommend 为白名单校验后的推荐方案（失配取 partial）；reason=AI 判断依据一句话 */
export interface ImpactPlan {
  nodes: string[]
  rule_ids: string[]
  clar_nos: string[]
  mode: string
  reason: string
  recommend: RegenMode
}

/** GET /wb/summary：树总表（含每节点徽章计数与 job 进行态）+ 根画像 */
export const wbSummary = () => req<WbSummary>('/wb/summary')

/** 一键生成（证据池非空且树空时；后端 409/422 抛 ApiError），进度走 GET /jobs */
export const generateReq = () => req<{ job_id: string; total: number }>('/generate', { method: 'POST' })

/** 取消当前 generate/regen job（已完成内容保留） */
export const generateCancel = () => req<{ status: string }>('/generate/cancel', { method: 'POST' })

/** 影响分析：新材料 × 现有条目/待确认 → 方案卡（T17 接线，端点 T15 交付） */
export const impactAnalyse = (evIds: string[]) => req<ImpactPlan>('/regen/impact', json('POST', { ev_ids: evIds }))

/** 重生成三模式：partial=受影响节点局部 / rescan=仅待确认代答 / full=全量（T17 接线，端点 T16 交付） */
export const regen = (mode: RegenMode, evIds: string[], nodes?: string[]) =>
  req<{ job_id: string }>('/regen', json('POST', { mode, ev_ids: evIds, nodes }))

/** 根卡 ↻ 摘要：同步重聚合 root+全部 module 画像并写回（不 job 化，秒级返回） */
export const summaryRegen = () => req<{ updated: string[] }>('/summary/regen', { method: 'POST' })

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
