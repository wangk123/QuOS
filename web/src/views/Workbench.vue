<script setup lang="ts">
// Task 9 工作台布局壳：树空 → 整页 Landing（导入态；job 完成后 refreshWb 拉到树切态）；
// 树非空 → .stage 左右分栏（WbTree 58fr / WbDetail 42fr，各自 sticky 独立滚动，样式迁原型 workbench.html）。
// selected = 同页选中态（'__root__'=根详情）；WbTree pick 与 WbDetail jump（面包屑/主线 chips）都只切 selected。
import { computed, inject, onUnmounted, ref } from 'vue'
import { patchProfileGoal, summaryRegen } from '../api'
import WbTree from '../components/WbTree.vue'
import { jobRunning } from '../jobs'
import { useWb } from '../wb'
import Landing from './Landing.vue'
import WbDetail from './WbDetail.vue'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})
const refreshClar = inject<() => Promise<void>>('refreshClar', async () => {})
const { wb, refreshWb, stop } = useWb()
onUnmounted(stop)

const selected = ref('__root__')
/** 跳转落地 tab：存疑汇总行 → 'doubt'；其余路径回概要——每条选中路径都显式写，无悬挂态 */
const selTab = ref<'overview' | 'doubt'>('overview')
function jump(full: string, tab?: 'doubt') {
  selected.value = full
  selTab.value = tab ?? 'overview'
}
const empty = computed(() => (wb.value?.tree ?? []).length === 0)

/** 右栏节点态：树行直查；根 '__root__' 永可看——仅 running job 期间给 doing 骨架，否则 done */
function stateOf(full: string) {
  if (full === '__root__') return jobRunning.value ? 'doing' : 'done'
  return wb.value?.tree.find(r => r.full === full)?.state ?? ''
}

/** 根卡 ↻ 摘要：同步重聚合 root+全部 module 画像（秒级），完成后刷新总表 */
async function onRefreshRoot() {
  try {
    await summaryRegen()
    await refreshWb()
    toast('总览与模块摘要已重生成', 'ok')
  } catch (e) {
    toast(e instanceof Error ? e.message : '摘要重生成失败', 'warn')
  }
}

/** 根卡 ✎：行内编辑根 goal（后端 __root__ 直存） */
async function onEditRoot() {
  const goal = prompt('需求总览（一句话）', wb.value?.root?.goal ?? '')
  if (goal === null) return
  try {
    await patchProfileGoal('__root__', goal)
    await refreshWb()
  } catch (e) {
    toast(e instanceof Error ? e.message : '总览保存失败', 'warn')
  }
}
</script>

<template>
  <Landing v-if="empty" @generated="refreshWb" />
  <div v-else class="stage">
    <div class="treezone">
      <WbTree
        :selected="selected"
        @pick="s => { selected = s; selTab = 'overview' }"
        @refresh-root="onRefreshRoot"
        @edit-root="onEditRoot"
      />
    </div>
    <div class="detailzone">
      <WbDetail :node-full="selected" :state="stateOf(selected)" :initial-tab="selTab" @jump="jump" @clar-changed="() => void refreshClar()" />
    </div>
  </div>
</template>

<style scoped>
.stage { display: grid; grid-template-columns: minmax(500px, 58fr) minmax(430px, 42fr); min-height: calc(100vh - 52px); }
.treezone { padding: 16px 14px 80px 22px; overflow-y: auto; border-right: 1px solid var(--border2); position: sticky; top: 52px; max-height: calc(100vh - 52px); }
.detailzone { padding: 16px 22px 80px 18px; overflow-y: auto; position: sticky; top: 52px; max-height: calc(100vh - 52px); }
@media (max-width: 960px) {
  .stage { grid-template-columns: 1fr; }
  .treezone, .detailzone { position: static; max-height: none; }
}
</style>
