<script setup lang="ts">
// 条目 tab：本节点规则行（R id / 文本 / 出处 / 置信度徽章 / 已核过绿标）+ 核验进度条 + 写操作——
// 核验（confirmRule 行内变绿）/ 待确认（行内展开表单，自定义问法 askRule）/ ✦ AI 辅助核验（verifyJob 轮询）。
import { computed, inject, ref } from 'vue'
import { ApiError, askRule, confirmRule, verifyJob, type Rule } from '../../api'
import { jobRunning, startJobPolling } from '../../jobs'
import { refreshWb } from '../../wb'

const props = defineProps<{ rules: Rule[] }>()
const emit = defineEmits<{ 'clar-changed': [] }>()
const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const CONF: Record<string, string> = { 实证: 'b-green', 文档: 'b-blue', 推测: 'b-amber', 待实证: 'b-red', 旧文档: 'b-gray' }

// 行内写操作本地覆盖（父列表不重拉）：树徽章联动统一走 refreshWb
const okLocal = ref(new Set<string>()) // 本地已核过
const askedLocal = ref(new Set<string>()) // 本地已转待确认
const isOk = (r: Rule) => r.verified || okLocal.value.has(r.id)
const isAsked = (r: Rule) => !!r.clar || askedLocal.value.has(r.id)

const okN = computed(() => props.rules.filter(isOk).length)
const pct = computed(() => (props.rules.length ? Math.round((okN.value / props.rules.length) * 100) : 0))
const pendN = computed(() => props.rules.length - okN.value)

function fail(e: unknown, prefix: string) {
  toast(e instanceof ApiError ? `${prefix}：${e.message}` : prefix, 'warn')
}

/** 人工核过：行内绿标 + 进度前进 + 树徽章刷新 */
async function onConfirm(r: Rule) {
  try {
    await confirmRule(r.id)
    okLocal.value.add(r.id)
    void refreshWb()
    toast(`${r.id} 已人工核过 ✓`, 'ok')
  } catch (e) {
    fail(e, '操作失败')
  }
}

// 待确认行内表单：预填建议问法，用户可改后投递
const askOpen = ref('')
const askText = ref('')
function openAsk(r: Rule) {
  askOpen.value = askOpen.value === r.id ? '' : r.id
  askText.value = `「${r.id}」的具体触发条件/兜底行为是什么？`
}
async function submitAsk(r: Rule) {
  try {
    await askRule(r.id, askText.value.trim())
    askedLocal.value.add(r.id)
    askOpen.value = ''
    void refreshWb()
    emit('clar-changed') // 顶栏待确认角标
    toast(`${r.id} → 已进澄清池（答案确认后自动核过）`, 'ok')
  } catch (e) {
    fail(e, '转澄清失败')
  }
}

/** AI 辅助核验（文档级）：只核文档/实证级未核验规则（推测级留给人工/转问人），进度轮询驱动 */
async function aiVerify() {
  try {
    const r = await verifyJob({ only_doc: true })
    startJobPolling(r.job_id, async (msg, cls) => {
      toast(msg, cls)
      await refreshWb()
    })
  } catch (e) {
    fail(e, '核验失败')
  }
}
</script>

<template>
  <div class="card">
    <h3>条目 · 核验 {{ okN }}/{{ rules.length }} <span class="badge b-gray">来自材料，逐条标出处</span>
      <span class="spacer" />
      <button v-if="pendN" class="btn-accent btn-sm" type="button" :disabled="jobRunning" @click="aiVerify">
        {{ jobRunning ? 'AI 核验中…' : '✦ AI 辅助核验（文档级）' }}</button>
    </h3>
    <div class="vprog"><span>核验进度</span><div class="bar"><i :style="{ width: pct + '%' }" /></div><b>{{ pct }}%</b></div>
    <template v-for="r in rules" :key="r.id">
      <div class="rrow">
        <span class="rid">{{ r.id }}</span>
        <span class="rtxt">{{ r.text }}<span class="rsrc">{{ r.src }}</span></span>
        <span class="acts">
          <span class="badge" :class="CONF[r.conf] ?? 'b-gray'">{{ r.conf }}</span>
          <span v-if="isOk(r)" class="badge b-green">已核过</span>
          <template v-else>
            <button class="btn-ghost btn-sm" type="button" title="我确认这条与实际一致" @click="onConfirm(r)">核验</button>
            <button v-if="!isAsked(r)" class="btn-ghost btn-sm" type="button" title="进澄清池，答案确认后自动核过" @click="openAsk(r)">待确认？</button>
            <span v-else class="badge b-blue" :title="`问#${r.clar ?? ''} 待回收答案`">已转待确认</span>
          </template>
        </span>
      </div>
      <div v-if="askOpen === r.id" class="askform">
        <textarea v-model="askText" rows="2" placeholder="想问什么就改什么——答案确认后这条自动核过" />
        <div class="askbtns">
          <button class="btn-accent btn-sm" type="button" @click="submitAsk(r)">投递到待确认</button>
          <button class="btn-ghost btn-sm" type="button" @click="askOpen = ''">收起</button>
        </div>
      </div>
    </template>
    <p v-if="!rules.length" class="none">本节点暂无条目</p>
  </div>
</template>

<style scoped>
.card { display: block; cursor: default; background: #fff; border: 1px solid var(--border2); border-radius: 10px; padding: 15px 18px; }
.card h3 { font-size: 14px; display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-bottom: 8px; }
.card h3 .spacer { flex: 1; }
.vprog { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 12px; color: var(--muted-fg); }
.vprog .bar { flex: 1; height: 6px; background: var(--muted); border-radius: 3px; overflow: hidden; }
.vprog .bar i { display: block; height: 100%; background: var(--ok); border-radius: 3px; transition: width .4s; }
.vprog b { color: var(--ok); }
.rrow { display: flex; align-items: flex-start; gap: 10px; padding: 8px 2px; border-top: 1px solid #f1f5f9; font-size: 12.5px; }
.rrow:first-of-type { border-top: none; }
.rrow .rid { font-family: var(--mono); font-size: 11.5px; color: var(--muted-fg); flex: none; padding-top: 1px; min-width: 26px; }
.rrow .rtxt { flex: 1; min-width: 0; }
.rrow .rsrc { display: block; font-size: 11px; color: var(--muted-fg); margin-top: 1px; }
.rrow .acts { display: flex; gap: 5px; flex: none; align-items: center; }
.askform { padding: 2px 2px 10px 36px; border-top: 1px dashed #f1f5f9; }
.askform textarea { width: 100%; font-family: inherit; font-size: 12.5px; padding: 7px 10px; border: 1px solid var(--border2); border-radius: 6px; resize: vertical; margin: 8px 0 6px; }
.askbtns { display: flex; gap: 6px; }
.none { color: var(--muted-fg); font-size: 12px; padding: 10px 0 2px; }
</style>
