<script setup lang="ts">
import { inject, ref } from 'vue'
import { ApiError, addEvidenceFile, adoptClar, answerClar, answerClarOpen, ignoreClar, verifyClar, type Clarification } from '../api'

// 单题卡：待问（choice/open/AI 代答）+ 已答折叠行；API 调用在本体完成，成功后 emit 通知父层重拉。
const props = defineProps<{ c: Clarification }>()
const emit = defineEmits<{
  answered: []
  adopted: []
  ignored: []
  verified: []
}>()

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const pick = ref<number>()
const draft = ref('')
const expanded = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const files = ref<File[]>([])
const MAX_SIZE = 10 * 1024 * 1024

const stBadge: Record<string, [string, string]> = {
  wait: ['b-amber', '待问'],
  answered: ['b-blue', '已答·待实证'],
  verified: ['b-green', '已实证'],
}

// AI 置信度徽章：high/med/low → 绿/蓝/琥珀，未知值灰底原样
const confBadge = (conf: string): [string, string] =>
  ({ high: ['b-green', '高置信'], med: ['b-blue', '中置信'], low: ['b-amber', '低置信'] } as Record<string, [string, string]>)[conf] ??
  ['b-gray', conf]

// 卡头来源徽章：R=规则提取（无依据转问人）C=冲突裁决 G=查漏补缺；无 ref 或未知前缀不显示
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

async function answerChoice() {
  if (pick.value === undefined) return
  try {
    await answerClar(props.c.no, pick.value)
    emit('answered')
    toast(`${props.c.no} 已记录（口头答案=推测级）`)
  } catch (e) {
    failToast(e, '记录')
  }
}

// open 题附件：先在本地 chip 暂存，提交时逐份入池（source=clar）收 evIds 随文本一起提交
function onPickFile(e: Event) {
  const el = e.target as HTMLInputElement
  const picked = [...(el.files ?? [])].filter(f => {
    if (f.size > MAX_SIZE) {
      toast(`文件超过 10MB：${f.name}`, 'warn')
      return false
    }
    return true
  })
  files.value.push(...picked)
  el.value = '' // 清空以便重复选同名文件
}

async function answerOpen() {
  const text = draft.value.trim()
  if (!text) return
  try {
    const evIds: string[] = []
    for (const f of files.value) evIds.push((await addEvidenceFile(f, 'clar')).id)
    await answerClarOpen(props.c.no, text, evIds)
    draft.value = ''
    files.value = []
    emit('answered')
    toast(`${props.c.no} 材料已记录（材料答案=推测级）`)
  } catch (e) {
    failToast(e, '提交')
  }
}

async function adopt() {
  try {
    await adoptClar(props.c.no)
    emit('adopted')
    toast(`${props.c.no} 已采纳 AI 代答（推测级，待实证）`)
  } catch (e) {
    failToast(e, '采纳')
  }
}

async function ignore() {
  try {
    await ignoreClar(props.c.no)
    emit('ignored')
    toast(`已忽略 ${props.c.no} 的 AI 代答`)
  } catch (e) {
    failToast(e, '忽略')
  }
}

async function verify() {
  try {
    await verifyClar(props.c.no)
    emit('verified')
    toast(`${props.c.no} 已标记确认${props.c.ref ? ' · 关联规则已同步核过' : ''}`, 'ok')
  } catch (e) {
    failToast(e, '标记')
  }
}
</script>

<template>
  <div class="q-card" :class="{ done: c.st !== 'wait' }">
    <template v-if="c.st === 'wait'">
      <div class="qc-hd">
        <span class="src">{{ c.no }}</span>
        <span class="badge" :class="c.kind === 'open' ? 'b-open' : 'b-gray'">
          {{ c.kind === 'open' ? '补材料' : '选择题' }}
        </span>
        <span v-if="refBadge(c.ref)" class="badge b-gray">{{ refBadge(c.ref) }}</span>
        <span v-else-if="c.ref" class="qc-from">关联 {{ c.ref }}</span>
        <span class="badge" :class="(stBadge[c.st] ?? stBadge['wait'])[0]">{{ (stBadge[c.st] ?? stBadge['wait'])[1] }}</span>
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
        <p class="qc-ai-line"><b>来源</b><span>{{ c.ai.ev_ids.length }} 份材料</span></p>
        <div class="qc-foot">
          <span class="qc-hint">AI 代答=推测级，采纳后仍需实证</span>
          <button class="btn-ghost btn-sm" type="button" @click="ignore">忽略</button>
          <button class="btn btn-sm" type="button" @click="adopt">采纳</button>
        </div>
      </div>

      <template v-else-if="c.kind === 'choice'">
        <div class="qc-opts" role="radiogroup" :aria-label="`问题 ${c.no} 选项`">
          <button
            v-for="(o, i) in c.opts"
            :key="i"
            class="opt"
            :class="{ on: pick === i }"
            type="button"
            role="radio"
            :aria-checked="pick === i"
            @click="pick = i"
          >
            <b>{{ String.fromCharCode(65 + i) }}. </b>{{ o }}
          </button>
        </div>
        <div class="qc-foot">
          <span class="qc-hint">点选项后记录，答案=推测级，需实证</span>
          <button class="btn btn-sm" type="button" :disabled="pick === undefined" @click="answerChoice">记录答案</button>
        </div>
      </template>

      <template v-else>
        <textarea
          v-model="draft"
          class="qc-input"
          :aria-label="`问题 ${c.no} 补充材料`"
          rows="4"
          placeholder="输入补充说明，或直接粘贴制度文件 / 会议记录原文……"
        />
        <div v-if="files.length" class="qc-files">
          <span v-for="(f, i) in files" :key="`${f.name}-${i}`" class="qc-chip">
            {{ f.name }}
            <button class="qc-x" type="button" :aria-label="`移除附件 ${f.name}`" @click="files.splice(i, 1)">✕</button>
          </span>
        </div>
        <div class="qc-foot">
          <span class="qc-hint">材料答案=推测级，需实证</span>
          <button class="btn-ghost btn-sm" type="button" @click="fileInput?.click()">+附件</button>
          <button class="btn btn-sm" type="button" :disabled="!draft.trim()" @click="answerOpen">提交补充</button>
        </div>
        <input
          ref="fileInput"
          type="file"
          multiple
          hidden
          :aria-label="`问题 ${c.no} 补充材料附件`"
          @change="onPickFile"
        />
      </template>
    </template>

    <template v-else>
      <button class="qc-row" type="button" @click="expanded = !expanded">
        <span class="tri" :class="{ open: expanded }">▸</span>
        <span class="src">{{ c.no }}</span>
        <span class="qc-row-q">{{ c.q }}</span>
        <span class="qc-row-a">答：{{ c.answer }}</span>
        <span class="badge" :class="(stBadge[c.st] ?? stBadge['wait'])[0]">{{ (stBadge[c.st] ?? stBadge['wait'])[1] }}</span>
      </button>
      <div v-if="expanded" class="qc-detail">
        <p class="qc-q">{{ c.q }}</p>
        <div class="qc-ans">
          <span class="badge" :class="c.kind === 'open' ? 'b-open' : 'b-gray'">
            {{ c.kind === 'open' ? '补材料' : '选择题' }}
          </span>
          <div class="qc-ans-text">{{ c.answer }}</div>
        </div>
        <div v-if="c.st === 'answered'" class="qc-foot">
          <span class="qc-hint">口头/材料答案仍是推测级，拿到书面依据后标记</span>
          <button class="btn-ok btn-sm" type="button" @click="verify">标记已确认</button>
        </div>
        <p v-else-if="c.ref" class="qc-hint">关联规则 {{ c.ref }} 已同步核过</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.q-card { background: #fff; border: 1px solid var(--border2); border-radius: var(--radius); padding: 12px 14px; }
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
  font-family: inherit; font-size: 12.5px; line-height: 1.6; resize: vertical; min-height: 84px; }
.qc-input:focus { border-color: var(--secondary); }
.qc-files { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.qc-chip { display: inline-flex; align-items: center; gap: 5px; max-width: 100%; background: var(--muted);
  border-radius: 999px; padding: 3px 10px; font-size: 11.5px; color: var(--fg); }
.qc-chip .qc-x { background: none; border: none; color: var(--muted-fg); font-size: 11px; line-height: 1;
  padding: 0; cursor: pointer; }
.qc-chip .qc-x:hover { color: var(--destructive); }
.qc-foot { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.qc-foot .btn, .qc-foot .btn-ok, .qc-foot .btn-ghost { margin-left: auto; }
.qc-hint { font-size: 11.5px; color: var(--muted-fg); }

.qc-ai { border: 1px solid var(--blue-bg); background: #f8faff; border-radius: 8px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 6px; }
.qc-ai-hd { display: flex; align-items: center; gap: 8px; }
.qc-ai-tag { font-size: 11.5px; font-weight: 600; color: var(--primary); }
.qc-ai-line { display: flex; gap: 8px; font-size: 12.5px; line-height: 1.6; margin: 0; }
.qc-ai-line b { flex-shrink: 0; font-size: 11.5px; color: var(--muted-fg); font-weight: 600; padding-top: 1px; }
.qc-ai-line span { min-width: 0; word-break: break-word; }
.qc-unv { font-style: normal; font-size: 11px; color: var(--muted-fg); margin-left: 6px; }

.qc-row { display: flex; align-items: center; gap: 8px; width: 100%; background: none; text-align: left;
  padding: 4px 2px; border-radius: 6px; font-size: 12.5px; min-width: 0; }
.qc-row:hover { background: var(--muted); }
.tri { color: var(--muted-fg); flex-shrink: 0; transition: transform .15s; display: inline-block; }
.tri.open { transform: rotate(90deg); }
.qc-row-q { flex: 1; min-width: 60px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--fg); }
.qc-row-a { flex-shrink: 1; max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--muted-fg); font-size: 12px; }
.qc-detail { border-top: 1px dashed var(--border); margin-top: 8px; padding-top: 10px; }
.qc-ans { display: flex; gap: 8px; align-items: flex-start; }
.qc-ans-text { font-size: 12.5px; line-height: 1.6; background: var(--muted); border-radius: 6px; padding: 8px 10px; white-space: pre-wrap; }

.b-open { background: #ffedd5; color: #c2410c; }
</style>
