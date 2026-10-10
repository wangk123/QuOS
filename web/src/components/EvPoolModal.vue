<script setup lang="ts">
// 证据池弹窗：追加材料（点击/拖拽/⌘V）/ 删除 / 重新生成两模式入口（full/smart）。
// 数据由父级传入（App 持有 evidence 供顶栏角标复用），增删后 emit('changed') 父级重拉。
import { inject, onUnmounted, ref, watch } from 'vue'
import { ApiError, addEvidenceFile, deleteEvidence, type EvidenceItem } from '../api'

const props = defineProps<{ open: boolean; evidence: EvidenceItem[] }>()
const emit = defineEmits<{
  close: []
  changed: []
  /** 重新生成两模式：full=全量重跑 / smart=智能生成（疑点直处+自动范围重组） */
  regen: [mode: 'full' | 'smart']
}>()

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const fileInput = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const busy = ref(false)

const evMeta: Record<string, string> = {
  仓库: 'b-blue',
  文本: 'b-amber',
  截图: 'b-amber',
  文档: 'b-gray',
  压缩包: 'b-gray',
}

async function uploadFiles(files: File[]) {
  if (busy.value || !files.length) return
  busy.value = true
  try {
    for (const f of files) await addEvidenceFile(f)
    toast(`${files.length} 个文件已入池`, 'ok')
    emit('changed')
  } catch (e) {
    toast(e instanceof ApiError ? `入池失败：${e.message}` : '入池失败', 'warn')
  } finally {
    busy.value = false
  }
}

function onPick(e: Event) {
  const el = e.target as HTMLInputElement
  if (el.files?.length) void uploadFiles([...el.files])
  el.value = '' // 清空以便重复选同名文件
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  const files = [...(e.dataTransfer?.files ?? [])]
  if (files.length) void uploadFiles(files)
}

/** ⌘V 截图/文件：同 Landing 模式接管 window 粘贴——弹窗打开时才挂、关闭即移除（防与待确认弹窗双投递） */
function onPaste(e: ClipboardEvent) {
  const files = [...(e.clipboardData?.files ?? [])]
  if (files.length) void uploadFiles(files)
}
watch(
  () => props.open,
  v => {
    if (v) window.addEventListener('paste', onPaste)
    else window.removeEventListener('paste', onPaste)
  },
  { immediate: true },
)
onUnmounted(() => window.removeEventListener('paste', onPaste))

async function remove(ev: EvidenceItem) {
  const hint = ev.state === 'extracted' ? `，其提取的 ${ev.count} 条规则将一并移除` : ''
  if (!confirm(`删除《${ev.name}》${hint}？`)) return
  try {
    await deleteEvidence(ev.id)
    toast(`已删除《${ev.name}》`, 'ok')
    emit('changed')
  } catch (e) {
    toast(e instanceof ApiError ? `删除失败：${e.message}` : '删除失败', 'warn')
  }
}
</script>

<template>
  <div class="mask" :class="{ open }" @click.self="$emit('close')">
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>证据池 <span class="badge b-gray">{{ evidence.length }} 份</span></h3>
        <div class="msub">补充材料后重新生成——已整理的结果保留，新内容增量并入</div>
        <button class="x" type="button" aria-label="关闭" @click="$emit('close')">✕</button>
      </div>
      <div class="modal-body">
        <div
          class="dropmini"
          :class="{ over: dragOver }"
          role="button"
          aria-label="追加材料"
          @click="fileInput?.click()"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="onDrop"
        >{{ busy ? '入池中…' : '拖入 / ⌘V / 点击上传，追加材料' }}</div>
        <input ref="fileInput" type="file" multiple hidden aria-label="追加材料文件" @change="onPick" />

        <div v-for="e in evidence" :key="e.id" class="evrow">
          <span class="nm">{{ e.name }}</span>
          <span v-if="e.source === 'clar'" class="badge b-amber">澄清补料</span>
          <span class="badge" :class="evMeta[e.type] ?? 'b-gray'">{{ e.type }}</span>
          <span class="st">{{ '★'.repeat(e.stars) || '?' }}</span>
          <span class="badge" :class="e.state === 'extracted' ? 'b-green' : 'b-gray'">
            {{ e.state === 'extracted' ? '已并入需求' : '未生成' }}
          </span>
          <button class="x" type="button" title="移除" :aria-label="`移除 ${e.name}`" @click="remove(e)">✕</button>
        </div>
        <div v-if="!evidence.length" class="evrow" style="color: var(--muted-fg)">池是空的——拖文件 / ⌘V / 点击上方框追加</div>
      </div>
      <div class="modal-foot">
        <button class="btn" type="button" @click="$emit('regen', 'full')">↻ 全量重新生成</button>
        <button class="btn btn-accent2" type="button" @click="$emit('regen', 'smart')">✦ 智能生成</button>
        <span class="fnote">智能生成自动核验遗留待处理疑点、自动判断受影响模块并重组</span>
      </div>
    </div>
  </div>
</template>
