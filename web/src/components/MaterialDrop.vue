<script setup lang="ts">
import { inject, onMounted, onUnmounted, ref } from 'vue'
import { ApiError, addEvidenceFile, reviewClars, type EvidenceItem } from '../api'
import { startJobPolling } from '../jobs'

// 材料投递条：选择 / 拖拽 / 粘贴三通道入池（source=clar），随后发起澄清重检后台任务。
const emit = defineEmits<{ submitted: [evIds: string[]] }>()
const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const fileInput = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const busy = ref(false)
const MAX_SIZE = 10 * 1024 * 1024

function onPick(e: Event) {
  const el = e.target as HTMLInputElement
  if (el.files?.length) void submitFiles(el.files)
  el.value = '' // 清空以便重复选同名文件
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  if (e.dataTransfer?.files.length) void submitFiles(e.dataTransfer.files)
}

function onPaste(e: ClipboardEvent) {
  // 仅接管焦点在抽屉内的粘贴：抽屉外的粘贴归证据池视图的 window 级 handler，避免双投递
  if (!(e.target instanceof Element) || !e.target.closest('.drawer')) return
  const files = e.clipboardData?.files
  if (files?.length) void submitFiles(files)
}

async function submitFiles(list: FileList | File[]) {
  if (busy.value) return
  const files = [...list].filter(f => {
    if (f.size > MAX_SIZE) {
      toast(`文件超过 10MB：${f.name}`, 'warn')
      return false
    }
    return true
  })
  if (!files.length) return
  busy.value = true
  try {
    const evs: EvidenceItem[] = []
    for (const f of files) evs.push(await addEvidenceFile(f, 'clar'))
    const { job_id } = await reviewClars(evs.map(e => e.id))
    startJobPolling(job_id, toast)
    emit('submitted', evs.map(e => e.id))
  } catch (e) {
    toast(e instanceof ApiError ? `投递失败：${e.message}` : '投递失败', 'warn')
  } finally {
    busy.value = false
  }
}

// 仅挂载期间监听 document 粘贴（本体随抽屉 v-if 存在，关闭即卸载清理）
onMounted(() => document.addEventListener('paste', onPaste))
onUnmounted(() => document.removeEventListener('paste', onPaste))
</script>

<template>
  <div
    class="mdrop"
    :class="{ over: dragOver }"
    @dragover.prevent="dragOver = true"
    @dragleave.prevent="dragOver = false"
    @drop.prevent="onDrop"
  >
    <input ref="fileInput" type="file" multiple class="mdrop-file" aria-label="选择材料文件" @change="onPick" />
    <button class="btn btn-sm" type="button" :disabled="busy" @click="fileInput?.click()">
      {{ busy ? '投递中…' : '补材料 · AI 重检' }}
    </button>
    <span class="hint">选择 / 拖拽 / 粘贴文件到抽屉内，AI 用材料代答待问项（单份 ≤10MB）</span>
  </div>
</template>

<style scoped>
.mdrop { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 12px; margin: 10px 0 0;
  border: 1px dashed var(--border2); border-radius: 8px; background: #fafbfd; }
.mdrop.over { border-color: var(--primary); background: var(--blue-bg); }
.mdrop-file { display: none; }
.hint { font-size: 11.5px; color: var(--muted-fg); }
</style>
