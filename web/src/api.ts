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
}

export interface Conflict {
  id: string
  parties: string[] // 参与规则 id（2~N 同主题说法）
  q: string
  st: string // open | done
  resolution: string | null // 胜方规则 id | 'manual'
  manual_text?: string // 选「其他」手输的实际行为
  node?: string // 归属节点全路径（后端唯一口径 _conflict_node；'__root__'=全局）
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
  if (res.status === 204) return undefined as T  // 无响应体（confirm/delete 等），跳过解析
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

/** 人工修正：实际行为与规则不符——文本替换+标黄留痕+核过 */
export const correctRule = (id: string, text: string) =>
  req<Rule>(`/rules/${encodeURIComponent(id)}/correct`, json('POST', { text }))

/** 自定义开放核实记录：问题+答案直接落规则（人工确认级，绑节点） */
export const addRuleManual = (text: string, node: string) =>
  req<Rule>('/rules', json('POST', { text, node }))

/** 人工核过：不经 AI 直接确认 */
export const confirmRule = (id: string) =>
  req<void>(`/rules/${encodeURIComponent(id)}/confirm`, { method: 'POST' })

/** 删除规则（物理删） */
export const deleteRule = (id: string) =>
  req<void>(`/rules/${encodeURIComponent(id)}`, { method: 'DELETE' })

/** 转问人：进「问人」清单，答案确认后自动核过；q 为自定义问法（空 = 后端默认拼接问法） */

/** 人工挂载/改归属；node 为空串 = 回未归类 */
export const setRuleNode = (id: string, node: string) =>
  req<void>(`/rules/${encodeURIComponent(id)}/node`, json('PUT', { node }))

// ---------- 矛盾 ----------

export const getConflicts = () => req<Conflict[]>('/conflicts')

/** 裁决：code=信第 side 方（parties 索引）；manual=其他（text=手输实际行为，后端落实证规则） */
export const resolveConflict = (id: string, action: 'code' | 'manual', side?: number, text?: string) =>
  req<Conflict>('/conflicts', json('POST', { id, action, side: side ?? -1, text: text ?? '' }))

// ---------- 空白 ----------

export const getGaps = () => req<Gap[]>('/gaps')

/** 缺口处置：ok=设计如此 | note=人工补写说明（text 生成实证规则并闭环） */
export const disposeGap = (id: string, action: 'ok' | 'note' = 'ok', text = '') =>
  req<Gap>('/gaps', json('POST', { id, action, text }))

// ---------- 存疑汇总（根详情「存疑汇总」卡） ----------

export interface DoubtGlobalGap {
  id: string
  dim: string
  text: string
  st: string
}

export interface DoubtModule {
  name: string
  /** 总数 = rules + open 冲突 + open 缺口（与树行同口径） */
  total?: number
  rules: number
  conflicts: number
  gaps: number
  peek: string
}

export interface DoubtGlobalConflict {
  id: string
  q: string
  st: string
}

export interface DoubtSummary {
  stats: { conflicts: number; gaps: number }
  global: DoubtGlobalGap[]
  globalConflicts: DoubtGlobalConflict[]
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
  done_nodes?: string[]
  auto_resolved?: string[] // smart：自动裁决的冲突 id
  auto_closed?: string[] // smart：自动闭环的缺口 id
  regen_nodes?: string[] // smart：重组的节点全路径 // generate/regen：已完成节点全路径清单（总表 state 标记用）
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

// ---------- 基线 ----------

export const createBaseline = (note = '基线存档') =>
  req<Baseline>('/baseline', json('POST', { note }))

export const listBaselines = () => req<Baseline[]>('/baseline')

// ---------- 工作台（总表 / 一键生成 / 重生成；对应 server/app/api/generate.py、router.py 工作台段） ----------

/** 总表行（server WbNode 十一字段）：path=数字路径，full=全路径，state=''|'done'|'doing'
 * 四原子指标：rules 条目 / unverified 未核验 / conf 冲突 / gaps 缺口（模块行=子树聚合，与存疑汇总同源） */
export interface WbNodeRow {
  path: string
  name: string
  full: string
  goal: string
  kind: 'module' | 'leaf'
  /** 总数 = 有效规则 + open 冲突 + open 缺口（树行/tab/chips 唯一口径） */
  total: number
  rules: number
  unverified: number
  conf: number
  gaps: number
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

export type RegenMode = 'full' | 'smart'

/** GET /wb/summary：树总表（含每节点徽章计数与 job 进行态）+ 根画像 */
export const wbSummary = () => req<WbSummary>('/wb/summary')

/** 一键生成（证据池非空且树空时；后端 409/422 抛 ApiError），进度走 GET /jobs */
export const generateReq = () => req<{ job_id: string; total: number }>('/generate', { method: 'POST' })

/** 取消当前 generate/regen job（已完成内容保留） */
export const generateCancel = () => req<{ status: string }>('/generate/cancel', { method: 'POST' })

/** 重新生成两模式：full=全量重跑 / smart=智能生成（六阶段：新材料→重核→疑点直处→影响分析→重组→汇总） */
export const regen = (mode: RegenMode, evIds: string[]) =>
  req<{ job_id: string; mode: string; total: number }>('/regen', json('POST', { mode, ev_ids: evIds }))

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
export const patchProject = (slug: string, patch: { name?: string; description?: string }) =>
  reqRoot<{ slug: string; name: string; description: string }>(
    `/${encodeURIComponent(slug)}`, json('PATCH', patch))
export const archiveProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}/archive`, { method: 'POST' })
export const restoreProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}/restore`, { method: 'POST' })
export const purgeProject = (slug: string) =>
  reqRoot<void>(`/${encodeURIComponent(slug)}`, { method: 'DELETE' })
