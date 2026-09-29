// 简单视图状态路由（M1 不引 vue-router）：App.vue 内 view 切换 + 跨视图共享状态
import { ref } from 'vue'
import { curSlug, openProject, setProject } from './api'

export type ViewName =
  | 'v-ev' | 'v-fact' | 'v-conf' | 'v-gap' | 'v-prof' | 'v-save' | 'v-base'

export const view = ref<ViewName>('v-ev')
export function goto(v: ViewName) {
  view.value = v
}

/** 当前整理目标（功能树叶节点数字路径，'' = 未选中） */
export const curPath = ref('')
/** 当前整理节点名（App.vue 树加载/切换时写入，各视图标题用） */
export const curName = ref('（未选中节点）')

/** 顶栏基线标签（Save 并入基线后刷新） */
export const baseTag = ref('未建基线')

/** 全局 AI 任务进行中状态：挂在 App 级进度条上，切视图不丢失。
 *  cur/total 给出时进度条显示真实百分比，否则为不定态跑马灯 */
export const aiBusy = ref<{ label: string; cur?: number; total?: number } | null>(null)

export const NAV_PROJ: [ViewName, string][] = [
  ['v-ev', '证据池'],
  ['v-base', '基线'],
]
export const NAV_FLOW: [ViewName, string][] = [
  ['v-fact', '规则提取'],
  ['v-conf', '冲突裁决'],
  ['v-prof', '生成画像'],
  ['v-gap', '查漏补缺'],
  ['v-save', '定稿存档'],
]

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
