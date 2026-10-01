// 简单视图状态路由（M1 不引 vue-router）：App.vue 顶层 home/proj 切换 + 跨组件共享状态
import { ref } from 'vue'
import { curSlug, openProject, setProject } from './api'

/** 工作台终态（T19）：仅 v-wb 单一工作台——证据池/待确认/版本全为弹窗，五步旧视图与 v-base 已删 */
export type ViewName = 'v-wb'

export const view = ref<ViewName>('v-wb')

/** 全局 AI 任务进行中状态：挂在 App 级进度条上，切页不丢失。
 *  cur/total 给出时进度条显示真实百分比，否则为不定态跑马灯 */
export const aiBusy = ref<{ label: string; cur?: number; total?: number } | null>(null)

// ---------- 两级顶层导航：home 项目首页 / proj 项目工作台 ----------

export const top = ref<'home' | 'proj'>('home')

/** 进入项目工作台：设置项目上下文 + 记录 last_opened（失败无感） */
export async function enterProject(slug: string) {
  setProject(slug)
  top.value = 'proj'
  location.hash = `#/p/${encodeURIComponent(slug)}`
  void openProject(slug).catch(() => {})
}

export function goHome() {
  top.value = 'home'
  setProject('')
  location.hash = '#/'
}

/** 解析当前 hash 同步顶层状态（可重入：初始化与 hashchange 前进/后退共用）
 *  - `#/p/<slug>`：进入项目工作台；slug 缺失时停留当前态
 *  - 其他 hash（含 `#/`）：回到 home 态（curSlug 清空）
 *  - 目标状态与当前一致则跳过；畸形 hash 由调用方 try/catch 兜底
 */
export function syncFromHash() {
  const m = location.hash.match(/^#\/p\/(.*)$/)
  if (m) {
    const slug = decodeURIComponent(m[1])
    if (!slug) return
    if (slug === curSlug.value && top.value === 'proj') return
    setProject(slug)
    top.value = 'proj'
  } else {
    if (top.value === 'home' && !curSlug.value) return
    top.value = 'home'
    setProject('')
  }
}
