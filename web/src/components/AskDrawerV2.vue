<script setup lang="ts">
import { computed, inject, onUnmounted, ref, watch } from 'vue'
import { ApiError, getClarifications, type Clarification } from '../api'
import { jobRunning } from '../jobs'
import ClarCard from './ClarCard.vue'
import MaterialDrop from './MaterialDrop.vue'

// 澄清池抽屉：tabs / 列表 / 导出编排；单题渲染与作答在 ClarCard，材料投递在 MaterialDrop。
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  close: []
  changed: []
}>()

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<Clarification[]>([])
const tab = ref<'wait' | 'done' | 'all'>('wait')
const showExport = ref(false)
const err = ref('')

// 旧数据无 kind：按 opts 兜底（有选项=选择题，无选项=开放题）
async function load() {
  items.value = (await getClarifications()).map(c => ({
    ...c,
    kind: c.kind ?? (c.opts.length ? 'choice' : 'open'),
  }))
}

// 抽屉仅在打开时拉取；immediate 兼容首挂即 open 的场景
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
const shown = computed(() =>
  tab.value === 'wait' ? waiting.value : tab.value === 'done' ? done.value : items.value,
)

// 单题有落定（作答/采纳/忽略/标记）→ 重拉列表并通知外层刷新角标
async function reload() {
  await load().catch(() => {}) // 重拉失败保持现状，不打断交互
  emit('changed')
}

// 材料已投递、重检任务已启动：一次性监听 jobRunning 转 false（任务完成）后重拉列表
// （watch 在事件处理器中创建、不随实例自动停止，卸载时须显式清理）
let unwatchJob: (() => void) | null = null
function onSubmitted(evIds: string[]) {
  toast(`已投递 ${evIds.length} 份材料，AI 重检进行中…`)
  unwatchJob?.()
  unwatchJob = watch(jobRunning, (v, o) => {
    if (!v && o) {
      unwatchJob?.()
      unwatchJob = null
      void reload()
    }
  })
}
onUnmounted(() => {
  unwatchJob?.()
  unwatchJob = null
})

const exportText = computed(() => {
  const w = waiting.value
  const choice = w.filter(c => c.kind === 'choice')
  const open = w.filter(c => c.kind === 'open')
  const lines: string[] = [`【需求确认 ×${w.length}】本批，麻烦一次性回我：`]
  if (choice.length) {
    lines.push('—— 选择题（回编号+选项字母）——')
    choice.forEach(c =>
      lines.push(`${c.no}. ${c.q}\n   ${c.opts.map((o, i) => String.fromCharCode(65 + i) + '. ' + o).join('  ')}`),
    )
  }
  if (open.length) {
    lines.push('—— 需补充材料（回编号+内容，可直接粘贴原文）——')
    open.forEach(c => lines.push(`${c.no}. ${c.q}`))
  }
  return lines.join('\n')
})
</script>

<template>
  <div v-if="open" class="drawer-bg" @click.self="$emit('close')">
    <div class="drawer" role="dialog" aria-modal="true">
      <p v-if="err" class="err">{{ err }}</p>
      <div class="dw2">
      <div class="dw2-hd">
        <h3>
          澄清池 <span class="src">{{ items.length }} 项 · 待问 {{ waiting.length }}</span>
        </h3>
        <button class="ghost" type="button" aria-label="关闭" @click="$emit('close')">✕</button>
      </div>
      <p class="dw2-sub">
        攒一批一次问。选择题回字母，<b>补材料题</b>回文本或粘贴原文——①无依据规则、②冲突、④缺口的存疑项都汇到这里。
      </p>

      <div class="dw2-tabs">
        <button
          v-for="t in ([['wait', `待问 ${waiting.length}`], ['done', `已答 ${done.length}`], ['all', `全部 ${items.length}`]] as const)"
          :key="t[0]"
          class="tab"
          :class="{ on: tab === t[0] }"
          type="button"
          @click="tab = t[0]"
        >{{ t[1] }}</button>
        <span class="spacer" />
        <button class="btn btn-sm" type="button" :disabled="!waiting.length" @click="showExport = !showExport">
          导出提问文本（发 IM）
        </button>
      </div>

      <MaterialDrop @submitted="onSubmitted" />

      <div class="dw2-list">
        <ClarCard
          v-for="c in shown"
          :key="c.no"
          :c="c"
          @answered="reload"
          @adopted="reload"
          @ignored="reload"
          @verified="reload"
        />

        <div v-if="!shown.length" class="dw2-empty">
          {{ tab === 'wait' ? '没有待问项——②冲突、④缺口、①无依据规则可转到这里' : '暂无记录' }}
        </div>
      </div>

      <div v-if="showExport" class="dw2-export">
        <div class="hd">导出预览（复制发 IM）</div>
        <div class="q-export">{{ exportText }}</div>
      </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.drawer-bg { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 90; }
.drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(880px, 94vw);
  background: #fff; box-shadow: -4px 0 24px rgba(0,0,0,.12); padding: 16px 20px;
  overflow: hidden; display: flex; flex-direction: column; }
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
.dw2 { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.dw2-hd { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.dw2-hd h3 { display: flex; align-items: center; gap: 8px; font-size: 15px; flex-wrap: wrap; }
.dw2-sub { font-size: 12px; color: var(--muted-fg); margin: 6px 0 12px; }
.dw2-tabs { display: flex; align-items: center; gap: 6px; padding-bottom: 12px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.tab { background: #fff; border: 1px solid var(--border2); color: var(--muted-fg); padding: 5px 12px; border-radius: 999px; font-size: 12px; }
.tab.on { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; }
.dw2-list { flex: 1; overflow-y: auto; padding: 12px 2px 12px 0; display: flex; flex-direction: column; gap: 10px; }

.dw2-empty { padding: 40px; text-align: center; color: var(--muted-fg); border: 1px dashed var(--border2); border-radius: var(--radius); }
.dw2-export { border-top: 1px solid var(--border); padding-top: 10px; }
.dw2-export .hd { font-weight: 600; font-size: 12.5px; margin-bottom: 4px; }
</style>
