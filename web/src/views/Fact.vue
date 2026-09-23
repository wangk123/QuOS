<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import {
  ApiError,
  extractEvidence,
  getAssertions,
  getConflicts,
  getEvidence,
  verifyAll,
  verifyOne,
  type Assertion,
  type Conflict,
  type EvidenceItem,
} from '../api'
import { curName } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<Assertion[]>([])
const conflicts = ref<Conflict[]>([])
const evidence = ref<EvidenceItem[]>([])
const err = ref('')
const aiLabel = ref('')
const verifyRecord = ref('') // 全量核验记录条

const confBadge: Record<string, [string, string]> = {
  实证: ['b-green', '代码实证'],
  文档: ['b-blue', '文档'],
  推测: ['b-amber', '推测 ⚠'],
  待实证: ['b-red', 'AI待实证'],
  旧文档: ['b-gray', '旧文档'],
}

async function load() {
  ;[items.value, conflicts.value, evidence.value] = await Promise.all([
    getAssertions(),
    getConflicts(),
    getEvidence(),
  ])
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
  }
})

const stat = {
  total: () => items.value.length,
  verified: () => items.value.filter(a => a.verified).length,
  unverified: () => items.value.filter(a => !a.verified).length,
  suspectCnt: () => items.value.filter(a => a.conf === '推测' || a.conf === '待实证').length,
}
const corrected = computed(() => items.value.filter(a => a.suspect))

function inConflict(a: Assertion) {
  return conflicts.value.some(c => c.st === 'open' && (c.a === a.id || c.b === a.id))
}
function voided(a: Assertion) {
  return conflicts.value.some(c => c.st === 'code' && a.id !== c.resolution && (c.a === a.id || c.b === a.id))
}

/** 提取池中全部未提取材料（顺序执行，AI 一次读一份） */
async function extractAll() {
  const pend = evidence.value.filter(e => e.state === 'pending')
  if (!pend.length) {
    toast('池中没有可提取的新材料')
    return
  }
  try {
    for (const ev of pend) {
      aiLabel.value = `AI 正在读《${ev.name}》提炼行为断言…`
      const r = await extractEvidence(ev.id)
      toast(`《${ev.name}》+${r.added} 条断言 · 出处已标注`, 'ok')
    }
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? `提取失败：${e.message}` : '提取失败', 'warn')
  } finally {
    aiLabel.value = ''
  }
}

async function checkAll() {
  aiLabel.value = `AI 全量核验：${items.value.length} 条断言逐条比对材料…`
  try {
    const r = await verifyAll()
    await load()
    const bad = r.results.filter(x => x && (x as any).corrected_text).length
    verifyRecord.value = `AI 逐条比对材料：${r.applied.length} 条全查${bad ? ` · ${bad} 条读错已修正（标黄待人工确认）` : ' · 全部一致 ✓'}`
    toast(bad ? `核验完成：${bad} 条 AI 读错已修正` : '核验完成：全部一致 ✓', bad ? 'warn' : 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `核验失败：${e.message}` : '核验失败', 'warn')
  } finally {
    aiLabel.value = ''
  }
}

async function checkOne(id: string) {
  aiLabel.value = `AI 单点核验 ${id}：比对材料…`
  try {
    await verifyOne(id)
    await load()
    toast(`${id} 已核验：与材料一致 ✓`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `核验失败：${e.message}` : '核验失败', 'warn')
  } finally {
    aiLabel.value = ''
  }
}
</script>

<template>
  <div>
    <div class="view-head">
      <h2>① 提事实 · {{ curName }}</h2>
      <span class="sub">AI 读材料，一句句写下「系统在干什么」，每句注明从哪看出来的。</span>
      <div class="spacer" style="flex: 1" />
      <button class="btn" type="button" @click="extractAll">提取池中相关材料</button>
      <button class="btn-accent" type="button" @click="checkAll">AI 全量核验</button>
    </div>

    <p v-if="err" class="err">{{ err }}</p>
    <div class="statbar">
      <div class="stat"><b>{{ stat.total() }}</b><span>断言</span></div>
      <div class="stat okc"><b>{{ stat.verified() }}</b><span>已核验 ✓</span></div>
      <div class="stat" :class="stat.unverified() ? 'warn' : 'okc'"><b>{{ stat.unverified() }}</b><span>未核验</span></div>
      <div class="stat"><b>{{ stat.suspectCnt() }}</b><span>推测/待实证 ⚠</span></div>
    </div>

    <div v-if="aiLabel" class="ai-run">
      <span class="spin" /><span>{{ aiLabel }}</span><div class="bar"><i /></div>
    </div>

    <div class="card-box">
      <div class="hd">
        断言表 · {{ curName }}
        <span class="sub" style="font-weight: 400">AI 全量核验 + 任意行单点「核」指定核验；AI 读错会当场标黄修正</span>
      </div>
      <table>
        <thead>
          <tr>
            <th style="width: 38px">#</th><th>断言（必须能判对错）</th><th style="width: 150px">出处</th>
            <th style="width: 88px">置信度</th><th style="width: 86px">状态</th><th style="width: 56px">核验</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in items" :key="a.id" :class="{ suspect: a.suspect }">
            <td><span class="src">{{ a.id }}</span></td>
            <td :class="{ strike: voided(a) }">{{ a.text }}</td>
            <td><span class="src">{{ a.src }}</span></td>
            <td><span class="badge" :class="(confBadge[a.conf] ?? confBadge['文档'])[0]">{{ (confBadge[a.conf] ?? confBadge['文档'])[1] }}</span></td>
            <td>
              <span v-if="voided(a)" class="badge b-gray">已作废</span>
              <span v-else-if="inConflict(a)" class="badge b-red">冲突</span>
              <span v-else-if="a.suspect" class="badge b-amber">已修正·待确认</span>
              <span v-else class="badge b-blue">在案</span>
            </td>
            <td>
              <span v-if="a.verified" class="badge b-green">✓ 核过</span>
              <button v-else class="btn-ghost btn-sm" type="button" @click="checkOne(a.id)">核</button>
            </td>
          </tr>
          <tr v-if="!items.length">
            <td colspan="6" style="color: var(--muted-fg); padding: 24px; text-align: center">还没有断言——点「提取池中相关材料」</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="verifyRecord" class="card-box">
      <div class="hd">全量核验记录</div>
      <div class="bd" style="font-size: 12.5px">
        <span class="badge b-green">{{ verifyRecord }}</span>
        <span v-if="corrected.length" style="color: var(--muted-fg); margin-left: 10px">可疑项标黄置顶待人工确认：{{ corrected.map(a => a.id).join('、') }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
</style>
