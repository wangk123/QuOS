<script setup lang="ts">
import { inject, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ApiError,
  addEvidence,
  addEvidenceFile,
  extractEvidence,
  getEvidence,
  type EvidenceItem,
} from '../api'
import { goto } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<EvidenceItem[]>([])
const err = ref('')
const raw = ref('')
const aiLabel = ref('') // AI 请求中的假进度条文案
const over = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const evMeta: Record<string, [string, string]> = {
  仓库: ['b-blue', '仓库'],
  文本: ['b-amber', '文本'],
  截图: ['b-amber', '截图'],
  文档: ['b-gray', '文档'],
  压缩包: ['b-gray', '压缩包'],
}

async function load() {
  items.value = await getEvidence()
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
  }
  window.addEventListener('paste', onPaste)
})
onBeforeUnmount(() => window.removeEventListener('paste', onPaste))

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

/** ⌘V 截图：剪贴板含 image 时转 Blob 上传 */
async function onPaste(e: ClipboardEvent) {
  const img = [...(e.clipboardData?.items ?? [])].find(i => i.type.startsWith('image/'))
  if (!img) return
  const f = img.getAsFile()
  if (f) await uploadFiles([f])
}

async function extract(id: string) {
  const ev = items.value.find(x => x.id === id)
  if (!ev || ev.state === 'extracted') return
  aiLabel.value = `AI 正在读《${ev.name}》提炼行为断言…`
  try {
    const r = await extractEvidence(id)
    toast(`+${r.added} 条断言 · 出处已标注`, 'ok')
    await load()
    goto('v-fact') // 跳到 ① 提事实查看新断言
  } catch (e) {
    toast(e instanceof ApiError ? `提取失败：${e.message}` : '提取失败', 'warn')
  } finally {
    aiLabel.value = ''
  }
}

const stat = {
  total: () => items.value.length,
  repo: () => items.value.filter(e => e.type === '仓库').length,
  ai: () => items.value.filter(e => e.type === 'AI生成').length,
  extracted: () => items.value.filter(e => e.state === 'extracted').length,
}
</script>

<template>
  <div>
    <div class="view-head">
      <h2>证据池</h2>
      <span class="sub">项目级材料库——文本、截图、文档、压缩包、仓库，先入池；整理节点时来挑。</span>
    </div>

    <div class="smart-input" :class="{ over }" @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
      <button class="att" type="button" title="选择文件" aria-label="选择文件" @click="fileInput?.click()">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21.4 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
        </svg>
      </button>
      <input
        v-model="raw"
        placeholder="粘贴 / 输入：文本 · 聊天记录 · git 仓库地址（自动识别）——文件直接拖进本框"
        aria-label="智能输入"
        @keydown.enter.prevent="smartAdd"
      />
      <button class="btn" type="button" @click="smartAdd">入池</button>
      <input ref="fileInput" type="file" multiple hidden @change="onFileChange" />

    </div>
    <div class="smart-hint">
      <span><b>文本</b>→文字材料</span><span><b>截图</b>→⌘V 直接入池</span><span><b>git@… / xxx.git</b>→自动挂仓库</span><span><b>拖文件</b>→按扩展名归类</span>
    </div>

    <p v-if="err" class="err">{{ err }}</p>
    <div class="statbar">
      <div class="stat"><b>{{ stat.total() }}</b><span>池内材料</span></div>
      <div class="stat"><b>{{ stat.repo() }}</b><span>代码仓库</span></div>
      <div class="stat warn"><b>{{ stat.ai() }}</b><span>AI 生成（警示）</span></div>
      <div class="stat okc"><b>{{ stat.extracted() }}</b><span>已提取</span></div>
    </div>

    <div v-if="aiLabel" class="ai-run">
      <span class="spin" /><span>{{ aiLabel }}</span><div class="bar"><i /></div>
    </div>

    <div class="card-box">
      <div class="hd">材料清单（项目级）</div>
      <table>
        <thead>
          <tr>
            <th>材料</th><th>类型</th><th>可信度</th><th>登记</th><th>状态</th><th style="width: 110px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in items" :key="e.id" :class="{ 'ev-danger': e.type === 'AI生成' }">
            <td><span style="font-family: var(--mono)">{{ e.name }}</span> <span v-if="e.ext" class="src">{{ e.ext }}</span></td>
            <td><span class="badge" :class="(evMeta[e.type] ?? evMeta['文档'])[0]">{{ e.type }}{{ e.type === 'AI生成' ? ' ⚠' : '' }}</span></td>
            <td>{{ '★'.repeat(e.stars) || '?' }}</td>
            <td><span class="src">{{ e.reg }}</span></td>
            <td>
              <span v-if="e.state === 'extracted'" class="badge b-green">已提取 {{ e.count }}</span>
              <span v-else class="badge b-gray">未提取</span>
              <span v-if="e.missing" class="badge b-red">文件丢失</span>
            </td>
            <td class="row-actions">
              <button class="btn btn-sm" type="button" :disabled="e.state === 'extracted'" @click="extract(e.id)">提取</button>
            </td>
          </tr>
          <tr v-if="!items.length">
            <td colspan="6" style="color: var(--muted-fg); padding: 24px; text-align: center">池是空的——上方输入框粘贴文本 / git 地址，⌘V 截图或拖文件进来</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="warn-strip">
      <b>入库规则</b>AI 生成的材料标红：格式漂亮 ≠ 内容真实，提取断言一律「待实证」。口头/截图不登记就永远丢了——先入池。
    </div>
  </div>
</template>

<style scoped>
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
</style>
