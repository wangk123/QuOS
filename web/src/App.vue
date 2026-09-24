<script setup lang="ts">
import { computed, onMounted, provide, ref, watch } from 'vue'
import { ApiError, curSlug, getTree, listBaselines, treeOp, type Baseline, type TreeNode } from './api'
import FuncTree from './components/FuncTree.vue'
import Home from './views/Home.vue'
import Ask from './views/Ask.vue'
import Card from './views/Card.vue'
import Conflict from './views/Conflict.vue'
import Fact from './views/Fact.vue'
import Gap from './views/Gap.vue'
import Pool from './views/Pool.vue'
import Save from './views/Save.vue'
import { NAV_FLOW, NAV_PROJ, baseTag, curName, curPath, goto, view, top, goHome, syncFromHash } from './router'

const nodes = ref<TreeNode[]>([])
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

function findNode(path: string): TreeNode | null {
  if (!path) return null
  let layer = nodes.value
  let cur: TreeNode | null = null
  for (const seg of path.split(',')) {
    cur = layer[+seg] ?? null
    if (!cur) return null
    layer = cur.children
  }
  return cur
}

async function loadTree() {
  try {
    nodes.value = await getTree()
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      goHome()
      toast('项目不存在或已归档')
      return
    }
    throw e
  }
  if (curPath.value && !findNode(curPath.value)) curPath.value = '' // 删选中节点后悬挂重置
}

watch(
  () => [nodes.value, curPath.value],
  () => (curName.value = findNode(curPath.value)?.name ?? '（未选中节点）'),
  { deep: true },
)

async function refreshBaselines() {
  baselines.value = await listBaselines()
  if (baselines.value.length) {
    // list_baselines 按版本号升序返回，「当前」= 最新（最后一项）
    const b = baselines.value[baselines.value.length - 1]
    baseTag.value = `基线 ${b.tag} · ${b.commit.slice(0, 7)}`
  }
}

// 切到「基线」视图时重新拉取（Save 并入基线后本组件数组不会自动更新）
watch(view, v => {
  if (v === 'v-base') void refreshBaselines().catch(() => {})
})

async function boot() {
  err.value = ''
  try {
    await loadTree()
    if (top.value !== 'proj') return // 项目级 404：loadTree 已 goHome+toast，跳过基线加载
    await refreshBaselines()
  } catch (e) {
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

function onToggle(path: string) {
  const n = findNode(path)
  if (n) n.open = !n.open
}

async function onOp(op: 'add' | 'rename' | 'del', path: string) {
  try {
    if (op === 'add') {
      const parent = findNode(path)
      const name = prompt(`加子节点${parent ? ` · ${parent.name}` : '（根层级）'}`)
      if (!name?.trim()) return
      await treeOp('add', path, name.trim())
    } else if (op === 'rename') {
      const n = findNode(path)
      if (!n) return
      const name = prompt('新名称', n.name)
      if (!name?.trim() || name.trim() === n.name) return
      await treeOp('rename', path, name.trim())
    } else {
      const n = findNode(path)
      if (!n || !confirm(`删除「${n.name}」及其全部子节点？`)) return
      await treeOp('del', path)
    }
    await loadTree()
  } catch (e) {
    err.value = e instanceof ApiError ? `操作失败（HTTP ${e.status}）：${e.message}` : String(e)
  }
}

const VIEW_CMP = {
  'v-ev': Pool,
  'v-fact': Fact,
  'v-conf': Conflict,
  'v-gap': Gap,
  'v-card': Card,
  'v-ask': Ask,
  'v-save': Save,
} as const
const viewCmp = computed(() => (VIEW_CMP as Record<string, unknown>)[view.value])
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
      <span class="baseline-tag">{{ baseTag }}</span>
    </header>

    <nav class="navbar">
      <div class="navgrp">
        <span class="grp-lbl">项目</span>
        <button
          v-for="[v, n] in NAV_PROJ"
          :key="v"
          class="step"
          :class="{ active: view === v }"
          type="button"
          @click="goto(v)"
        >{{ n }}</button>
      </div>
      <div class="navgrp">
        <span class="sep" />
        <span class="grp-lbl">整理{{ curPath ? ` · ${curName}` : '' }}</span>
        <template v-for="([v, n], i) in NAV_FLOW" :key="v">
          <button class="step" :class="{ active: view === v }" type="button" @click="goto(v)">
            <span class="n">{{ i + 1 }}</span>{{ n }}
          </button>
          <span v-if="i < NAV_FLOW.length - 1" class="step-arrow">›</span>
        </template>
      </div>
    </nav>

    <div class="main">
      <aside aria-label="功能树">
        <p v-if="err" class="err">{{ err }}</p>
        <FuncTree :nodes="nodes" :cur-path="curPath" @pick="p => (curPath = p)" @toggle="onToggle" @op="onOp" />
      </aside>
      <main class="content">
        <component :is="viewCmp" v-if="viewCmp" />
        <div v-else-if="view === 'v-base'">
          <div class="view-head">
            <h2>基线</h2>
            <span class="sub">项目级版本存档。新需求 diff 定位受影响卡片，只重跑那部分整理。</span>
          </div>
          <div class="card-box">
            <div class="hd">版本时间线</div>
            <div class="bd">
              <div v-if="baselines.length" class="tl">
                <div v-for="(b, i) in baselines" :key="b.tag" class="tl-item" :class="{ cur: i === baselines.length - 1 }">
                  <h4>{{ b.tag }} <span v-if="i === baselines.length - 1" class="badge b-blue">当前</span></h4>
                  <div class="meta">{{ b.commit }}</div>
                </div>
              </div>
              <div v-else style="color: var(--muted-fg)">还没有基线——某节点整理完成（⑥存档）后出现</div>
            </div>
          </div>
          <div class="warn-strip">
            <b>增量定位（M2）</b>粘贴 git diff → AI 定位受影响卡片 → 只重跑该子树的 ①-⑤。当前 M1 先建立基线闭环。
          </div>
        </div>
      </main>
    </div>
  </template>

  <div class="toasts" aria-live="polite">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.cls">{{ t.msg }}</div>
  </div>
</template>

<style scoped>
header {
  display: flex;
  align-items: center;
  gap: 16px;
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
.baseline-tag {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted-fg);
  background: var(--muted);
  padding: 4px 10px;
  border-radius: 999px;
}
.navbar {
  display: flex;
  gap: 18px;
  background: #fff;
  border-bottom: 1px solid var(--border2);
  padding: 8px 20px;
  overflow-x: auto;
  position: sticky;
  top: 52px;
  z-index: 49;
  align-items: center;
}
.navgrp { display: flex; gap: 4px; align-items: center; }
.navgrp .grp-lbl {
  font-size: 10.5px;
  font-weight: 700;
  color: var(--muted-fg);
  letter-spacing: 0.06em;
  margin-right: 6px;
  white-space: nowrap;
}
.navgrp .sep { width: 1px; height: 18px; background: var(--border2); margin: 0 12px 0 18px; }
.step {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 12px;
  border-radius: 999px;
  white-space: nowrap;
  color: var(--muted-fg);
  background: transparent;
}
.step:hover { background: var(--muted); }
.step .n {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--muted);
  color: var(--muted-fg);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.step.active { background: var(--primary); color: #fff; font-weight: 600; }
.step.active .n { background: rgba(255, 255, 255, 0.25); color: #fff; }
.step-arrow { color: var(--border2); flex-shrink: 0; align-self: center; }
.main { display: flex; min-height: calc(100vh - 100px); }
aside {
  width: 264px;
  background: #fff;
  border-right: 1px solid var(--border2);
  padding: 10px 8px;
  flex-shrink: 0;
  overflow-y: auto;
}
.err {
  font-size: 12px;
  color: var(--destructive);
  background: var(--red-bg);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
}
.content { flex: 1; padding: 18px 22px; min-width: 0; }
@media (max-width: 960px) { aside { display: none; } }
</style>
