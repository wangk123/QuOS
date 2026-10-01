<script setup lang="ts">
// Task 8 工作台右主区节点详情：根详情（wb 聚合，不走 getProfile——它按树节点寻址）+ 节点三态（排队/处理中骨架/就绪三 tab）。
// 就绪态读侧：getProfile + getRules(本节点子树) + getConflicts(按 a/b 规则 node 归属过滤，查不到归属不过滤防漏) + getGaps(无 node 字段→项目级全量)。
import { computed, ref, watch } from 'vue'
import { getConflicts, getGaps, getProfile, getRules, type Conflict, type Gap, type Profile, type Rule } from '../api'
import { digitPathOf, wb } from '../wb'
import DetailDoubt from '../components/detail/DetailDoubt.vue'
import DetailOverview from '../components/detail/DetailOverview.vue'
import DetailRules from '../components/detail/DetailRules.vue'

const props = defineProps<{ nodeFull: string; state: string }>()
const emit = defineEmits<{ jump: [full: string]; 'clar-changed': [] }>()
const tab = ref<'overview' | 'rules' | 'doubt'>('overview')

// ── 根详情：wb.root + wb.tree 顶层行（与 WbTree 根卡同口径：只对顶层求和，防模块/叶双计）
const isRoot = computed(() => props.nodeFull === '__root__')
const topRows = computed(() => (wb.value?.tree ?? []).filter(r => !r.path.includes(',')))
const rootPend = computed(() => topRows.value.reduce((s, r) => s + r.pend, 0))
const rootStat = computed(() => {
  const t = wb.value?.tree ?? []
  return { done: t.filter(r => r.state === 'done').length, doing: t.some(r => r.state === 'doing'), total: t.length }
})
/** 主线 chips：flow 文本按行/「→」拆，名字命中顶层模块行 → full 可点跳；命中不上只展示 */
interface Chip { text: string; full?: string }
const flowChips = computed<Chip[]>(() => {
  const names = new Map(topRows.value.map(r => [r.name, r.full]))
  return (wb.value?.root?.flow ?? '')
    .split(/\n|→/).map(s => s.trim()).filter(Boolean).map(text => ({ text, full: names.get(text) }))
})
/** 边界 chips：boundaries 按 ·、，拆，纯展示不可点 */
const boundChips = computed(() => (wb.value?.root?.boundaries ?? '').split(/[·、，,]/).map(s => s.trim()).filter(Boolean))

// ── 节点就绪态数据（读侧）
const profile = ref<Profile | null>(null)
const rules = ref<Rule[]>([]) // 本节点子树规则（条目 tab）
const allRules = ref<Rule[]>([]) // 全量规则（存疑 tab 冲突 a/b 反查文本）
const conflicts = ref<Conflict[]>([])
const gaps = ref<Gap[]>([]) // Gap 无 node 字段：项目级全量展示（见任务报告）
const err = ref('')
const loading = ref(false)

async function load() {
  err.value = ''
  profile.value = null
  rules.value = []
  allRules.value = []
  conflicts.value = []
  gaps.value = []
  if (props.nodeFull === '__root__' || props.state !== 'done') return
  loading.value = true
  try {
    const [p, rs, cs, gs] = await Promise.all([getProfile(digitPathOf(props.nodeFull) || props.nodeFull), getRules(), getConflicts(), getGaps()])
    const under = (n?: string) => !!n && (n === props.nodeFull || n.startsWith(props.nodeFull + '/'))
    profile.value = p
    allRules.value = rs
    rules.value = rs.filter(r => under(r.node))
    const nodeOf = new Map(rs.map(r => [r.id, r.node ?? '']))
    conflicts.value = cs.filter(c => {
      const na = nodeOf.get(c.a), nb = nodeOf.get(c.b)
      if (na === undefined && nb === undefined) return true // a/b 规则查不到归属（已删/未同步）：不过滤防漏
      return under(na) || under(nb)
    })
    gaps.value = gs
  } catch (e) {
    err.value = e instanceof Error ? `详情加载失败：${e.message}` : String(e)
  } finally {
    loading.value = false
  }
}
// 切节点/状态翻新（含 ''→done 就绪瞬间）；tab 回概要
watch(() => [props.nodeFull, props.state], () => { tab.value = 'overview'; void load() }, { immediate: true })

const parts = computed(() => (isRoot.value ? [] : props.nodeFull.split('/')))
/** 就绪态右侧徽章：取 wb 行 pend（后端已含冲突数）；行缺失（如未同步）不显示 */
const rowPend = computed(() => (wb.value?.tree ?? []).find(r => r.full === props.nodeFull)?.pend ?? -1)
/** 存疑 tab 徽章：只计 open 冲突 + 未处置缺口（已裁决/已处置不占角标） */
const doubtN = computed(
  () => conflicts.value.filter(c => c.st === 'open').length + gaps.value.filter(g => g.st === 'open').length,
)
</script>

<template>
  <!-- ── 根详情 ── -->
  <div v-if="isRoot" class="wbdetail">
    <div class="crumb">
      <b>◉ 需求总览</b>
      <span class="right">
        <span v-if="rootStat.doing" class="badge b-blue">后台处理中</span>
        <span v-else-if="rootStat.total" :class="rootPend ? 'badge b-amber' : 'badge b-green'">{{ rootPend ? `${rootPend} 处待你判断` : '判断清零 ✓' }}</span>
      </span>
    </div>
    <div v-if="rootStat.doing" class="doing-box"><span class="spin" /><span>后台正在逐个节点完善（{{ rootStat.done }}/{{ rootStat.total }}）——已出来的部分随时可以看和改，不用等</span></div>
    <div v-if="rootStat.doing" class="card"><div class="skel w90" /><div class="skel w75" /><div class="skel w60" /><div class="skel w45" /></div>
    <div class="card">
      <h3>这份需求是什么</h3>
      <p class="rootdesc">{{ wb?.root?.goal || '根画像未生成——生成需求后由 AI 汇总；也可在左栏根卡点 ✎ 手工补一句' }}</p>
      <template v-if="wb?.root">
        <div class="spec mini">
          <span class="k">入口</span><span>{{ wb.root.entry || '—' }}</span>
          <span class="k">备注</span><span>{{ wb.root.note || '—' }}</span>
        </div>
        <div v-if="boundChips.length" class="h4s">给谁 · 边界</div>
        <div v-if="boundChips.length" class="jline"><span v-for="(c, i) in boundChips" :key="'b' + i" class="jstep-chip plain">{{ c }}</span></div>
        <div v-if="flowChips.length" class="h4s">端到端主线（点击定位到树上）</div>
        <div v-if="flowChips.length" class="jline">
          <template v-for="(c, i) in flowChips" :key="'f' + i">
            <span v-if="i" class="jarr">→</span>
            <span class="jstep-chip" :class="{ plain: !c.full }" @click="c.full && emit('jump', c.full)">{{ c.text }}</span>
          </template>
        </div>
      </template>
      <div class="h4s">模块速览</div>
      <table class="mtx">
        <tbody>
          <tr><th>模块</th><th>条目</th><th>状态</th></tr>
          <tr v-for="r in topRows" :key="r.path" class="clickable" @click="emit('jump', r.full)">
            <td>{{ r.name }}</td>
            <td class="num">{{ r.rules }}</td>
            <td><span :class="r.state === 'doing' ? 'badge b-blue' : r.pend ? 'badge b-amber' : 'badge b-green'">{{ r.state === 'doing' ? '处理中' : r.pend ? `${r.pend} 待判断` : '就绪' }}</span></td>
          </tr>
          <tr v-if="!topRows.length"><td colspan="3" class="none">树还是空的——先在左栏加模块</td></tr>
        </tbody>
      </table>
      <div class="h4s">待你判断</div>
      <p class="pendsum"><template v-if="rootPend">全部模块合计 <b>{{ rootPend }}</b> 处待判断——在左栏逐节点清零</template><template v-else>全部模块判断清零 ✓</template></p>
    </div>
  </div>

  <!-- ── 节点：排队 / 处理中 ── -->
  <div v-else-if="state !== 'done'" class="wbdetail">
    <div class="crumb">
      <b>{{ parts[parts.length - 1] }}</b>
      <span class="right"><span :class="state === 'doing' ? 'badge b-blue' : 'badge b-gray'">{{ state === 'doing' ? '后台正在完善' : '排队中' }}</span></span>
    </div>
    <div v-if="state === 'doing'" class="doing-box"><span class="spin" /><span>正在完善本节点——AI 逐条提炼并核验行为要求…</span></div>
    <div v-if="state === 'doing'" class="card"><div class="skel w90" /><div class="skel w75" /><div class="skel w60" /><div class="skel w45" /></div>
    <div v-else class="card"><div class="doing-box nom"><span class="spin" /><span>排在后台队列里——先处理前面的节点。不用等，可以先去改树的结构。</span></div></div>
  </div>

  <!-- ── 节点：就绪（三 tab，读侧） ── -->
  <div v-else class="wbdetail">
    <div class="crumb">
      <button class="cl" type="button" @click="emit('jump', '__root__')">◉ 需求总览</button>
      <template v-for="(p, i) in parts" :key="i">
        <span class="sep">›</span>
        <button v-if="i < parts.length - 1" class="cl" type="button" @click="emit('jump', parts.slice(0, i + 1).join('/'))">{{ p }}</button>
        <b v-else>{{ p }}</b>
      </template>
      <span class="right">
        <span v-if="rowPend > 0" class="badge b-amber">{{ rowPend }} 处待判断</span>
        <span v-else-if="rowPend === 0" class="badge b-green">判断清零 ✓</span>
      </span>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <div v-else-if="loading || !profile" class="card"><div class="skel w90" /><div class="skel w75" /><div class="skel w60" /><div class="skel w45" /></div>
    <template v-else>
      <div class="tabbar">
        <button class="tab" :class="{ on: tab === 'overview' }" @click="tab = 'overview'">概要</button>
        <button class="tab" :class="{ on: tab === 'rules' }" @click="tab = 'rules'">条目 <span class="c">{{ rules.length }}</span></button>
        <button class="tab" :class="{ on: tab === 'doubt' }" @click="tab = 'doubt'">存疑 <span v-if="doubtN" class="c conf">⚠{{ doubtN }}</span></button>
      </div>
      <DetailOverview v-if="tab === 'overview'" :profile="profile" />
      <DetailRules v-else-if="tab === 'rules'" :rules="rules" @clar-changed="emit('clar-changed')" />
      <DetailDoubt v-else :conflicts="conflicts" :gaps="gaps" :all-rules="allRules" @clar-changed="emit('clar-changed')" />
    </template>
  </div>
</template>

<style scoped>
.wbdetail { padding: 2px 2px 20px; }
.crumb { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted-fg); margin-bottom: 9px; flex-wrap: wrap; }
.crumb b { color: var(--fg); } .crumb .sep { color: var(--border2); }
.crumb .right { margin-left: auto; display: flex; gap: 6px; }
.crumb .cl { background: none; color: var(--muted-fg); padding: 0; font-size: 12px; }
.crumb .cl:hover { color: var(--primary); }
.card { display: block; cursor: default; background: #fff; border: 1px solid var(--border2); border-radius: 10px; padding: 15px 18px; margin-bottom: 12px; }
.card h3 { font-size: 14px; display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-bottom: 8px; }
.h4s { font-size: 11.5px; color: var(--muted-fg); margin: 13px 0 4px; letter-spacing: .05em; font-weight: 700; }
.rootdesc { font-size: 13px; } .pendsum { font-size: 12.5px; }
.spec { display: grid; grid-template-columns: 76px 1fr; gap: 4px 12px; font-size: 12.5px; }
.spec .k { color: var(--muted-fg); } .spec.mini { margin-top: 10px; }
.doing-box { display: flex; align-items: center; gap: 12px; background: var(--blue-bg); border: 1px solid #b6d0f5; border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; color: var(--primary); font-size: 12.5px; }
.doing-box.nom { margin: 0; }
.doing-box .spin { width: 15px; height: 15px; border: 2.5px solid #b6d0f5; border-top-color: var(--primary); border-radius: 50%; animation: spin .9s linear infinite; flex: none; }
@keyframes spin { to { transform: rotate(360deg); } }
.skel { height: 11px; border-radius: 5px; background: linear-gradient(90deg, #e8eef8 25%, #f4f8fd 50%, #e8eef8 75%); background-size: 200% 100%; animation: shine 1.3s infinite; margin-bottom: 8px; }
.skel.w90 { width: 90%; } .skel.w75 { width: 75%; } .skel.w60 { width: 60%; } .skel.w45 { width: 45%; }
@keyframes shine { to { background-position: -200% 0; } }
.jline { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin: 6px 0; }
.jstep-chip { display: inline-flex; align-items: center; gap: 4px; background: var(--blue-bg); color: var(--primary); font-size: 11.5px; font-weight: 600; padding: 3px 9px; border-radius: 6px; cursor: pointer; border: 1px solid transparent; }
.jstep-chip:hover { border-color: var(--secondary); }
.jstep-chip.plain { cursor: default; color: var(--muted-fg); background: var(--muted); } .jstep-chip.plain:hover { border-color: transparent; }
.jarr { color: var(--border2); font-size: 12px; }
.mtx { border-collapse: collapse; width: 100%; font-size: 12px; margin-top: 4px; }
.mtx th, .mtx td { border: 1px solid var(--border); padding: 4px 8px; text-align: left; }
.mtx th { background: var(--muted); }
.mtx td.num { text-align: right; font-variant-numeric: tabular-nums; }
.mtx tr.clickable { cursor: pointer; } .mtx tr.clickable:hover td { background: #f1f5fd; }
.mtx td.none { color: var(--muted-fg); text-align: center; }
.tabbar { display: flex; gap: 3px; border-bottom: 1.5px solid var(--border2); margin-bottom: 12px; }
.tab { padding: 7px 13px; background: none; color: var(--muted-fg); border-radius: 8px 8px 0 0; border-bottom: 2.5px solid transparent; font-weight: 600; }
.tab.on { color: var(--primary); border-bottom-color: var(--primary); background: #fff; }
.tab .c { font-size: 10.5px; font-weight: 700; border-radius: 8px; padding: 0 6px; margin-left: 5px; background: var(--muted); color: var(--muted-fg); }
.tab .c.conf { background: var(--red-bg); color: var(--destructive); }
</style>
