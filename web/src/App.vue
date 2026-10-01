<script setup lang="ts">
// 工作台终态（T19）：App = 顶栏（版本 | 证据池(n) | 待确认(n)）+ Workbench 单视图 + 全局进度条 + 弹窗/toasts。
// 五步旧视图、侧栏树与 v-base 基线块均已删（版本入口收敛为 VerModal 弹窗）。
import { computed, onMounted, provide, ref, watch } from 'vue'
import { ApiError, curSlug, generateCancel, getClarifications, getEvidence, listBaselines, type Baseline, type EvidenceItem } from './api'
import ClarModal from './components/ClarModal.vue'
import EvPoolModal from './components/EvPoolModal.vue'
import ImpactModal from './components/ImpactModal.vue'
import VerModal from './components/VerModal.vue'
import Home from './views/Home.vue'
import Workbench from './views/Workbench.vue'
import { aiBusy, goHome, syncFromHash, top } from './router'
import { resumeJobs } from './jobs'
import { refreshWb } from './wb'

const err = ref('')
const baselines = ref<Baseline[]>([])

interface Toast {
  id: number
  msg: string
  cls: string
}
let toastSeq = 0
const toasts = ref<Toast[]>([])

function toast(msg: string, cls = '') {
  const t = { id: ++toastSeq, msg, cls }
  toasts.value.push(t)
  setTimeout(() => (toasts.value = toasts.value.filter(x => x.id !== t.id)), 2800)
}
provide('toast', toast)
provide('refreshClar', refreshClar) // Workbench 右栏待确认落定后刷新顶栏角标

async function refreshBaselines() {
  baselines.value = await listBaselines()
}

// 顶栏「待确认」弹窗（T13）：wait 状态条数角标
const clarOpen = ref(false)
const clarWait = ref(0)
async function refreshClar() {
  clarWait.value = (await getClarifications()).filter(c => c.st === 'wait').length
}
// 弹窗内单题落定（记答复/采纳→规则自动核过）：角标与工作台树徽章同刷
function onClarChanged() {
  void refreshClar().catch(() => {})
  void refreshWb().catch(() => {})
}

// 顶栏「证据池」弹窗（T12）：列表数据由 App 持有，角标 = 同源计数；增删后弹窗 emit changed 重拉
const evOpen = ref(false)
const evidence = ref<EvidenceItem[]>([])
const evCount = computed(() => evidence.value.length)
async function refreshEv() {
  evidence.value = await getEvidence()
}
function onEvChanged() {
  void refreshEv().catch(() => {})
}

/** B3 取消入口：终结当前 generate/regen job；已完成内容保留，aiBusy 由 jobs 轮询驱动自动消失 */
async function onCancelAi() {
  try {
    await generateCancel()
    toast('已取消——已完成内容保留')
  } catch (e) {
    toast(e instanceof Error ? e.message : '取消失败', 'warn')
  }
}
/** 重新生成入口（T17）：打开影响分析弹窗——触发材料 = 未提取（state!=='extracted'）的新材料；
 *  同时关掉证据池弹窗，防双弹窗叠层与两处 paste 监听双投递 */
const impactOpen = ref(false)
const newEvIds = computed(() => evidence.value.filter(e => e.state !== 'extracted').map(e => e.id))
function onImpact() {
  evOpen.value = false
  impactOpen.value = true
}
/** regen job 已发起：立即刷总表（空新材料直接打开时弹窗内自会提示，不执行） */
function onImpactDone() {
  void refreshWb().catch(() => {})
}

// 顶栏「版本」弹窗（T14 终态唯一版本入口）：存版成功后重拉基线
const verOpen = ref(false)
function onSaved() {
  void refreshBaselines().catch(() => {})
}

async function boot() {
  err.value = ''
  try {
    await refreshWb() // wb 探测：项目不存在 404 统一在此兜底（Workbench 内 useWb 刷新失败静默）
    if (top.value !== 'proj') return
    await refreshBaselines()
    void resumeJobs(toast) // 恢复后端仍在跑的批量任务进度（页面刷新/重开场景）
    void refreshClar().catch(() => {})
    void refreshEv().catch(() => {})
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      goHome()
      toast('项目不存在或已归档')
      return
    }
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : '无法连接后端——请先启动 server'
  }
}

onMounted(() => {
  const pre = top.value
  try {
    syncFromHash()
  } catch {
    // 畸形 hash（如 #/p/%）decode 抛 URIError：停留 home
  }
  // 浏览器前进/后退改变 hash 时同步顶层状态（enterProject/goHome 自身写的 hash
  // 已与状态一致，syncFromHash 幂等跳过，不会重复触发切换）
  window.addEventListener('hashchange', () => {
    try {
      syncFromHash()
    } catch {
      // 畸形 hash：停留当前态
    }
  })
  // syncFromHash 造成 home→proj 切换时由下方 watch 接手，避免双重 boot
  if (top.value === 'proj' && pre === 'proj') void boot()
})

// 首次进入/切换项目（含 syncFromHash 恢复、hashchange 项目间前进后退）时加载树+基线
watch([top, curSlug], ([t]) => {
  if (t === 'proj') void boot()
})
</script>

<template>
  <Home v-if="top === 'home'" />
  <template v-else>
    <header>
      <div class="logo">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2v20M2 12h20" /><circle cx="12" cy="12" r="9" />
        </svg>
        QuOS
      </div>
      <button class="ghost" @click="goHome">⟵ 项目</button>
      <div class="proj">项目 <b>{{ curSlug }}</b></div>
      <span class="spacer"></span>
      <!-- 三入口全为弹窗位：版本弹窗（T14）/证据池弹窗（T12）/待确认弹窗（T13） -->
      <button class="ghost-sm" type="button" @click="verOpen = true">版本</button>
      <button class="pool-btn" type="button" @click="evOpen = true">
        证据池<span v-if="evCount" class="pool-badge">{{ evCount }}</span>
      </button>
      <button class="pool-btn" type="button" @click="clarOpen = true">
        待确认<span v-if="clarWait" class="pool-badge">{{ clarWait }}</span>
      </button>
    </header>

    <ClarModal :open="clarOpen" :evidence="evidence" @close="clarOpen = false" @changed="onClarChanged" />
    <EvPoolModal :open="evOpen" :evidence="evidence" @close="evOpen = false" @changed="onEvChanged" @impact="onImpact" />
    <ImpactModal :open="impactOpen" :ev-ids="newEvIds" :evidence="evidence" @close="impactOpen = false" @done="onImpactDone" />
    <VerModal :open="verOpen" @close="verOpen = false" @saved="onSaved" />

    <p v-if="err" class="err">{{ err }}</p>

    <!-- 后台进度条：状态在 router.ts 的 aiBusy，切页不丢失；有 cur/total 时为真实百分比 -->
    <div v-if="aiBusy" class="ai-run global-ai">
      <span class="spin" /><span>{{ aiBusy.label }}{{ aiBusy.total ? `（${aiBusy.cur ?? 0}/${aiBusy.total}）` : '' }}</span>
      <div class="bar"><i :style="aiBusy.total ? { width: `${Math.round(((aiBusy.cur ?? 0) / aiBusy.total) * 100)}%`, animation: 'none' } : undefined" /></div>
      <button class="cancel-btn" type="button" @click="onCancelAi">取消</button>
    </div>

    <main class="content wb">
      <Workbench />
    </main>
  </template>

  <div class="toasts" aria-live="polite">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.cls">{{ t.msg }}</div>
  </div>
</template>

<style scoped>
header {
  display: flex;
  align-items: center;
  gap: 14px;
  background: #fff;
  border-bottom: 1px solid var(--border2);
  padding: 0 20px;
  height: 52px;
  position: sticky;
  top: 0;
  z-index: 50;
}
.logo { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 15px; color: var(--primary); }
.proj { display: flex; align-items: center; gap: 8px; color: var(--muted-fg); }
.ghost-sm { background: #fff; color: var(--muted-fg); border: 1px solid var(--border2); padding: 6px 13px; font-weight: 600; }
.ghost-sm:hover { background: var(--muted); }
.pool-btn { position: relative; background: #fff; color: var(--primary); border: 1px solid var(--border2); padding: 6px 13px; font-weight: 600; }
.pool-btn:hover { background: var(--muted); }
.pool-badge { position: absolute; top: -4px; right: -8px; min-width: 16px; height: 16px;
  border-radius: 8px; background: var(--destructive); color: #fff; font-size: 10px;
  display: flex; align-items: center; justify-content: center; padding: 0 4px; }
.global-ai {
  position: sticky;
  top: 52px;
  z-index: 48;
  margin: 10px 20px 0;
}
.global-ai .cancel-btn { background: #fff; color: var(--destructive); border: 1px solid var(--border2); border-radius: 6px; padding: 3px 12px; font-size: 12px; font-weight: 600; flex: none; cursor: pointer; }
.global-ai .cancel-btn:hover { background: var(--red-bg); }
.err {
  font-size: 12px;
  color: var(--destructive);
  background: var(--red-bg);
  border-radius: 6px;
  padding: 8px 10px;
  margin: 10px 20px 0;
}
.content { min-height: calc(100vh - 52px); padding: 18px 22px; min-width: 0; }
.content.wb { padding: 0; } /* Workbench 的 .stage 自带分栏 padding */
</style>
