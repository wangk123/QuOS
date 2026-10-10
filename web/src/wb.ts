// web/src/wb.ts —— 工作台聚合状态：/wb/summary 拉取 + job 期间自动刷新 + 徽章派生
import { ref } from 'vue'
import { jobRunning } from './jobs'
import { wbSummary, type WbSummary } from './api'

export const wb = ref<WbSummary | null>(null)
export async function refreshWb() { wb.value = await wbSummary() }
export function useWb() {
  void refreshWb()
  const t = setInterval(() => { if (jobRunning.value) void refreshWb() }, 1500)
  return { wb, refreshWb, stop: () => clearInterval(t) }
}

/** full → 数字路径：/profiles/{node_path} 是单段参数，只匹配数字路径或 __root__——含 / 的 full 会 404/405 */
export function digitPathOf(full: string): string {
  if (full === '__root__') return full
  return wb.value?.tree.find(r => r.full === full)?.path ?? ''
}
