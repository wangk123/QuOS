// web/src/jobs.ts
// 后台任务轮询：任务状态的真实源在后端（GET /jobs），这里只做查询展示——
// 刷新/换页/重开浏览器后 resumeJobs() 从后端恢复运行中任务，进度条不依赖前端存活。
import { listJobs, type Job } from './api'
import { aiBusy } from './router'

/** 是否有批量任务在跑（Profile 批量按钮禁用用） */
import { ref } from 'vue'
export const jobRunning = ref(false)

let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollingId: string | null = null

function applyJob(j: Job) {
  jobRunning.value = j.status === 'running'
  if (j.status === 'running') {
    aiBusy.value = { label: j.label, cur: j.cur, total: j.total }
  } else {
    aiBusy.value = null
  }
}

function summary(j: Job): string {
  // cancelled/failed 是终态：先于各 kind 的「完成」文案分流，避免误报完成
  if (j.status === 'cancelled') return `任务已取消：${j.label}`
  if (j.status === 'failed') return `任务已失败：${j.label}`
  if (j.kind === 'extract-verify') {
    const parts = [`提取 ${j.extracted ?? 0} 条`]
    if (j.corrected !== undefined) parts.push(`一致 ${j.ok}`, `修正 ${j.corrected}`, `无依据 ${j.nobasis}`)
    if (j.failed) parts.push(`失败 ${j.failed}`)
    return `提取并核验完成：${parts.join(' · ')}（无依据项请人工过或转澄清）`
  }
  if (j.kind === 'verify-batch') {
    const parts = [`一致 ${j.ok} 条`, `修正 ${j.corrected} 条`, `无依据 ${j.nobasis} 条`]
    if (j.failed) parts.push(`失败 ${j.failed}`)
    return `核验完成：${parts.join(' · ')}（无依据项请人工过或转澄清）`
  }
  if (j.kind === 'regen' && j.auto_resolved) {
    const parts = []
    if (j.auto_resolved?.length) parts.push(`自动裁决 ${j.auto_resolved.length} 处冲突`)
    if (j.auto_closed?.length) parts.push(`闭环 ${j.auto_closed.length} 条缺口`)
    if (j.regen_nodes?.length) parts.push(`重组 ${j.regen_nodes.length} 个节点`)
    if (parts.length) return `智能生成完成：${parts.join(' · ')}`
  }
  if (j.kind === 'generate') {
    // ok=assemble 成功节点数；blocked=闸门拦下的未核验节点
    const parts = [`${j.ok} 节点就绪`]
    if (j.blocked.length) parts.push(`${j.blocked.length} 待核验跳过`)
    return `生成完成：${parts.join(' · ')}`
  }
  if (j.kind === 'regen') {
    const parts = [`${j.ok} 节点更新`]
    if (j.blocked.length) parts.push(`${j.blocked.length} 待核验跳过`)
    return `重生成完成：${parts.join(' · ')}`
  }
  const parts = [`成功 ${j.ok} 张`]
  if (j.skipped.length) parts.push(`跳过 ${j.skipped.length}（无规则：${j.skipped.slice(0, 3).join('、')}${j.skipped.length > 3 ? '…' : ''}）`)
  if (j.blocked.length) parts.push(`阻断 ${j.blocked.length}（未核验：${j.blocked.slice(0, 3).join('、')}${j.blocked.length > 3 ? '…' : ''}）`)
  if (j.failed) parts.push(`失败 ${j.failed}`)
  return `批量生成完成：${parts.join(' · ')}`
}

async function tick(jobId: string, toast: (msg: string, cls?: string) => void): Promise<boolean> {
  const rows = await listJobs()
  const j = rows.find(x => x.id === jobId)
  if (!j) {
    jobRunning.value = false
    aiBusy.value = null
    return true // 任务不存在（服务重启）：终止轮询
  }
  applyJob(j)
  if (j.status !== 'running') {
    // cancelled/failed 终态固定 warn（ok>0 的部分结果也非成功色）；done 按 ok 有无分流
    const cls = j.status === 'done' && j.ok > 0 ? 'ok' : 'warn'
    toast(summary(j), cls)
    return true
  }
  return false
}

async function step(jobId: string, toast: (msg: string, cls?: string) => void): Promise<void> {
  try {
    if (await tick(jobId, toast)) {
      pollTimer = null
      pollingId = null
      return
    }
  } catch {
    // 网络抖动：下轮重试，不打断轮询
  }
  pollTimer = setTimeout(() => void step(jobId, toast), 1500)
}

/** 发起方调用：开始轮询指定任务（立即查一次再定时；同一时刻只跟踪一个） */
export function startJobPolling(jobId: string, toast: (msg: string, cls?: string) => void): void {
  if (pollTimer) clearTimeout(pollTimer)
  pollingId = jobId
  jobRunning.value = true
  void step(jobId, toast)
}

/** App 启动/项目进入时调用：恢复后端仍在跑的任务（页面刷新/重开浏览器场景） */
export async function resumeJobs(toast: (msg: string, cls?: string) => void): Promise<void> {
  if (pollingId) return // 已在跟踪
  try {
    const rows = await listJobs()
    const run = rows.find(x => x.status === 'running')
    if (run) {
      applyJob(run)
      startJobPolling(run.id, toast)
    } else {
      // 无运行任务（含服务重启中断）：清干净前端残留态
      jobRunning.value = false
      aiBusy.value = null
    }
  } catch {
    // 后端暂不可达：静默，下次进入再试
  }
}
