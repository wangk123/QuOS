// 简单视图状态路由（M1 不引 vue-router）：App.vue 内 view 切换 + 跨视图共享状态
import { ref } from 'vue'

export type ViewName =
  | 'v-ev' | 'v-fact' | 'v-conf' | 'v-gap' | 'v-card' | 'v-ask' | 'v-save' | 'v-base'

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

export const NAV_PROJ: [ViewName, string][] = [
  ['v-ev', '证据池'],
  ['v-base', '基线'],
]
export const NAV_FLOW: [ViewName, string][] = [
  ['v-fact', '提事实'],
  ['v-conf', '挑矛盾'],
  ['v-gap', '找空白'],
  ['v-card', '成卡片'],
  ['v-ask', '问人'],
  ['v-save', '存档'],
]
