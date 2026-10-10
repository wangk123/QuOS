<script setup lang="ts">
// 规则 tab（条目+存疑合并）：一组状态 chips（全部/核验通过/待处理）+ 混合流。
// 二分恒等：全部 = 核验通过 + 待处理；待处理 = open 冲突 + open 缺口 + 待核规则；
// 处置完即人工确认过 → 归入核验通过（灰行留痕），无第三分类。默认排序：待处理置顶。
import { computed, inject, ref } from 'vue'
import { ApiError, confirmRule, disposeGap, resolveConflict, verifyJob,
         type Conflict, type Gap, type Rule } from '../../api'
import { jobRunning, startJobPolling } from '../../jobs'
import { refreshWb } from '../../wb'

const props = defineProps<{ rules: Rule[]; conflicts: Conflict[]; gaps: Gap[]; allRules: Rule[] }>()
const emit = defineEmits<{ 'clar-changed': [] }>()
const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const CONF: Record<string, string> = { 实证: 'b-green', 文档: 'b-blue', 推测: 'b-amber', 待实证: 'b-red', 旧文档: 'b-gray' }

// ---- 写操作本地覆盖（父列表不重拉）：树徽章联动统一走 refreshWb ----
const okLocal = ref(new Set<string>())
const cOver = ref(new Map<string, Conflict>())
const gOver = ref(new Map<string, Gap>())

const isOk = (r: Rule) => r.verified || okLocal.value.has(r.id)
const confList = computed(() => props.conflicts.map(c => cOver.value.get(c.id) ?? c))
const gapList = computed(() => props.gaps.map(g => gOver.value.get(g.id) ?? g))

// ---- 状态 chips（单组单选）：全部 = 核验通过 + 待处理，计数恒等 ----
const filter = ref<'all' | 'ok' | 'pend'>('all')
const openConfs = computed(() => confList.value.filter(c => c.st === 'open'))
const openGaps = computed(() => gapList.value.filter(g => g.st === 'open'))
const pendRules = computed(() => props.rules.filter(r => !isOk(r)))
const okRules = computed(() => props.rules.filter(isOk))
const doneConfs = computed(() => confList.value.filter(c => c.st !== 'open'))
const doneGaps = computed(() => gapList.value.filter(g => g.st !== 'open'))
const pendN = computed(() => openConfs.value.length + openGaps.value.length + pendRules.value.length)
const okN2 = computed(() => okRules.value.length + doneConfs.value.length + doneGaps.value.length)
const allN = computed(() => props.rules.length + props.conflicts.length + props.gaps.length)
const pct = computed(() => (allN.value ? Math.round((okN2.value / allN.value) * 100) : 0))

function fail(e: unknown, prefix: string) {
  toast(e instanceof ApiError ? `${prefix}：${e.message}` : prefix, 'warn')
}

// ---- 规则行操作（核验/待确认/AI 辅助核验）----
async function onConfirm(r: Rule) {
  try {
    await confirmRule(r.id)
    okLocal.value.add(r.id)
    void refreshWb()
    toast(`${r.id} 已人工核过 ✓`, 'ok')
  } catch (e) { fail(e, '操作失败') }
}

async function aiVerify() {
  try {
    const r = await verifyJob({ only_doc: true })
    startJobPolling(r.job_id, async (msg, cls) => {
      toast(msg, cls)
      await refreshWb()
    })
  } catch (e) { fail(e, '核验失败') }
}

// ---- 冲突裁决 / 缺口处置 ----
const byId = computed(() => new Map(props.allRules.map(r => [r.id, r])))
function side(id: string) {
  const r = byId.value.get(id)
  return { src: r?.src ?? id, text: r?.text ?? '（规则已不存在）' }
}

const LETTERS = ['A', 'B', 'C', 'D', 'E', 'F']
async function resolve(c: Conflict, action: 'code' | 'manual', side?: number, text?: string) {
  try {
    const updated = await resolveConflict(c.id, action, side, text)
    cOver.value.set(c.id, updated)
    void refreshWb()
    toast(action === 'manual' ? `${c.id} 已按「其他」落实证规则` : `${c.id} 已裁定（信${LETTERS[side ?? 0]}）`, 'ok')
  } catch (e) { fail(e, '裁决失败') }
}

// 「其他」手输：默认收起，点开输入实际行为
const manualOpen = ref('')
const manualText = ref('')

// 冲突卡折叠（默认收起一行，点开看各方说法与裁决）
const openConf = ref(new Set<string>())
function toggleConf(id: string) {
  openConf.value.has(id) ? openConf.value.delete(id) : openConf.value.add(id)
}

async function dispose(g: Gap) {
  try {
    const updated = await disposeGap(g.id)
    gOver.value.set(g.id, updated)
    void refreshWb()
    toast('已按「设计如此」记录', 'ok')
  } catch (e) { fail(e, '处置失败') }
}
</script>

<template>
  <div class="card">
    <h3>规则 · {{ allN }} 条
      <span class="badge b-gray">要么核验通过、要么待处理——没有第三种</span>
      <span class="spacer" />
      <button v-if="pendRules.length" class="btn-accent btn-sm" type="button" :disabled="jobRunning" @click="aiVerify">
        {{ jobRunning ? 'AI 核验中…' : '✦ AI 辅助核验（文档级）' }}</button>
    </h3>
    <div class="chips">
      <button v-for="o in ([['all', `全部 ${allN}`], ['pend', `⚠ 待处理 ${pendN}`], ['ok', `✅ 核验通过 ${okN2}`]] as const)"
              :key="o[0]" class="chip" :class="{ on: filter === o[0], warn: o[0] === 'pend' && filter === 'pend' }" type="button"
              @click="filter = o[0]">{{ o[1] }}</button>
      <span class="pct">{{ pct }}% 已确认</span>
    </div>

    <!-- 待处理区（全部/待处理 显示）：冲突卡 → 缺口卡 → 待核规则行 -->
    <template v-if="filter !== 'ok'">
      <div v-for="c in openConfs" :key="c.id" class="confbox">
        <div class="confhead" @click="toggleConf(c.id)">
          <span class="ctag">⚠</span>
          <span class="ctitle">{{ c.id }} · {{ c.q }}</span>
          <span class="badge b-red">{{ c.parties.length }} 方说法</span>
          <span class="chev">{{ openConf.has(c.id) ? '▾' : '▸' }}</span>
        </div>
        <template v-if="openConf.has(c.id)">
          <div class="confcard">
            <div v-for="(p, i) in c.parties" :key="p" class="confside" :class="i % 2 ? 'b' : 'a'">
              <div class="who">{{ LETTERS[i] }} · {{ side(p).src }}</div>{{ side(p).text }}
            </div>
          </div>
          <div class="cbtns">
            <button v-for="(p, i) in c.parties" :key="p" class="btn-ghost btn-sm" type="button"
                    :title="`以 ${LETTERS[i]} 侧为准，其余作废`" @click="resolve(c, 'code', i)">信{{ LETTERS[i] }}</button>
            <button class="btn-accent btn-sm" type="button" title="实际行为与各方都不同——手输后落实证规则，各方作废"
                    @click="manualOpen = manualOpen === c.id ? '' : c.id">其他…</button>
          </div>
          <div v-if="manualOpen === c.id" class="askform">
            <textarea v-model="manualText" rows="2" placeholder="实际行为是什么就写什么——将生成一条人工确认的实证规则，冲突各方全部作废" />
            <div class="askbtns">
              <button class="btn-accent btn-sm" type="button" @click="resolve(c, 'manual', undefined, manualText); manualOpen = ''; manualText = ''">落实证规则</button>
              <button class="btn-ghost btn-sm" type="button" @click="manualOpen = ''">收起</button>
            </div>
          </div>
        </template>
      </div>
      <div v-for="g in openGaps" :key="g.id" class="rrow gap">
        <span class="gtag">△ 缺口</span>
        <span class="rtxt">{{ g.text }}<span class="rsrc">维度：{{ g.dim }} · 材料没说清</span></span>
        <span class="acts">
          <button class="btn-ghost btn-sm" type="button" title="确实不用说明，记录在案" @click="dispose(g)">设计如此</button>
        </span>
      </div>
      <template v-for="r in pendRules" :key="r.id">
        <div class="rrow">
          <span class="rid">{{ r.id }}</span>
          <span class="rtxt">{{ r.text }}<span class="rsrc">{{ r.src }}</span></span>
          <span class="acts">
            <span class="badge" :class="CONF[r.conf] ?? 'b-gray'">{{ r.conf }}</span>
            <button class="btn-ghost btn-sm" type="button" title="我确认这条与实际一致" @click="onConfirm(r)">核验</button>
          </span>
        </div>
      </template>
    </template>

    <!-- 核验通过区（全部/核验通过 显示）：已处置留痕灰行 + 已核规则行 -->
    <template v-if="filter !== 'pend'">
      <div v-for="c in doneConfs" :key="c.id" class="rrow done">
        <span class="rid">✓</span>
        <span class="rtxt">{{ c.q }}<span class="rsrc">冲突已裁决 · {{ c.resolution === 'manual' ? '其他：' + (c.manual_text ?? '') : `信 ${c.resolution}` }}</span></span>
      </div>
      <div v-for="g in doneGaps" :key="g.id" class="rrow done">
        <span class="rid">✓</span>
        <span class="rtxt">{{ g.text }}<span class="rsrc">缺口已处置 · {{ g.st === 'answered' ? '材料已补 ✓' : '设计如此' }}</span></span>
      </div>
      <div v-for="r in okRules" :key="r.id" class="rrow">
        <span class="rid">{{ r.id }}</span>
        <span class="rtxt">{{ r.text }}<span class="rsrc">{{ r.src }}</span></span>
        <span class="acts">
          <span class="badge" :class="CONF[r.conf] ?? 'b-gray'">{{ r.conf }}</span>
          <span class="badge b-green">已核过</span>
        </span>
      </div>
    </template>
    <p v-if="!allN" class="none">本节点暂无规则与疑点</p>
    <p v-if="allN && ((filter === 'pend' && !pendN) || (filter === 'ok' && !okN2))" class="none">该状态下暂无内容</p>
  </div>
</template>

<style scoped>
.card { display: block; cursor: default; background: #fff; border: 1px solid var(--border2); border-radius: 10px; padding: 15px 18px; }
.card h3 { font-size: 14px; display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-bottom: 8px; }
.card h3 .spacer { flex: 1; }
.chips { display: flex; align-items: center; gap: 7px; margin-bottom: 10px; flex-wrap: wrap; }
.chip { font-size: 12px; font-weight: 600; padding: 4px 12px; border-radius: 999px; border: 1px solid var(--border2); background: #fff; color: var(--muted-fg); cursor: pointer; }
.chip.on { background: var(--primary); border-color: var(--primary); color: #fff; }
.chip.on.warn { background: #b45309; border-color: #b45309; }
.chips .pct { font-size: 11.5px; color: var(--muted-fg); margin-left: auto; }
.rrow { display: flex; align-items: flex-start; gap: 10px; padding: 8px 2px; border-top: 1px solid #f1f5f9; font-size: 12.5px; }
.rrow .rid { font-family: var(--mono); font-size: 11.5px; color: var(--muted-fg); flex: none; padding-top: 1px; min-width: 26px; }
.rrow .rtxt { flex: 1; min-width: 0; }
.rrow .rsrc { display: block; font-size: 11px; color: var(--muted-fg); margin-top: 1px; }
.rrow .acts { display: flex; gap: 5px; flex: none; align-items: center; }
.rrow.gap { background: #fffbeb; }
.rrow.gap .gtag { flex: none; font-weight: 700; font-size: 11px; color: var(--warn); }
.rrow.done { opacity: .55; }
.askform { padding: 2px 2px 10px 36px; border-top: 1px dashed #f1f5f9; }
.askform textarea { width: 100%; font-family: inherit; font-size: 12.5px; padding: 7px 10px; border: 1px solid var(--border2); border-radius: 6px; resize: vertical; margin: 8px 0 6px; }
.askbtns { display: flex; gap: 6px; }
.confbox { border: 1px solid #fecaca; background: #fef7f7; border-radius: 10px; padding: 10px 14px; margin: 4px 0 10px; }
.confhead { display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; }
.confhead .ctag { font-weight: 700; color: var(--destructive); flex: none; }
.confhead .ctitle { flex: 1; min-width: 0; font-weight: 600; font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.confhead .chev { color: var(--muted-fg); flex: none; font-size: 11px; }
.confbox h4 { font-size: 13px; display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.cq { font-weight: 600; font-size: 12.5px; margin-bottom: 6px; }
.confcard { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 8px 0 2px; }
.confside { border: 1px solid var(--border2); border-radius: 8px; padding: 10px 12px; font-size: 12px; background: #fff; }
.confside .who { font-size: 11px; font-weight: 700; margin-bottom: 4px; }
.confside.a { background: #f6f9ff; border-color: #c3d7f7; }
.confside.a .who { color: var(--primary); }
.confside.b { background: #fffaf0; border-color: #ecd9b0; }
.confside.b .who { color: var(--warn); }
.cbtns { display: flex; gap: 8px; margin-top: 10px; }
.none { color: var(--muted-fg); font-size: 12px; padding: 10px 0 2px; }
@media (max-width: 640px) { .confcard { grid-template-columns: 1fr; } }
</style>
