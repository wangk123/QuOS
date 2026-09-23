<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, PROJ, getTree, listBaselines, treeOp, type TreeNode } from './api'
import FuncTree from './components/FuncTree.vue'

// M1 骨架：视图区占位，具体视图 Task 12 实现
const nodes = ref<TreeNode[]>([])
const curPath = ref('')
const baseTag = ref('未建基线')
const err = ref('')
const view = ref('v-ev')

const NAV_PROJ: [string, string][] = [
  ['v-ev', '证据池'],
  ['v-base', '基线'],
]
const NAV_FLOW: [string, string][] = [
  ['v-fact', '提事实'],
  ['v-conf', '挑矛盾'],
  ['v-gap', '找空白'],
  ['v-card', '成卡片'],
  ['v-ask', '问人'],
  ['v-save', '存档'],
]

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
const curName = computed(() => findNode(curPath.value)?.name ?? '（未选中节点）')

async function loadTree() {
  nodes.value = await getTree()
  if (curPath.value && !findNode(curPath.value)) curPath.value = '' // 删选中节点后悬挂重置
}

onMounted(async () => {
  try {
    await loadTree()
    const bl = await listBaselines()
    if (bl.length) baseTag.value = `基线 ${bl[0].tag} · ${bl[0].commit}`
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : '无法连接后端——请先启动 server'
  }
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
</script>

<template>
  <header>
    <div class="logo">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2v20M2 12h20" /><circle cx="12" cy="12" r="9" />
      </svg>
      QuOS
    </div>
    <div class="proj">项目 <b>{{ PROJ }}</b></div>
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
        @click="view = v"
      >{{ n }}</button>
    </div>
    <div class="navgrp">
      <span class="sep" />
      <span class="grp-lbl">整理{{ curPath ? ` · ${curName}` : '' }}</span>
      <template v-for="([v, n], i) in NAV_FLOW" :key="v">
        <button class="step" :class="{ active: view === v }" type="button" @click="view = v">
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
      <div class="placeholder">
        <h2>{{ curName }}</h2>
        <p>视图在 Task 12 实现</p>
      </div>
    </main>
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
.placeholder {
  padding: 40px;
  text-align: center;
  color: var(--muted-fg);
  background: #fff;
  border: 1px dashed var(--border2);
  border-radius: var(--radius);
}
.placeholder h2 { color: var(--fg); margin-bottom: 6px; }
@media (max-width: 960px) { aside { display: none; } }
</style>
