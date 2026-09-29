// web/src/jobs.ts
// 后台任务轮询：任务状态的真实源在后端（GET /jobs），这里只做查询展示——
// 刷新/换页/重开浏览器后 resumeJobs() 从后端恢复运行中任务，进度条不依赖前端存活。
import { listJobs, type Job } from './api'
import { aiBusy } from './router'

/** 是否有批量任务在跑（Card 批量按钮禁用用） */
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
    toast(summary(j), j.ok ? 'ok' : 'warn')
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
