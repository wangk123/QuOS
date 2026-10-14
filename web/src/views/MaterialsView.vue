<!-- 材料页:拖拽/点击上传(hash 去重 409 提示)、列表、解析文本 drawer -->
<script setup lang="ts">
import { ref } from 'vue'
import { listMaterials, uploadMaterial, ApiError, type Material } from '../api'
import { route } from '../router'
import { toast } from '../components/toast'

const materials = ref<Material[]>([])
const selected = ref<number | null>(null)
const preview = ref<Material | null>(null)
const dragover = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

async function refresh() {
  materials.value = await listMaterials(route.pid)
}
refresh()

async function upload(files: FileList | File[] | null) {
  if (!files) return
  for (const f of Array.from(files)) {
    try {
      const m = await uploadMaterial(route.pid, f)
      toast(`已接收 ${m.filename},解析完成`)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast(`材料已存在(hash 相同),原记录 #${e.detail?.material_id ?? '?'}`, 'warn')
      } else throw e
    }
  }
  refresh()
}

function onDrop(e: DragEvent) {
  dragover.value = false
  upload(e.dataTransfer?.files ?? null)
}
function guessType(m: Material): string {
  return ({ pdf: 'pdf', md: 'md', txt: 'txt', png: 'img', jpg: 'img', jpeg: 'img', webp: 'img' } as any)[m.type] ?? 'txt'
}
function statusTag(m: Material) {
  if (m.parsed_text) return { cls: 'ok', label: '已解析' }
  if (guessType(m) === 'img') return { cls: 'mute', label: '图片 · 无文本' }
  return { cls: 'warn', label: '无文本' }
}
function openPreview(m: Material) {
  selected.value = m.id
  preview.value = m
}
function fmtSize(n: number): string {
  return n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}
</script>

<template>
  <div class="content">
    <div class="page-head">
      <div>
        <h1 class="pv">材料</h1>
        <div class="pv-sub">证据池:只增不改,hash 去重;解析文本供出处核对</div>
      </div>
    </div>
    <div class="upload-zone" :class="{ dragover }" tabindex="0" role="button" aria-label="上传材料"
         @click="fileInput?.click()" @keydown.enter.prevent="fileInput?.click()"
         @dragover.prevent="dragover = true" @dragleave="dragover = false" @drop.prevent="onDrop">
      <b>拖拽文件到此处,或点击选择</b>
      <span class="hint">PDF / Markdown / TXT / 图片 · hash 相同的重复文件将被拒绝</span>
    </div>
    <input ref="fileInput" type="file" multiple hidden @change="upload(($event.target as any).files); ($event.target as any).value = ''" />
    <div class="card">
      <table class="tbl">
        <thead><tr><th>文件</th><th>类型</th><th>SHA-256(前 12)</th><th>大小</th><th>上传时间</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="m in materials" :key="m.id" class="clickable" :class="{ 'row-sel': selected === m.id }" @click="openPreview(m)">
            <td style="display: flex; gap: 9px; align-items: center">
              <span style="color: var(--faint)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
              </span>
              <span style="font-weight: 500">{{ m.filename }}</span>
            </td>
            <td><span class="mt" :class="guessType(m)">{{ m.type.toUpperCase() }}</span></td>
            <td><span class="hash">{{ m.sha256.slice(0, 12) }}</span></td>
            <td style="color: var(--muted); font-size: 0.83rem">{{ fmtSize(m.size) }}</td>
            <td style="color: var(--muted); font-size: 0.83rem">{{ m.created_at.slice(0, 16).replace('T', ' ') }}</td>
            <td><span class="tag" :class="statusTag(m).cls"><span class="dot" />{{ statusTag(m).label }}</span></td>
          </tr>
          <tr v-if="!materials.length"><td colspan="6"><div class="empty">还没有材料</div></td></tr>
        </tbody>
      </table>
    </div>

    <!-- 解析文本抽屉 -->
    <teleport to="body">
      <div v-if="preview" class="drawer-mask" @click="preview = null" />
      <div v-if="preview" class="drawer">
        <div class="dr-head">
          <h3>{{ preview.filename }}</h3>
          <button class="icon-btn" aria-label="关闭" @click="preview = null">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
          </button>
        </div>
        <div class="dr-meta">
          <span class="hash">{{ preview.sha256.slice(0, 12) }}</span>
          <span>{{ fmtSize(preview.size) }}</span>
          <span class="mt" :class="guessType(preview)">{{ preview.type.toUpperCase() }}</span>
        </div>
        <div class="dr-body">
          <div v-if="preview.parsed_text">
            <div class="sl" style="margin-top: 0">解析文本(parsed_text)</div>
            <div class="parsed">{{ preview.parsed_text }}</div>
          </div>
          <div v-else class="empty">图片材料:解析文本为空,规则引用本材料时跳过出处硬校验</div>
        </div>
      </div>
    </teleport>
  </div>
</template>
