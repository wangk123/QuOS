<script setup lang="ts">
// 待确认弹窗（T13）：分段（等待/已答复）/ 记下答复（口头/材料佐证）/ AI 代答卡（采纳/忽略）。
// 弹窗三段结构同 EvPoolModal（.mask/.modal 全局样式）；卡片流样式沿旧澄清抽屉（T19 已删）。
import { computed, inject, ref, watch } from 'vue'
import {
  ApiError, adoptClar, answerClar, answerClarOpen, getClarifications, ignoreClar,
  type Clarification, type EvidenceItem,
} from '../api'

const props = defineProps<{ open: boolean; evidence: EvidenceItem[] }>()
const emit = defineEmits<{
  close: []
  changed: []
}>()

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<Clarification[]>([])
const tab = ref<'wait' | 'done'>('wait')
const err = ref('')

// 每题作答草稿（按 no 键控）：选项/文本/答复来源/佐证材料
const pick = ref<Record<number, number>>({})
const draft = ref<Record<number, string>>({})
const src = ref<Record<number, 'oral' | 'material'>>({})
const evPick = ref<Record<number, string[]>>({})

// 旧数据无 kind：按 opts 兜底（有选项=选择题，无选项=开放题）
async function load() {
  items.value = (await getClarifications()).map(c => {
    const k = c.kind ?? (c.opts.length ? 'choice' : 'open')
    draft.value[c.no] ??= ''
    src.value[c.no] ??= 'oral'
    evPick.value[c.no] ??= []
    return { ...c, kind: k }
  })
}

// 弹窗仅在打开时拉取；immediate 兼容首挂即 open 的场景
watch(
  () => props.open,
  v => {
    if (!v) return
    err.value = ''
    load().catch(e => {
      err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
    })
  },
  { immediate: true },
)

const waiting = computed(() => items.value.filter(c => c.st === 'wait'))
const done = computed(() => items.value.filter(c => c.st !== 'wait'))
const shown = computed(() => (tab.value === 'wait' ? waiting.value : done.value))
const aiCount = computed(() => waiting.value.filter(c => c.ai).length)

// ai.ev_ids 反查材料名（池中无此 id 时回退显示 id）
const evName = (id: string) => props.evidence.find(e => e.id === id)?.name ?? id

const stBadge: Record<string, [string, string]> = {
  wait: ['b-amber', '待确认'],
  answered: ['b-blue', '已答复'],
  verified: ['b-green', '已实证'],
}

// AI 置信度徽章：high/med/low → 绿/蓝/琥珀，未知值灰底原样
const confBadge = (conf: string): [string, string] =>
  ({ high: ['b-green', '高置信'], med: ['b-blue', '中置信'], low: ['b-amber', '低置信'] } as Record<string, [string, string]>)[conf] ??
  ['b-gray', conf]

// 卡头来源徽章：R=规则提取（无依据转问人）C=冲突裁决 G=查漏补缺
function refBadge(ref: string | null): string | null {
  if (!ref) return null
  if (ref.startsWith('R')) return `① 规则提取 ${ref}`
  if (ref.startsWith('C')) return `② 冲突裁决 ${ref}`
  if (ref.startsWith('G')) return `④ 查漏补缺 ${ref}`
  return null
}

function failToast(e: unknown, what: string) {
  toast(e instanceof ApiError ? `${what}失败：${e.message}` : `${what}失败`, 'warn')
}

// 单题落定（记答复/采纳/忽略）→ 重拉列表 + 通知外层（App 刷角标与工作台树徽章）
async function reload() {
  await load().catch(() => {}) // 重拉失败保持现状，不打断交互
  emit('changed')
}

// choice：点选项记答复（口头答案=推测级）
async function answerChoice(c: Clarification) {
  const idx = pick.value[c.no]
  if (idx === undefined) return
  try {
    await answerClar(c.no, idx)
    toast(`${c.no} 已记录（口头答案=推测级）`)
    await reload()
  } catch (e) {
    failToast(e, '记录')
  }
}

// open：文本 + 来源（口头确认=纯文本 / 材料佐证=关联池中材料）
async function answerOpen(c: Clarification) {
  const text = draft.value[c.no]?.trim()
  if (!text) return
  const evIds = src.value[c.no] === 'material' ? evPick.value[c.no] ?? [] : []
  try {
    await answerClarOpen(c.no, text, evIds)
    toast(`${c.no} 已记录${evIds.length ? '（材料佐证=推测级）' : '（口头答案=推测级）'}`)
    await reload()
  } catch (e) {
    failToast(e, '记录')
  }
}

// 采纳 AI 代答：后端联动核过 ref 指向的规则
async function adopt(c: Clarification) {
  try {
    await adoptClar(c.no)
    toast(`已采纳 ${c.no} AI 代答${c.ref ? `，关联条目 ${c.ref} 已自动核过` : ''}`, 'ok')
    await reload()
  } catch (e) {
    failToast(e, '采纳')
  }
}

// 忽略 AI 代答：ai 清空、题回等待段人工记答复
async function ignore(c: Clarification) {
  try {
    await ignoreClar(c.no)
    toast(`已忽略 ${c.no} 的 AI 代答`)
    await reload()
  } catch (e) {
    failToast(e, '忽略')
  }
}
</script>

<template>
  <div class="mask" :class="{ open }" @click.self="$emit('close')">
    <div class="modal wide clar" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>待确认 <span class="badge b-gray">{{ items.length }} 项</span></h3>
        <div class="msub">攒一批一次问清；答复落定后关联条目自动核过</div>
        <button class="x" type="button" aria-label="关闭" @click="$emit('close')">✕</button>
      </div>
      <div class="modal-body">
        <p v-if="err" class="err">{{ err }}</p>
        <div class="seg">
          <button
            v-for="t in ([['wait', `等待 ${waiting.length}`], ['done', `已答复 ${done.length}`]] as const)"
            :key="t[0]"
            class="tab"
            :class="{ on: tab === t[0] }"
            type="button"
            @click="tab = t[0]"
          >{{ t[1] }}</button>
        </div>

        <div v-if="tab === 'wait' && aiCount" class="ai-strip">
          ✦ AI 从材料找到 {{ aiCount }} 个可能答案，逐条采纳或忽略
        </div>

        <div v-for="c in shown" :key="c.no" class="q-card" :class="{ done: tab === 'done' }">
          <template v-if="c.st === 'wait'">
            <div class="qc-hd">
              <span class="src">{{ c.no }}</span>
              <span class="badge" :class="c.kind === 'open' ? 'b-open' : 'b-gray'">
                {{ c.kind === 'open' ? '补材料' : '选择题' }}
              </span>
              <span v-if="refBadge(c.ref)" class="badge b-gray">{{ refBadge(c.ref) }}</span>
            </div>
            <p class="qc-q">{{ c.q }}</p>

            <div v-if="c.ai" class="qc-ai" :aria-label="`问题 ${c.no} AI 代答`">
              <div class="qc-ai-hd">
                <span class="qc-ai-tag">AI 代答（待采纳）</span>
                <span class="badge" :class="confBadge(c.ai.conf)[0]">{{ confBadge(c.ai.conf)[1] }}</span>
              </div>
              <p class="qc-ai-line"><b>答案</b><span>{{ c.ai.answer }}</span></p>
              <p class="qc-ai-line">
                <b>摘录</b>
                <span>“{{ c.ai.quote }}”<i v-if="!c.ai.quote_ok" class="qc-unv">摘录未校验</i></span>
              </p>
              <p class="qc-ai-line"><b>来源</b><span>{{ c.ai.ev_ids.map(evName).join('、') || '—' }}</span></p>
              <div class="qc-foot">
                <span class="qc-hint">采纳后关联条目自动核过</span>
                <button class="btn-ghost btn-sm" type="button" :aria-label="`问题 ${c.no} 忽略`" @click="ignore(c)">忽略</button>
                <button class="btn btn-sm" type="button" :aria-label="`问题 ${c.no} 采纳`" @click="adopt(c)">采纳</button>
              </div>
            </div>

            <div v-else-if="c.kind === 'choice'" class="qc-opts" role="radiogroup" :aria-label="`问题 ${c.no} 选项`">
              <button
                v-for="(o, i) in c.opts"
                :key="i"
                class="opt"
                :class="{ on: pick[c.no] === i }"
                type="button"
                role="radio"
                :aria-checked="pick[c.no] === i"
                @click="pick[c.no] = i"
              >
                <b>{{ String.fromCharCode(65 + i) }}. </b>{{ o }}
              </button>
              <div class="qc-foot">
                <span class="qc-hint">点选项后记下答复，口头答案=推测级</span>
                <button class="btn btn-sm" type="button" :aria-label="`问题 ${c.no} 提交答复`" :disabled="pick[c.no] === undefined" @click="answerChoice(c)">记下答复</button>
              </div>
            </div>

            <div v-else class="ans-form">
              <textarea
                v-model="draft[c.no]"
                class="qc-input"
                :aria-label="`问题 ${c.no} 记下答复`"
                rows="3"
                placeholder="记下对方的答复原文……"
              />
              <div class="src-row" role="radiogroup" :aria-label="`问题 ${c.no} 答复来源`">
                <label><input v-model="src[c.no]" type="radio" value="oral" />口头确认</label>
                <label><input v-model="src[c.no]" type="radio" value="material" />材料佐证</label>
              </div>
              <select
                v-if="src[c.no] === 'material'"
                v-model="evPick[c.no]"
                class="qc-select"
                :aria-label="`问题 ${c.no} 佐证材料`"
                multiple
              >
                <option v-for="e in evidence" :key="e.id" :value="e.id">{{ e.name }}</option>
              </select>
              <div class="qc-foot">
                <span class="qc-hint">答复=推测级，拿到书面依据后再实证</span>
                <button class="btn btn-sm" type="button" :aria-label="`问题 ${c.no} 提交答复`" :disabled="!draft[c.no]?.trim()" @click="answerOpen(c)">记下答复</button>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="qc-hd">
              <span class="src">{{ c.no }}</span>
              <span class="badge" :class="(stBadge[c.st] ?? ['b-gray', c.st])[0]">{{ (stBadge[c.st] ?? ['b-gray', c.st])[1] }}</span>
              <span v-if="c.ref" class="qc-from">关联 {{ c.ref }}</span>
            </div>
            <p class="qc-q">{{ c.q }}</p>
            <div class="qc-ans">答：{{ c.answer }}</div>
            <p v-if="c.ref" class="qc-link">答复落定，关联条目 {{ c.ref }} 已自动核过</p>
          </template>
        </div>

        <div v-if="!shown.length" class="empty">
          {{ tab === 'wait' ? '没有待确认项——②冲突、④缺口、①无依据规则可转到这里' : '暂无已答复记录' }}
        </div>
      </div>
      <div class="modal-foot">
        <span class="fnote">AI 代答=推测级，采纳后仍需实证；忽略后代答回到人工记答复</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
.seg { display: flex; align-items: center; gap: 6px; padding-bottom: 10px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.tab { background: #fff; border: 1px solid var(--border2); color: var(--muted-fg); padding: 5px 12px; border-radius: 999px; font-size: 12px; }
.tab.on { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; }
.ai-strip { background: var(--blue-bg); color: var(--primary); border-radius: 8px; padding: 8px 12px;
  font-size: 12.5px; font-weight: 600; margin-bottom: 10px; }

.q-card { background: #fff; border: 1px solid var(--border2); border-radius: var(--radius); padding: 12px 14px; margin-bottom: 10px; }
.q-card.done { background: #fafbfd; }
.qc-hd { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.qc-from { font-size: 11px; color: var(--muted-fg); margin-left: auto; }
.qc-q { font-size: 13px; line-height: 1.65; margin-bottom: 10px; }
.qc-opts { display: flex; flex-direction: column; gap: 6px; }
.opt { display: flex; align-items: baseline; gap: 8px; text-align: left; background: #fff;
  border: 1px solid var(--border2); border-radius: 8px; padding: 8px 12px; font-size: 12.5px; line-height: 1.5;
  color: var(--fg); transition: border-color .15s, background .15s; }
.opt:hover { border-color: var(--secondary); background: #f8faff; }
.opt.on { border-color: var(--primary); background: var(--blue-bg); }
.opt b { flex-shrink: 0; font-family: var(--mono); font-size: 12px; color: var(--muted-fg); }
.opt.on b { color: var(--primary); }
.qc-input { width: 100%; border: 1px solid var(--border2); border-radius: 8px; padding: 9px 11px;
  font-family: inherit; font-size: 12.5px; line-height: 1.6; resize: vertical; min-height: 68px; }
.qc-input:focus { border-color: var(--secondary); }
.src-row { display: flex; gap: 14px; margin-top: 8px; font-size: 12.5px; }
.src-row label { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; color: var(--fg); }
.qc-select { width: 100%; margin-top: 8px; border: 1px solid var(--border2); border-radius: 8px;
  padding: 6px 9px; font-size: 12.5px; min-height: 60px; }
.qc-foot { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.qc-foot .btn, .qc-foot .btn-ghost { margin-left: auto; }
.qc-hint { font-size: 11.5px; color: var(--muted-fg); }
.qc-ans { font-size: 12.5px; line-height: 1.6; background: var(--muted); border-radius: 6px; padding: 8px 10px; white-space: pre-wrap; }
.qc-link { font-size: 11.5px; color: var(--muted-fg); margin: 8px 0 0; }
.empty { padding: 40px; text-align: center; color: var(--muted-fg); border: 1px dashed var(--border2); border-radius: var(--radius); }

.qc-ai { border: 1px solid var(--blue-bg); background: #f8faff; border-radius: 8px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 6px; }
.qc-ai-hd { display: flex; align-items: center; gap: 8px; }
.qc-ai-tag { font-size: 11.5px; font-weight: 600; color: var(--primary); }
.qc-ai-line { display: flex; gap: 8px; font-size: 12.5px; line-height: 1.6; margin: 0; }
.qc-ai-line b { flex-shrink: 0; font-size: 11.5px; color: var(--muted-fg); font-weight: 600; padding-top: 1px; }
.qc-ai-line span { min-width: 0; word-break: break-word; }
.qc-unv { font-style: normal; font-size: 11px; color: var(--muted-fg); margin-left: 6px; }

.b-open { background: #ffedd5; color: #c2410c; }
</style>
