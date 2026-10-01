<script setup lang="ts">
// Task 6 空项目导入态：整页大导入框 + 材料列表 + 生成需求入口。
// 拖拽 / ⌘V / 批量上传 / 回车入池 / 删除等交互（原五步材料视图能力收口于此）。
import { inject, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ApiError,
  addEvidence,
  addEvidenceFile,
  deleteEvidence,
  generateReq,
  getEvidence,
  type EvidenceItem,
} from '../api'
import { startJobPolling } from '../jobs'

const emit = defineEmits<{ generated: [] }>()
const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<EvidenceItem[]>([])
const err = ref('')
const raw = ref('')
const over = ref(false)
const generating = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

/** 材料行类型徽章配色 */
const evMeta: Record<string, string> = {
  仓库: 'b-blue',
  文本: 'b-amber',
  截图: 'b-amber',
  文档: 'b-gray',
  压缩包: 'b-gray',
}

async function load() {
  items.value = await getEvidence()
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : '无法连接后端——请先启动 server'
  }
  window.addEventListener('paste', onPaste)
})
onBeforeUnmount(() => window.removeEventListener('paste', onPaste))

/** 文本 / git 地址回车入池 */
async function smartAdd() {
  const v = raw.value.trim()
  if (!v) {
    toast('先粘贴或输入内容（文本 / git 地址）')
    return
  }
  try {
    const ev = await addEvidence(v)
    raw.value = ''
    await load()
    toast(ev.type === '仓库' ? `识别为仓库，已挂载${ev.ext}` : '识别为文本，已入池（项目级）', 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `入池失败：${e.message}` : '入池失败', 'warn')
  }
}

/** 文件批量上传 */
async function uploadFiles(files: File[]) {
  if (!files.length) return
  try {
    for (const f of files) await addEvidenceFile(f)
    await load()
    toast(`${files.length} 个文件已入池`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `入池失败：${e.message}` : '入池失败', 'warn')
  }
}

function onDrop(e: DragEvent) {
  over.value = false
  const files = [...(e.dataTransfer?.files ?? [])]
  if (files.length) void uploadFiles(files)
}

function onFileChange(e: Event) {
  const files = [...(((e.target as HTMLInputElement).files ?? []) as File[])]
  if (e.target instanceof HTMLInputElement) e.target.value = ''
  if (files.length) void uploadFiles(files)
}

/** ⌘V 截图：剪贴板含 image 时转 Blob 上传（澄清池弹窗内让位防双投递） */
async function onPaste(e: ClipboardEvent) {
  if (e.target instanceof Element && e.target.closest('.drawer')) return
  const img = [...(e.clipboardData?.items ?? [])].find(i => i.type.startsWith('image/'))
  if (!img) return
  const f = img.getAsFile()
  if (f) await uploadFiles([f])
}

/** 删除材料：已提取的材料连带规则移除，confirm 交互防误删（无撤销机制） */
async function remove(id: string) {
  const ev = items.value.find(x => x.id === id)
  if (!ev) return
  const hint = ev.state === 'extracted' ? `，其提取的 ${ev.count} 条规则将一并移除` : ''
  if (!confirm(`删除《${ev.name}》${hint}？`)) return
  try {
    await deleteEvidence(id)
    await load()
    toast(`已删除《${ev.name}》`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `删除失败：${e.message}` : '删除失败', 'warn')
  }
}

/** 一键生成需求：后台 job 轮询进度，发起成功即通知父级切工作台态 */
async function generate() {
  if (!items.value.length || generating.value) return
  generating.value = true
  try {
    const r = await generateReq()
    startJobPolling(r.job_id, toast)
    emit('generated')
  } catch (e) {
    toast(e instanceof ApiError ? `生成失败：${e.message}` : '生成失败', 'warn')
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <div class="landing">
    <h1>把需求的材料丢进来</h1>
    <p class="sub">多烂都行——文档、聊天记录、截图、git 仓库、甚至一句话。生成需求之后随时可以再补。</p>
    <p v-if="err" class="err">{{ err }}</p>

    <div
      class="bigdrop"
      :class="{ over }"
      aria-label="导入材料"
      @click="fileInput?.click()"
      @dragover.prevent="over = true"
      @dragleave="over = false"
      @drop.prevent="onDrop"
    >
      <h3>拖拽材料到这里 · 或点击选择 · ⌘V 粘贴</h3>
      <p>支持批量，一次丢完</p>
      <div class="types">
        <span class="badge b-gray">文档</span><span class="badge b-amber">聊天记录</span><span class="badge b-amber">截图</span><span class="badge b-blue">git 仓库</span><span class="badge b-gray">一句话想法</span>
      </div>
      <input
        v-model="raw"
        class="drop-input"
        placeholder="或粘贴 / 输入：文本 · 聊天记录 · git 仓库地址（回车入池）"
        aria-label="文本材料输入"
        @click.stop
        @keydown.enter.prevent="smartAdd"
      />
    </div>
    <input ref="fileInput" type="file" multiple hidden @change="onFileChange" />

    <div v-if="items.length" class="evlist">
      <div class="hd">
        材料 <span class="badge b-gray">{{ items.length }} 份</span><span class="spacer"></span>
        <span class="tail">删错了没关系，之后随时补</span>
      </div>
      <div v-for="e in items" :key="e.id" class="evrow">
        <span class="nm" :title="e.name">{{ e.name }}</span>
        <span class="badge" :class="evMeta[e.type] ?? 'b-gray'">{{ e.type }}</span>
        <span class="st">{{ '★'.repeat(e.stars) || '?' }}</span>
        <span v-if="e.missing" class="badge b-red">文件丢失</span>
        <button class="x" type="button" title="移除" :aria-label="`移除 ${e.name}`" @click="remove(e.id)">✕</button>
      </div>
      <div class="dropmini">继续拖入 / ⌘V 追加材料</div>
    </div>

    <div class="genbar">
      <button class="btn-gen" type="button" :disabled="!items.length || generating" @click="generate">✦ 生成需求</button>
      <span class="note">生成后材料收进顶栏「证据池」，随时点开补充、重新生成</span>
    </div>
  </div>
</template>
