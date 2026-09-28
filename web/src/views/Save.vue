<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import {
  ApiError,
  assemble,
  createBaseline,
  getAssertions,
  getCard,
  getClarifications,
  getDoc,
  listBaselines,
  type Baseline,
} from '../api'
import { baseTag, curName, curPath } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const hasCard = ref(false)
const ruleCnt = ref(0)
const waitCnt = ref(0)
const asrtCnt = ref(0)
const baselines = ref<Baseline[]>([])
const err = ref('')
const showDoc = ref(false)
const docText = ref('')
const note = ref('')
const regen = ref(false)

async function load() {
  ;[baselines.value, asrtCnt.value] = await Promise.all([listBaselines(), getAssertions().then(r => r.length)])
  waitCnt.value = (await getClarifications()).filter(c => c.st === 'wait').length
  if (!curPath.value) {
    hasCard.value = false
    ruleCnt.value = 0
    return
  }
  try {
    const card = await getCard(curPath.value)
    hasCard.value = true
    ruleCnt.value = card.rules.length
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) hasCard.value = false
    else throw e
  }
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
  }
})

// 树上切目标节点：跟随 curPath 刷新该节点定稿状态（画像有无/规则数）
watch(curPath, () => {
  load().catch(e => {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
  })
})

const canSave = computed(() => hasCard.value)

async function newBaseline() {
  try {
    const b = await createBaseline(`${curName.value} 并入基线`)
    baseTag.value = `基线 ${b.tag} · ${b.commit.slice(0, 7)}`
    await load()
    toast(`已并入基线 ${b.tag}（commit+tag）`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `存档失败：${e.message}` : '存档失败', 'warn')
  }
}

async function regenerate() {
  if (!curPath.value) { toast('先在左侧选中功能点'); return }
  regen.value = true
  try {
    await assemble(curPath.value, note.value)
    toast('终稿已按补充意见重新生成', 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `重生成失败：${e.message}` : '重生成失败', 'warn')
  } finally { regen.value = false }
}

async function openDoc() {
  try {
    docText.value = await getDoc()
    showDoc.value = true
  } catch (e) {
    toast(e instanceof ApiError ? `导出失败：${e.message}` : '导出失败', 'warn')
  }
}

function downloadDoc() {
  const blob = new Blob([docText.value], { type: 'text/markdown' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = '结构化需求规格.md'
  a.click()
  URL.revokeObjectURL(a.href)
  toast('已下载 .md', 'ok')
}
</script>

<template>
  <div>
    <div class="view-head">
      <h2>⑤ 定稿存档</h2>
      <span class="sub">补充意见重生成终稿，存入项目基线（git commit+tag）。</span>
    </div>

    <p v-if="err" class="err">{{ err }}</p>

    <div class="card-box">
      <div class="hd">补充意见重生成终稿 · {{ curName }}</div>
      <div class="bd">
        <textarea v-model="note" rows="2" placeholder="AI 不知道的口头约定、历史坑、业务约束——并入画像「补充说明」并影响规则" />
        <button class="btn" type="button" :disabled="regen" @click="regenerate">
          {{ regen ? 'AI 重新生成中…' : '重新生成终稿' }}</button>
      </div>
    </div>

    <div v-if="hasCard" class="card-box">
      <div class="hd">存档预览</div>
      <div class="bd">
        <div class="rule-row">
          <span class="badge b-green">规则 {{ ruleCnt }} 条</span>
          <span class="badge" :class="waitCnt ? 'b-amber' : 'b-green'">待确认 {{ waitCnt }} 项</span>
          <span class="badge b-blue">规则 {{ asrtCnt }} 条</span>
        </div>
        <div v-if="waitCnt" style="font-size: 12px; color: var(--warn); margin-top: 8px">
          还有 {{ waitCnt }} 项待确认——建议先在顶栏澄清池收口，否则带「?」进基线。
        </div>
        <div style="margin-top: 10px; display: flex; gap: 8px">
          <button class="btn" type="button" :disabled="!canSave" @click="newBaseline">并入基线（commit + tag）</button>
          <button class="btn-accent" type="button" @click="openDoc">预览结果文档</button>
        </div>
      </div>
    </div>
    <div v-else class="empty">{{ curPath ? '画像还没生成——先回 ③ 生成画像' : '先在左侧功能树选中整理目标节点' }}</div>

    <div class="card-box">
      <div class="hd">版本时间线</div>
      <div class="bd">
        <div v-if="baselines.length" class="tl">
          <div v-for="(b, i) in baselines" :key="b.tag" class="tl-item" :class="{ cur: i === baselines.length - 1 }">
            <h4>{{ b.tag }} <span v-if="i === baselines.length - 1" class="badge b-blue">当前</span></h4>
            <div class="meta">{{ b.commit }}</div>
          </div>
        </div>
        <div v-else style="color: var(--muted-fg)">还没有基线——某节点定稿存档后出现</div>
      </div>
    </div>

    <div v-if="showDoc" class="modal-bg" @click.self="showDoc = false">
      <div class="modal wide" role="dialog" aria-modal="true">
        <h3>最终结果文档 · 结构化需求规格（自动生成）</h3>
        <div class="q-export" style="max-height: 52vh; overflow: auto">{{ docText }}</div>
        <div class="foot">
          <button class="btn-ghost" type="button" @click="showDoc = false">关闭</button>
          <button class="btn" type="button" @click="downloadDoc">下载 .md</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
</style>
