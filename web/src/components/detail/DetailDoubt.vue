<script setup lang="ts">
// 存疑 tab：冲突卡三选一（信A/信B=code 裁决、转待确认=clar）+ 缺口行两按钮（转澄清/设计如此）——
// 裁决后即时转结论态（本地覆盖，父列表不重拉），树徽章联动走 refreshWb。
import { computed, inject, ref } from 'vue'
import { ApiError, disposeGap, resolveConflict, type Conflict, type Gap, type Rule } from '../../api'
import { refreshWb } from '../../wb'

const props = defineProps<{ conflicts: Conflict[]; gaps: Gap[]; allRules: Rule[] }>()
const emit = defineEmits<{ 'clar-changed': [] }>()
const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const byId = computed(() => new Map(props.allRules.map(r => [r.id, r])))
function side(id: string) {
  const r = byId.value.get(id)
  return { src: r?.src ?? id, text: r?.text ?? '（规则已不存在）' }
}

// 写操作本地覆盖：后端返回已更新的 Conflict/Gap，直接替换渲染
const cOver = ref(new Map<string, Conflict>())
const gOver = ref(new Map<string, Gap>())
const confList = computed(() => props.conflicts.map(c => cOver.value.get(c.id) ?? c))
const gapList = computed(() => props.gaps.map(g => gOver.value.get(g.id) ?? g))
const openGapN = computed(() => gapList.value.filter(g => g.st === 'open').length)

function fail(e: unknown, prefix: string) {
  toast(e instanceof ApiError ? `${prefix}：${e.message}` : prefix, 'warn')
}

/** 冲突三选一：code=信某侧（resolution 落胜方规则 id）；clar=转澄清池（答案回来再裁） */
async function resolve(c: Conflict, action: 'code' | 'clar', side?: 'a' | 'b') {
  try {
    const updated = await resolveConflict(c.id, action, side)
    cOver.value.set(c.id, updated)
    void refreshWb()
    if (action === 'clar') emit('clar-changed') // 顶栏待确认角标
    toast(action === 'clar' ? `${c.id} → 已转待确认` : `${c.id} 已裁定（信${side === 'a' ? 'A' : 'B'}）`, 'ok')
  } catch (e) {
    fail(e, '裁决失败')
  }
}

/** 缺口处置：clar=转澄清追问；ok=设计如此（记录在案，行转灰） */
async function dispose(g: Gap, action: 'clar' | 'ok') {
  try {
    const updated = await disposeGap(g.id, action)
    gOver.value.set(g.id, updated)
    void refreshWb()
    if (action === 'clar') emit('clar-changed')
    toast(action === 'clar' ? `${g.id} → 已转待确认` : '已按「设计如此」记录', 'ok')
  } catch (e) {
    fail(e, '处置失败')
  }
}
</script>

<template>
  <template v-for="c in confList" :key="c.id">
    <div v-if="c.st !== 'open'" class="card"><div class="resolved">✓ {{ c.q }} —— {{ c.resolution ?? '已转待确认，等答案回来' }}</div></div>
    <div v-else class="card">
      <h3>矛盾 · {{ c.id }} <span class="badge b-red">两处材料说法冲突</span></h3>
      <p class="cq">{{ c.q }}</p>
      <div class="confcard">
        <div class="confside a"><div class="who">A · {{ side(c.a).src }}</div>{{ side(c.a).text }}</div>
        <div class="confside b"><div class="who">B · {{ side(c.b).src }}</div>{{ side(c.b).text }}</div>
      </div>
      <div class="cbtns">
        <button class="btn-ghost btn-sm" type="button" title="以 A 侧为准，B 侧作废" @click="resolve(c, 'code', 'a')">信A</button>
        <button class="btn-ghost btn-sm" type="button" title="以 B 侧为准，A 侧作废" @click="resolve(c, 'code', 'b')">信B</button>
        <button class="btn-accent btn-sm" type="button" title="进澄清池，向人追问后再裁" @click="resolve(c, 'clar')">转待确认</button>
      </div>
    </div>
  </template>
  <div class="card">
    <h3>缺口 <span class="badge b-amber">{{ openGapN }}</span> <span class="sub">按维度扫概要发现的「没说到」</span></h3>
    <div v-for="g in gapList" :key="g.id" class="rrow" :class="{ done: g.st !== 'open' }">
      <span class="rtxt">{{ g.text }}<span class="rsrc">维度：{{ g.dim }}</span></span>
      <span v-if="g.st === 'open'" class="gacts">
        <button class="btn-ghost btn-sm" type="button" title="进澄清池，向人追问" @click="dispose(g, 'clar')">转澄清</button>
        <button class="btn-ghost btn-sm" type="button" title="确实不用说明，记录在案" @click="dispose(g, 'ok')">设计如此</button>
      </span>
      <span v-else class="badge b-gray">{{ g.st === 'clar' ? '已转待确认' : '设计如此' }}</span>
    </div>
    <p v-if="!gaps.length" class="none">暂无缺口</p>
  </div>
</template>

<style scoped>
.card { display: block; cursor: default; background: #fff; border: 1px solid var(--border2); border-radius: 10px; padding: 15px 18px; margin-bottom: 12px; }
.card h3 { font-size: 14px; display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-bottom: 8px; }
.card h3 .sub { font-weight: 400; font-size: 11.5px; color: var(--muted-fg); }
.cq { font-weight: 600; font-size: 13px; }
.confcard { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 8px 0 2px; }
.confside { border: 1px solid var(--border2); border-radius: 8px; padding: 10px 12px; font-size: 12px; }
.confside .who { font-size: 11px; font-weight: 700; margin-bottom: 4px; }
.confside.a { background: #f6f9ff; border-color: #c3d7f7; }
.confside.a .who { color: var(--primary); }
.confside.b { background: #fffaf0; border-color: #ecd9b0; }
.confside.b .who { color: var(--warn); }
.cbtns { display: flex; gap: 8px; margin-top: 10px; }
.resolved { display: flex; align-items: center; gap: 8px; background: var(--green-bg); border: 1px solid #bbe3c6; border-radius: 8px; padding: 8px 12px; font-size: 12.5px; color: #14532d; }
.rrow { display: flex; align-items: flex-start; gap: 10px; padding: 8px 2px; border-top: 1px solid #f1f5f9; font-size: 12.5px; }
.rrow:first-of-type { border-top: none; }
.rrow.done { opacity: .55; }
.rrow .rtxt { flex: 1; min-width: 0; }
.rrow .rsrc { display: block; font-size: 11px; color: var(--muted-fg); margin-top: 1px; }
.rrow .gacts { display: flex; gap: 6px; flex: none; align-items: center; }
.none { color: var(--muted-fg); font-size: 12px; padding: 6px 0 0; }
@media (max-width: 640px) { .confcard { grid-template-columns: 1fr; } }
</style>
