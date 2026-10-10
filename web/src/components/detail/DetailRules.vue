<script setup lang="ts">
// 规则 tab（四类问题统一折叠模式）：行上只有图标+文本+徽章（空间全给内容），
// 展开后显示动作与输入。二分恒等：全部 = 核验通过 + 待处理；
// 待处理 = open 冲突 + open 缺口 + 待核规则；处置完即人工确认过 → 归核验通过（灰行留痕）。
import { computed, inject, ref } from 'vue'
import { ApiError, addRuleManual, confirmRule, correctRule, disposeGap, resolveConflict,
         verifyJob, type Conflict, type Gap, type Rule } from '../../api'
import { jobRunning, startJobPolling } from '../../jobs'
import { refreshWb } from '../../wb'

const props = defineProps<{ rules: Rule[]; conflicts: Conflict[]; gaps: Gap[]; allRules: Rule[]; nodeFull: string }>()
const emit = defineEmits<{ 'clar-changed': [] }>()
const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const CONF: Record<string, string> = { 实证: 'b-green', 文档: 'b-blue', 推测: 'b-amber', 待实证: 'b-red', 旧文档: 'b-gray' }
const LETTERS = ['A', 'B', 'C', 'D', 'E', 'F']

// ---- 折叠状态（行点击展开/收起；key=条目 id）----
const expanded = ref(new Set<string>())
function toggle(key: string) {
  expanded.value.has(key) ? expanded.value.delete(key) : expanded.value.add(key)
}

// ---- 写操作本地覆盖 ----
const okLocal = ref(new Set<string>())
const cOver = ref(new Map<string, Conflict>())
const gOver = ref(new Map<string, Gap>())
const isOk = (r: Rule) => r.verified || okLocal.value.has(r.id)
const confList = computed(() => props.conflicts.map(c => cOver.value.get(c.id) ?? c))
const gapList = computed(() => props.gaps.map(g => gOver.value.get(g.id) ?? g))

// ---- 状态 chips：全部 = 核验通过 + 待处理（计数恒等）----
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

// ---- 冲突：说法可选卡 + 统一确认 ----
const picked = ref(new Map<string, number | 'other'>()) // conflictId -> 选项
const manualText = ref('')
const busyConf = ref('')
function pickConf(c: Conflict, i: number | 'other') {
  picked.value.set(c.id, i)
}
function confReady(c: Conflict): boolean {
  const p = picked.value.get(c.id)
  if (p === undefined) return false
  if (p === 'other') return manualText.value.trim().length > 0
  return true
}
async function confirmResolve(c: Conflict) {
  const p = picked.value.get(c.id)
  if (p === undefined) return
  busyConf.value = c.id
  try {
    const updated = p === 'other'
      ? await resolveConflict(c.id, 'manual', undefined, manualText.value.trim())
      : await resolveConflict(c.id, 'code', p)
    cOver.value.set(c.id, updated)
    picked.value.delete(c.id)
    manualText.value = ''
    void refreshWb()
    toast(p === 'other' ? `${c.id} 已按「其他」落实证规则` : `${c.id} 已裁定`, 'ok')
  } catch (e) { fail(e, '裁决失败') } finally { busyConf.value = '' }
}

// ---- 缺口：补写 / 设计如此 ----
const noteText = ref('')
async function disposeGapAs(g: Gap, action: 'ok' | 'note') {
  try {
    const updated = await disposeGap(g.id, action, noteText.value.trim())
    gOver.value.set(g.id, updated)
    noteText.value = ''
    void refreshWb()
    toast(action === 'note' ? '已补写：生成实证规则，缺口闭环 ✓' : '已按「设计如此」记录 ✓', 'ok')
  } catch (e) { fail(e, '处置失败') }
}

// ---- 待核规则：核验 / 修正 ----
const fixText = ref('')
async function onConfirm(r: Rule) {
  try {
    await confirmRule(r.id)
    okLocal.value.add(r.id)
    void refreshWb()
    toast(`${r.id} 已人工核过 ✓`, 'ok')
  } catch (e) { fail(e, '操作失败') }
}
async function onCorrect(r: Rule) {
  try {
    await correctRule(r.id, fixText.value.trim())
    okLocal.value.add(r.id)
    fixText.value = ''
    void refreshWb()
    toast(`${r.id} 已修正（标黄留痕）✓`, 'ok')
  } catch (e) { fail(e, '修正失败') }
}

// ---- 自定义开放：手动记规则 ----
const openText = ref('')
async function onRecord() {
  try {
    await addRuleManual(openText.value.trim(), props.nodeFull)
    openText.value = ''
    expanded.value.delete('__open__')
    void refreshWb()
    toast('已记录：人工确认规则 ✓', 'ok')
  } catch (e) { fail(e, '记录失败') }
}

// ---- AI 辅助核验 ----
async function aiVerify() {
  try {
    const r = await verifyJob({ only_doc: true })
    startJobPolling(r.job_id, async (msg, cls) => {
      toast(msg, cls)
      await refreshWb()
    })
  } catch (e) { fail(e, '核验失败') }
}

// 冲突各方文本
const byId = computed(() => new Map(props.allRules.map(r => [r.id, r])))
function side(id: string) {
  const r = byId.value.get(id)
  return { src: r?.src ?? id, text: r?.text ?? '（规则已不存在）' }
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

    <template v-if="filter !== 'ok'">
      <!-- ⚠ 冲突：折叠行 → 展开选择+统一确认 -->
      <template v-for="c in openConfs" :key="c.id">
        <div class="fold red" @click="toggle(c.id)">
          <span class="ftag warn">⚠</span>
          <span class="ftxt">{{ c.id }} · {{ c.q }}<span class="fsub">冲突 · {{ c.parties.length }} 方说法待裁决</span></span>
          <span class="chev">{{ expanded.has(c.id) ? '▾' : '▸' }}</span>
        </div>
        <div v-if="expanded.has(c.id)" class="foldbody red">
          <div v-for="(pid, i) in c.parties" :key="pid" class="opt"
               :class="{ sel: picked.get(c.id) === i }" @click="pickConf(c, i)">
            <span class="tag">{{ LETTERS[i] ?? i + 1 }}</span>
            <div class="obody"><span class="osrc">{{ side(pid).src }}</span>{{ side(pid).text }}</div>
          </div>
          <div class="opt" :class="{ sel: picked.get(c.id) === 'other' }" @click="pickConf(c, 'other')">
            <span class="tag">其</span>
            <div class="obody">其他——实际行为与以上都不同（确认后生成实证规则，各方作废）</div>
          </div>
          <textarea v-if="picked.get(c.id) === 'other'" v-model="manualText" rows="2"
                    placeholder="实际行为是什么就写什么" />
          <div class="confirmbar">
            <button class="btn-primary btn-sm" type="button" :disabled="!confReady(c) || busyConf === c.id"
                    @click="confirmResolve(c)">{{ busyConf === c.id ? '裁决中…' : '确认裁决' }}</button>
            <span class="hint">选择一条说法（或其他）后启用——裁决即生效，败方作废</span>
          </div>
        </div>
      </template>

      <!-- △ 缺口：折叠行 → 展开三动作 -->
      <template v-for="g in openGaps" :key="g.id">
        <div class="fold amber" @click="toggle(g.id)">
          <span class="ftag warn">△</span>
          <span class="ftxt">{{ g.text }}<span class="fsub">缺口 · {{ g.dim }} · 材料没说清</span></span>
          <span class="chev">{{ expanded.has(g.id) ? '▾' : '▸' }}</span>
        </div>
        <div v-if="expanded.has(g.id)" class="foldbody amber">
          <div class="actsbar">
            <button class="btn-sm" type="button" @click="toggle(g.id + '-note')">✎ 补写说明</button>
            <button class="btn-sm" type="button" @click="disposeGapAs(g, 'ok')">设计如此</button>
            <button class="btn-sm link" type="button" title="保持待处理，直达证据池（补料后智能生成自动核对闭环）"
                    @click="emit('clar-changed'); toast('请到顶栏「证据池」补材料——补料后点智能生成自动闭环', 'ok')">去补材料 →</button>
          </div>
          <template v-if="expanded.has(g.id + '-note')">
            <textarea v-model="noteText" rows="2"
                      placeholder="实际是什么就写什么——将生成一条人工确认的规则，缺口随即闭环" />
            <div class="confirmbar">
              <button class="btn-primary btn-sm" type="button" :disabled="!noteText.trim()"
                      @click="disposeGapAs(g, 'note')">确认补写</button>
            </div>
          </template>
        </div>
      </template>

      <!-- 待核规则：折叠行 → 核验/修正（推测级带 ？ 标） -->
      <template v-for="r in pendRules" :key="r.id">
        <div class="fold" @click="toggle(r.id)">
          <span class="ftag" :class="{ q: r.conf === '推测' }">{{ r.conf === '推测' ? '？' : r.id }}</span>
          <span class="ftxt">{{ r.text }}<span class="fsub">{{ r.id }} · {{ r.src }} · {{ r.conf === '推测' ? '推测——与实际系统一致吗？' : '待核' }}</span></span>
          <span class="badge" :class="CONF[r.conf] ?? 'b-gray'">{{ r.conf }}</span>
          <span class="chev">{{ expanded.has(r.id) ? '▾' : '▸' }}</span>
        </div>
        <div v-if="expanded.has(r.id)" class="foldbody">
          <div class="actsbar">
            <button class="btn-sm" type="button" @click="onConfirm(r)">核验（与实际一致 ✓）</button>
            <button class="btn-sm" type="button" @click="toggle(r.id + '-fix')">✎ 修正实际行为</button>
          </div>
          <template v-if="expanded.has(r.id + '-fix')">
            <textarea v-model="fixText" rows="2"
                      placeholder="实际行为是什么就写什么——该规则将被修正并标黄（保留追溯）" />
            <div class="confirmbar">
              <button class="btn-primary btn-sm" type="button" :disabled="!fixText.trim()"
                      @click="onCorrect(r)">确认修正</button>
            </div>
          </template>
        </div>
      </template>

      <!-- ✎ 自定义开放：折叠行 → 自由输入 -->
      <div class="fold" @click="toggle('__open__')">
        <span class="ftag q">✎</span>
        <span class="ftxt" style="color: var(--muted-fg)">想核实什么就记在这里——答案直接落为规则（人工确认级）<span class="fsub">挂在当前节点</span></span>
        <span class="chev">{{ expanded.has('__open__') ? '▾' : '▸' }}</span>
      </div>
      <div v-if="expanded.has('__open__')" class="foldbody">
        <textarea v-model="openText" rows="2"
                  placeholder="例：回调地址是否要求 HTTPS？——现场确认支持 HTTP" />
        <div class="confirmbar">
          <button class="btn-primary btn-sm" type="button" :disabled="!openText.trim()"
                  @click="onRecord">确认记录</button>
          <span class="hint">问题 + 答案一起写；答案将直接落到规则</span>
        </div>
      </div>
    </template>

    <!-- 核验通过区：已处置留痕 + 已核规则（灰行，不折叠） -->
    <template v-if="filter !== 'pend'">
      <div v-for="c in doneConfs" :key="c.id" class="rrow done">
        <span class="rid">✓</span>
        <span class="rtxt">{{ c.q }}<span class="rsrc">冲突已裁决 · {{ c.resolution === 'manual' ? '其他：' + (c.manual_text ?? '') : `信 ${c.resolution}` }}</span></span>
      </div>
      <div v-for="g in doneGaps" :key="g.id" class="rrow done">
        <span class="rid">✓</span>
        <span class="rtxt">{{ g.text }}<span class="rsrc">缺口已处置 · {{ g.st === 'answered' ? '已补 ✓（材料或人工补写闭环）' : '设计如此' }}</span></span>
      </div>
      <div v-for="r in okRules" :key="r.id" class="rrow">
        <span class="rid">{{ r.id }}</span>
        <span class="rtxt">{{ r.text }}<span class="rsrc">{{ r.src }}{{ r.suspect ? ' · 已人工修正（标黄留痕）' : '' }}</span></span>
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

/* 统一折叠行：行上只有图标+文本+徽章，空间全给内容 */
.fold { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border: 1px solid var(--border2); border-radius: 8px; margin-bottom: 3px; cursor: pointer; user-select: none; background: #fff; }
.fold:hover { border-color: #cbd5e1; }
.fold.red { background: var(--red-bg, #fef7f7); border-color: #fecaca; }
.fold.amber { background: #fffbeb; border-color: #fde68a; }
.fold .ftag { flex: none; font-weight: 700; font-size: 12px; min-width: 26px; color: var(--muted-fg); font-family: var(--mono); }
.fold .ftag.warn { color: var(--warn); }
.fold .ftag.q { color: var(--primary); }
.fold .ftxt { flex: 1; min-width: 0; font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fold .fsub { display: block; font-size: 11px; color: var(--muted-fg); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fold .chev { flex: none; color: var(--muted-fg); font-size: 11px; }
.foldbody { border: 1px solid var(--border2); border-top: none; border-radius: 0 0 8px 8px; padding: 10px 12px; margin: -3px 0 10px; background: #fff; }
.foldbody.red { border-color: #fecaca; background: #fffdfd; }
.foldbody.amber { border-color: #fde68a; background: #fffdf5; }
.foldbody textarea { width: 100%; font: inherit; font-size: 12.5px; padding: 7px 10px; border: 1px solid var(--border2); border-radius: 6px; resize: vertical; margin-bottom: 8px; }
.actsbar { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 4px; }
.confirmbar { display: flex; gap: 8px; align-items: center; }
.confirmbar .hint { font-size: 11px; color: var(--muted-fg); }

/* 冲突说法可选卡 */
.opt { display: flex; gap: 10px; border: 1.5px solid var(--border2); background: #fff; border-radius: 8px; padding: 9px 12px; margin-bottom: 6px; cursor: pointer; transition: border-color .15s, background .15s; position: relative; }
.opt:hover { border-color: #93c5fd; }
.opt.sel { border-color: var(--primary); background: #eff6ff; }
.opt.sel::after { content: '✓ 已选'; position: absolute; top: 7px; right: 10px; font-size: 10.5px; font-weight: 700; color: var(--primary); }
.opt .tag { flex: none; width: 20px; height: 20px; border-radius: 50%; border: 1.5px solid var(--muted-fg); color: var(--muted-fg); font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.opt.sel .tag { border-color: var(--primary); background: var(--primary); color: #fff; }
.opt .obody { flex: 1; min-width: 0; font-size: 12px; }
.opt .osrc { display: block; font-size: 11px; color: var(--muted-fg); margin-bottom: 2px; }

/* 已处置/已核灰行 */
.rrow { display: flex; align-items: flex-start; gap: 10px; padding: 8px 2px; border-top: 1px solid #f1f5f9; font-size: 12.5px; }
.rrow .rid { font-family: var(--mono); font-size: 11.5px; color: var(--muted-fg); flex: none; padding-top: 1px; min-width: 26px; }
.rrow .rtxt { flex: 1; min-width: 0; }
.rrow .rsrc { display: block; font-size: 11px; color: var(--muted-fg); margin-top: 1px; }
.rrow .acts { display: flex; gap: 5px; flex: none; align-items: center; }
.rrow.done { opacity: .55; }

.btn-sm { font: inherit; font-weight: 600; font-size: 12px; padding: 4px 12px; border-radius: 7px; border: 1px solid var(--border2); background: #fff; cursor: pointer; }
.btn-sm.link { color: var(--primary); border-color: #bfdbfe; }
.btn-sm.btn-primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn-sm.btn-primary:disabled { opacity: .45; cursor: not-allowed; }
.none { color: var(--muted-fg); font-size: 12px; padding: 10px 0 2px; }
</style>
