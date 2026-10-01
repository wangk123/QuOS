<script setup lang="ts">
// 版本弹窗（T14）：版本时间线 / 存为版本 / 预览导出需求文档。终态唯一版本入口（v-base 视图 T19 已删），数据源 listBaselines。
import { inject, ref, watch } from 'vue'
import { ApiError, createBaseline, getDoc, listBaselines, type Baseline } from '../api'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  close: []
  /** 存版成功——父级重拉基线 */
  saved: []
}>()

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<Baseline[]>([])
const err = ref('')
const saving = ref(false)
const docOpen = ref(false)
const docText = ref('')

async function load() {
  items.value = await listBaselines()
}

// 仅打开时拉取；immediate 兼容首挂即 open
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

const isCur = (i: number) => i === items.value.length - 1 // 列表末项 = 当前
const vmeta = (b: Baseline) => [b.time, b.note, b.commit && b.commit.slice(0, 7)].filter(Boolean).join(' · ')

async function save() {
  if (saving.value) return
  const note = window.prompt('版本说明（可空）：留底原因 / 本版要点', '')
  if (note === null) return // 取消不存
  saving.value = true
  try {
    const r = await createBaseline(note.trim() || undefined) // 空 note 走 api 默认「基线存档」
    toast(`已存为 ${r.tag}`, 'ok')
    emit('saved')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? `存版失败：${e.message}` : '存版失败', 'warn')
  } finally {
    saving.value = false
  }
}

async function preview() {
  try {
    docText.value = await getDoc()
    docOpen.value = true
  } catch (e) {
    toast(e instanceof ApiError ? `导出失败：${e.message}` : '导出失败', 'warn')
  }
}

function download() {
  const url = URL.createObjectURL(new Blob([docText.value], { type: 'text/markdown' }))
  const a = document.createElement('a')
  a.href = url
  a.download = '需求文档.md'
  a.click()
  URL.revokeObjectURL(url)
  toast('已下载 需求文档.md', 'ok')
}
</script>

<template>
  <div class="mask" :class="{ open }" @click.self="$emit('close')">
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>版本</h3>
        <div class="msub">需求文档的存档历史——可回看、可对比，随时存一版留底</div>
        <button class="x" type="button" aria-label="关闭" @click="$emit('close')">✕</button>
      </div>
      <div class="modal-body">
        <p v-if="err" class="err">{{ err }}</p>
        <div v-if="items.length" class="vtl">
          <div v-for="(b, i) in items" :key="b.tag" class="vitem" :class="{ cur: isCur(i) }">
            <h4>{{ b.tag }} <span v-if="isCur(i)" class="badge b-green">当前</span></h4>
            <div class="vmeta">{{ vmeta(b) }}</div>
          </div>
        </div>
        <div v-else class="v-empty">还没有版本——需要留底时点存为版本</div>
      </div>
      <div class="modal-foot">
        <button class="btn" type="button" :disabled="saving" @click="save">{{ saving ? '存档中…' : '存为版本' }}</button>
        <button class="btn-ghost" type="button" @click="preview">预览 / 导出需求文档</button>
      </div>
    </div>
  </div>

  <!-- 二级弹层：导出预览（DOM 在主弹窗后，同 z-index 自然盖在上层） -->
  <div v-if="docOpen" class="mask open" @click.self="docOpen = false">
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>需求文档 · 导出预览</h3>
        <div class="msub">总览开篇 + 按树分层——整份需求一份文档，给评审/开发直接看</div>
        <button class="x" type="button" aria-label="关闭预览" @click="docOpen = false">✕</button>
      </div>
      <div class="modal-body"><pre class="doc-outline">{{ docText }}</pre></div>
      <div class="modal-foot">
        <button class="btn" type="button" @click="download">下载 .md</button>
        <button class="btn-ghost" type="button" @click="docOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
