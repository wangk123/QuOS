<script setup lang="ts">
// 影响分析弹窗（T17）：新材料 × 现有条目/待确认 → AI 影响分析 → 三方案卡（partial/rescan/full）
// 确认执行 regen 后 startJobPolling 交给 jobs.ts 轮询，完成 toast 出变更摘要（regen kind 已分流）。
import { computed, inject, ref, watch } from 'vue'
import { ApiError, impactAnalyse, regen, type EvidenceItem, type ImpactPlan, type RegenMode } from '../api'
import { startJobPolling } from '../jobs'

const props = defineProps<{ open: boolean; evIds: string[]; evidence: EvidenceItem[] }>()
const emit = defineEmits<{
  close: []
  /** 已发起 regen job——父级刷总表（job 期间 useWb 轮询继续跟进） */
  done: []
}>()

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const loading = ref(false)
const err = ref('')
const plan = ref<ImpactPlan | null>(null)
const pick = ref<RegenMode>('partial')
const running = ref(false)

// 新材料条：evIds 反查 evidence 显示名称/星级（池中无此 id 回退显示 id 本身）
const newEvs = computed(() =>
  props.evIds.map(id => {
    const e = props.evidence.find(x => x.id === id)
    return { id, name: e?.name ?? id, stars: e?.stars ?? 0, type: e?.type ?? '' }
  }),
)

// 三方案卡文案照原型（desc/metA 文案固定，meta 的 partial 影响节点数随 plan 动态）
const opts = computed(() => [
  {
    mode: 'partial' as const,
    title: '局部重新生成',
    desc: '只重跑受影响节点并重扫关联待确认；其余节点不动，已做的核验、裁决全部保留。',
    meta: `影响 ${plan.value?.nodes.length ?? 0} 节点 · 已有人工判断保留`,
  },
  {
    mode: 'rescan' as const,
    title: '仅重扫待确认',
    desc: '树和条目完全不动——只用新材料回答待确认问题（AI 找答案，你逐条采纳/忽略）。',
    meta: '影响 0 节点 · 最快 · 适合「材料只是答疑」的场景',
  },
  {
    mode: 'full' as const,
    title: '全量重新生成',
    desc: '全部节点重来。注意：已做的核验、裁决、手动编辑会被 AI 重新组织，不保证保留。',
    meta: '影响全部节点 · 最慢 · 适合「原始材料大改」的场景',
  },
])

// 打开即分析；无新材料不发起（后端 422），模板出提示。immediate 兼容首挂即 open
watch(
  () => props.open,
  v => {
    if (!v) return
    err.value = ''
    plan.value = null
    running.value = false
    if (!props.evIds.length) return
    loading.value = true
    impactAnalyse(props.evIds)
      .then(p => {
        plan.value = p
        pick.value = p.recommend // AI 推荐默认选中（可改选）
      })
      .catch(e => {
        err.value = e instanceof ApiError ? `分析失败（HTTP ${e.status}）：${e.message}` : String(e)
      })
      .finally(() => (loading.value = false))
  },
  { immediate: true },
)

async function run() {
  if (running.value || !plan.value) return
  running.value = true
  try {
    const r = await regen(pick.value, props.evIds, pick.value === 'partial' ? plan.value.nodes : [])
    startJobPolling(r.job_id, toast) // 进度条 + 完成后 jobs.ts toast 变更摘要
    emit('done')
    emit('close')
  } catch (e) {
    toast(e instanceof ApiError ? `执行失败：${e.message}` : '执行失败', 'warn')
    running.value = false
  }
}
</script>

<template>
  <div class="mask" :class="{ open }" @click.self="$emit('close')">
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>重新生成 · 影响分析</h3>
        <div class="msub">AI 分析新材料与现有需求的关联，给出影响范围与建议——你来定怎么跑</div>
        <button class="x" type="button" aria-label="关闭" @click="$emit('close')">✕</button>
      </div>
      <div class="modal-body">
        <p v-if="err" class="err">{{ err }}</p>

        <div v-if="!evIds.length" class="emptynew">没有新材料——重新生成前先补充材料</div>

        <template v-else>
          <div v-for="e in newEvs" :key="e.id" class="newev">
            <span class="badge b-blue">新材料</span>
            <span class="nm">{{ e.name }}</span>
            <span class="meta">{{ '★'.repeat(e.stars) || '?' }} {{ e.type }}</span>
          </div>

          <template v-if="loading">
            <div class="doing-box"><span class="spin" /><span>AI 正在比对新材料与现有需求…</span></div>
            <div class="skelt"><div class="skel w90" /><div class="skel w75" /><div class="skel w60" /><div class="skel w45" /></div>
          </template>

          <template v-else-if="plan">
            <div class="relrow">
              <span class="badge b-blue">{{ plan.nodes.length }} 个节点</span>
              <span class="rel">{{ plan.nodes.join(' · ') || '无关联' }}</span>
            </div>
            <div class="relrow">
              <span class="badge b-gray">{{ plan.rule_ids.length }} 条条目</span>
              <span class="rel">{{ plan.rule_ids.join(' · ') || '无关联' }}</span>
            </div>
            <div class="relrow">
              <span class="badge b-amber">{{ plan.clar_nos.length }} 个待确认</span>
              <span class="rel">{{ plan.clar_nos.join(' · ') || '无关联' }}</span>
            </div>
            <p v-if="plan.reason" class="reason">✦ AI 判断：{{ plan.reason }}</p>

            <div
              v-for="o in opts"
              :key="o.mode"
              class="optcard"
              :class="{ sel: pick === o.mode }"
              role="radio"
              :aria-checked="pick === o.mode"
              :aria-label="`方案 ${o.title}`"
              tabindex="0"
              @click="pick = o.mode"
              @keydown.enter.prevent="pick = o.mode"
            >
              <div class="optop">
                <span class="radio" />
                <b>{{ o.title }}</b>
                <span v-if="plan.recommend === o.mode" class="badge b-green">✦ AI 推荐</span>
              </div>
              <p>{{ o.desc }}</p>
              <div class="optmeta">{{ o.meta }}</div>
            </div>
          </template>
        </template>
      </div>
      <div class="modal-foot">
        <button v-if="evIds.length" class="btn" type="button" :disabled="running || !plan" @click="run">
          {{ running ? '启动中…' : '按所选方案执行' }}
        </button>
        <span class="fnote">执行中可取消；完成后变更摘要会列出更新了什么</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 样式迁原型 reports/profile-overview-preview/workbench.html（.newev/.relrow/.optcard/.doing-box/.skel） */
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
.emptynew { padding: 36px; text-align: center; color: var(--muted-fg); border: 1px dashed var(--border2); border-radius: var(--radius); }

.newev { display: flex; align-items: center; gap: 10px; background: #f6f9ff; border: 1px solid #c3d7f7; border-radius: 8px; padding: 9px 13px; margin-bottom: 10px; }
.newev .nm { font-family: var(--mono); font-size: 12.5px; word-break: break-all; }
.newev .meta { font-size: 11.5px; color: var(--muted-fg); margin-left: auto; flex: none; }
.relrow { display: flex; align-items: baseline; gap: 7px; flex-wrap: wrap; margin-bottom: 8px; font-size: 12px; }
.relrow .rel { color: var(--muted-fg); word-break: break-all; }
.reason { font-size: 11.5px; color: var(--muted-fg); margin: 0 0 12px; }

.optcard { border: 1.5px solid var(--border2); border-radius: 10px; padding: 11px 14px; margin-bottom: 9px; cursor: pointer; transition: all .15s; }
.optcard:hover { border-color: var(--secondary); }
.optcard.sel { border-color: var(--primary); background: #f6f9ff; box-shadow: 0 0 0 1px var(--primary); }
.optcard .optop { display: flex; align-items: center; gap: 9px; font-size: 13px; }
.optcard .radio { width: 15px; height: 15px; border-radius: 50%; border: 2px solid var(--border2); flex: none; display: inline-block; }
.optcard.sel .radio { border-color: var(--primary); background: radial-gradient(circle, var(--primary) 42%, #f6f9ff 46%); }
.optcard p { font-size: 12px; color: var(--muted-fg); margin: 5px 0 4px 24px; }
.optcard .optmeta { font-size: 11px; color: var(--primary); margin-left: 24px; font-weight: 600; }

.doing-box { display: flex; align-items: center; gap: 12px; background: var(--blue-bg); border: 1px solid #b6d0f5; border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; color: var(--primary); font-size: 12.5px; }
.doing-box .spin { width: 15px; height: 15px; border: 2.5px solid #b6d0f5; border-top-color: var(--primary); border-radius: 50%; animation: spin .9s linear infinite; flex: none; }
@keyframes spin { to { transform: rotate(360deg); } }
.skelt { background: #fff; border: 1px solid var(--border2); border-radius: var(--radius); padding: 12px 14px; }
.skel { height: 11px; border-radius: 5px; background: linear-gradient(90deg, #e8eef8 25%, #f4f8fd 50%, #e8eef8 75%); background-size: 200% 100%; animation: shine 1.3s infinite; margin-bottom: 8px; }
.skel:last-child { margin-bottom: 0; }
.skel.w90 { width: 90%; } .skel.w75 { width: 75%; } .skel.w60 { width: 60%; } .skel.w45 { width: 45%; }
@keyframes shine { to { background-position: -200% 0; } }
</style>
