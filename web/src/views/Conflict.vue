<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { ApiError, getAssertions, getConflicts, resolveConflict, rescanConflicts, type Assertion, type Conflict } from '../api'
import { curName } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const conflicts = ref<Conflict[]>([])
const assertions = ref<Assertion[]>([])
const err = ref('')
const aiLabel = ref('')

const confColor: Record<string, string> = {
  实证: 'var(--primary)',
  文档: 'var(--muted-fg)',
  推测: 'var(--warn)',
  待实证: 'var(--destructive)',
  旧文档: 'var(--muted-fg)',
}

async function load() {
  ;[conflicts.value, assertions.value] = await Promise.all([getConflicts(), getAssertions()])
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
  }
})

const open = computed(() => conflicts.value.filter(c => c.st === 'open'))

function byId(id: string): Assertion {
  return (
    assertions.value.find(a => a.id === id) ?? { id, text: `（${id}）`, src: '', conf: '文档', st: 'open', verified: false, suspect: false }
  )
}

async function resolve(c: Conflict, side: 'a' | 'b') {
  try {
    const winner = side === 'a' ? c.a : c.b
    await resolveConflict(c.id, 'code', side)
    await load()
    toast(`${c.id} 已裁决：信 ${winner} · 对方作废`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `裁决失败：${e.message}` : '裁决失败', 'warn')
  }
}

async function toClar(c: Conflict) {
  try {
    await resolveConflict(c.id, 'clar')
    await load()
    toast(`${c.id} → 已进「问人」清单`)
  } catch (e) {
    toast(e instanceof ApiError ? `转问人失败：${e.message}` : '转问人失败', 'warn')
  }
}

/** AI 重扫：对当前断言全集跑矛盾检测 */
async function rescan() {
  aiLabel.value = `AI 重扫矛盾：${assertions.value.length} 条断言两两比对…`
  try {
    const items = await rescanConflicts()
    await load()
    toast(`扫描完成：矛盾 ${items.filter(c => c.st === 'open').length} 项待裁决`)
  } catch (e) {
    toast(e instanceof ApiError ? `重扫失败：${e.message}` : '重扫失败', 'warn')
  } finally {
    aiLabel.value = ''
  }
}
</script>

<template>
  <div>
    <div class="view-head">
      <h2>② 挑矛盾 · {{ curName }}</h2>
      <span class="sub">所有材料之间对不上的地方：代码 vs 文档 vs 口头——矛盾 = 需求没对齐的实锤。</span>
      <div class="spacer" style="flex: 1" />
      <button class="btn" type="button" :disabled="!assertions.length" @click="rescan">AI 重扫</button>
      <span class="badge" :class="open.length ? 'b-red' : 'b-green'">待裁决 {{ open.length }}</span>
    </div>

    <p v-if="err" class="err">{{ err }}</p>
    <div v-if="aiLabel" class="ai-run">
      <span class="spin" /><span>{{ aiLabel }}</span><div class="bar"><i /></div>
    </div>
    <div v-for="c in conflicts" :key="c.id" class="conflict" :class="{ resolved: c.st !== 'open' }">
      <div class="sides">
        <div class="side">
          <div class="who" :style="{ color: confColor[byId(c.a).conf] }">{{ byId(c.a).id }} · {{ byId(c.a).conf }}</div>
          <div>{{ byId(c.a).text }}</div>
          <div style="margin-top: 6px"><span class="src">{{ byId(c.a).src }}</span></div>
        </div>
        <div class="vs">VS</div>
        <div class="side">
          <div class="who" :style="{ color: confColor[byId(c.b).conf] }">{{ byId(c.b).id }} · {{ byId(c.b).conf }}</div>
          <div>{{ byId(c.b).text }}</div>
          <div style="margin-top: 6px"><span class="src">{{ byId(c.b).src }}</span></div>
        </div>
      </div>
      <div class="conflict-foot">
        <span class="q">{{ c.id }} · {{ c.q }}</span>
        <template v-if="c.st === 'open'">
          <button class="btn-ghost btn-sm" type="button" @click="resolve(c, 'a')">信 {{ c.a }}</button>
          <button class="btn-ghost btn-sm" type="button" @click="resolve(c, 'b')">信 {{ c.b }}</button>
          <button class="btn btn-sm" type="button" @click="toClar(c)">转问人</button>
        </template>
        <span v-else-if="c.st === 'clar'" class="badge b-amber">已转问人</span>
        <span v-else class="badge b-green">已裁决：信 {{ c.resolution }}</span>
      </div>
    </div>
    <div v-if="!conflicts.length" class="empty">
      {{ err ? '' : '没有矛盾——去 ① 提取更多材料后点「AI 重扫」或回 ③ 继续找空白' }}
    </div>

    <div class="warn-strip">
      <b>裁决规则</b>代码 vs 文档默认倾向代码；「代码与口头意图相反」可能是生产 bug，必须问人，不能自动裁决。
    </div>
  </div>
</template>

<style scoped>
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
</style>
