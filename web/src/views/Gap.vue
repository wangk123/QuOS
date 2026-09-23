<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { ApiError, disposeGap, getDims, getGaps, rescanGaps, setDims, type Gap } from '../api'
import { curName } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const gaps = ref<Gap[]>([])
const dims = ref<string[]>([])
const err = ref('')
const aiLabel = ref('')
const showDimModal = ref(false)
const newDim = ref('')

async function load() {
  ;[gaps.value, dims.value] = await Promise.all([getGaps(), getDims()])
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
  }
})

const openCnt = computed(() => gaps.value.filter(g => g.st === 'open').length)
const groups = computed(() => {
  const known = dims.value.map(d => [d, gaps.value.filter(g => g.dim === d)] as const)
  const rest = gaps.value.filter(g => !dims.value.includes(g.dim))
  return rest.length ? [...known, ['未分组', rest] as const] : known
})

async function dispose(g: Gap, action: 'clar' | 'ok') {
  try {
    await disposeGap(g.id, action)
    await load()
    toast(action === 'clar' ? '空白 → 「问人」清单' : '已判读：设计如此')
  } catch (e) {
    toast(e instanceof ApiError ? `处置失败：${e.message}` : '处置失败', 'warn')
  }
}

async function rescan() {
  aiLabel.value = `AI 按 ${dims.value.length} 个维度扫描：${dims.value.join('/')}…`
  try {
    const items = await rescanGaps()
    await load()
    toast(`扫描完成：空白 ${items.filter(g => g.st === 'open').length} 项`)
  } catch (e) {
    toast(e instanceof ApiError ? `重扫失败：${e.message}` : '重扫失败', 'warn')
  } finally {
    aiLabel.value = ''
  }
}

async function addDim() {
  const v = newDim.value.trim()
  if (!v) {
    toast('填维度名')
    return
  }
  if (dims.value.includes(v)) {
    toast('已存在')
    return
  }
  try {
    dims.value = await setDims([...dims.value, v])
    newDim.value = ''
    toast(`维度「${v}」已加，重扫后生效`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `保存失败：${e.message}` : '保存失败', 'warn')
  }
}

async function delDim(i: number) {
  try {
    dims.value = await setDims(dims.value.filter((_, j) => j !== i))
    toast('维度已删（空白项保留，不匹配任何维度则归入「未分组」）')
  } catch (e) {
    toast(e instanceof ApiError ? `保存失败：${e.message}` : '保存失败', 'warn')
  }
}
</script>

<template>
  <div>
    <div class="view-head">
      <h2>③ 找空白 · {{ curName }}</h2>
      <span class="sub">按可配置的维度清单挨个问「这里说清了吗」——文档没写、代码看不出、口头没提的，就是空白。</span>
      <div class="spacer" style="flex: 1" />
      <button class="btn-ghost" type="button" @click="showDimModal = true">⚙ 维度配置（{{ dims.length }}）</button>
      <button class="btn" type="button" @click="rescan">AI 重扫（按当前维度）</button>
      <span class="badge" :class="openCnt ? 'b-red' : 'b-green'">待处理 {{ openCnt }}</span>
    </div>

    <p v-if="err" class="err">{{ err }}</p>
    <div v-if="aiLabel" class="ai-run">
      <span class="spin" /><span>{{ aiLabel }}</span><div class="bar"><i /></div>
    </div>

    <div v-for="[dim, items] in groups" :key="dim" class="gap-group">
      <div class="g-hd">
        <span class="badge b-blue">{{ dim }}</span>{{ dim }}完备性
        <span v-if="items.length" class="src">{{ items.filter(g => g.st === 'open').length }} 项待处理</span>
        <span v-else class="src">干净</span>
      </div>
      <div v-for="g in items" :key="g.id" class="gap-item" :class="{ done: g.st !== 'open' }">
        <span class="t" :style="g.st !== 'open' ? 'text-decoration: line-through' : ''">{{ g.text }}</span>
        <template v-if="g.st === 'open'">
          <button class="btn btn-sm" type="button" @click="dispose(g, 'clar')">转问人</button>
          <button class="btn-ghost btn-sm" type="button" @click="dispose(g, 'ok')">设计如此</button>
        </template>
        <span v-else-if="g.st === 'clar'" class="badge b-amber">已转问人</span>
        <span v-else class="badge b-gray">设计如此</span>
      </div>
    </div>
    <div v-if="!gaps.length" class="empty">
      {{ err ? '' : '没有空白记录——点「AI 重扫」按当前维度扫一遍（组装卡片后扫描更准）' }}
    </div>

    <div v-if="showDimModal" class="modal-bg" @click.self="showDimModal = false">
      <div class="modal" role="dialog" aria-modal="true">
        <h3>找空白 · 维度配置</h3>
        <p style="font-size: 12px; color: var(--muted-fg); margin-bottom: 8px">
          项目级规则库，预置六维；按业务域增删（如金融加「审计留痕」「监管报送」）。
        </p>
        <div class="dim-row" v-for="(d, i) in dims" :key="d">
          <span class="nm">{{ d }}</span>
          <span class="src">{{ gaps.filter(g => g.dim === d).length }} 项</span>
          <button type="button" @click="delDim(i)">删除</button>
        </div>
        <label>新增维度</label>
        <div style="display: flex; gap: 8px">
          <input v-model="newDim" type="text" placeholder="如：审计留痕" @keydown.enter.prevent="addDim" />
          <button class="btn-ghost" type="button" @click="addDim">添加</button>
        </div>
        <div class="foot">
          <button class="btn" type="button" @click="showDimModal = false">完成</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
</style>
