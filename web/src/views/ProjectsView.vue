<!-- 项目总览:表格(项目版本/项目状态列) + 新建/编辑(含状态与版本) + 删除 -->
<script setup lang="ts">
import { ref } from 'vue'
import { ApiError, createProject, deleteProject, listProjects, patchProject, type Project } from '../api'
import AppModal from '../components/AppModal.vue'
import { toast } from '../components/toast'

// 项目状态(治理开关)与合法转移,镜像后端 TRANSITIONS
const STATUS_META: Record<string, { label: string; cls: string; hint: string }> = {
  in_progress: { label: '进行中', cls: 'ok', hint: '进行中(写权限全开)' },
  paused: { label: '已暂停', cls: 'warn', hint: '已暂停(只读 · 可恢复)' },
  closed: { label: '已结项', cls: 'mute', hint: '已结项(只读 · 可重开)' },
}
const TRANSITIONS: Record<string, string[]> = {
  in_progress: ['paused', 'closed'],
  paused: ['in_progress', 'closed'],
  closed: ['in_progress'],
}
const XV = /^\d+\.\d+\.\d+$/

const projects = ref<Project[]>([])
let editing: Project | null = null

const modal = ref<null | 'form'>(null)
const form = ref({ name: '', description: '', version: '1.0.0', status: 'in_progress' })
const nameErr = ref('')
const verErr = ref('')
const deleting = ref<Project | null>(null)
// 编辑弹窗状态可选项=当前状态+合法可达态
const statusOptions = ref<string[]>([])

async function refresh() {
  projects.value = await listProjects()
  // 侧栏与项目列表页只在切页时自刷,增删改后主动通知,避免残留死链接
  window.dispatchEvent(new Event('quos:projects-changed'))
}
refresh()

function openCreate() {
  editing = null
  form.value = { name: '', description: '', version: '1.0.0', status: 'in_progress' }
  statusOptions.value = ['in_progress', 'paused', 'closed']
  nameErr.value = ''
  verErr.value = ''
  modal.value = 'form'
}
function openEdit(p: Project) {
  editing = p
  form.value = { name: p.name, description: p.description, version: p.version, status: p.status }
  statusOptions.value = [p.status, ...TRANSITIONS[p.status]]
  nameErr.value = ''
  verErr.value = ''
  modal.value = 'form'
}
async function save() {
  const name = form.value.name.trim()
  nameErr.value = ''
  verErr.value = ''
  if (!name) {
    nameErr.value = '名称必填'
    return
  }
  // 前端预判重名(后端 409 兜底)
  if (projects.value.some((p) => p.name === name && p !== editing)) {
    nameErr.value = '项目名称已存在'
    return
  }
  if (!XV.test(form.value.version.trim())) {
    verErr.value = '版本号须为 x.x.x 格式(如 1.2.0)'
    return
  }
  try {
    if (editing) {
      await patchProject(editing.id, {
        name, description: form.value.description,
        version: form.value.version.trim(), status: form.value.status,
      })
      toast('项目已更新')
    } else {
      await createProject(name, form.value.description)
      toast('项目已创建')
    }
    modal.value = null
    refresh()
  } catch (e) {
    const d = e instanceof ApiError ? e.detail?.code : ''
    if (d === 'DUP_NAME') nameErr.value = '项目名称已存在'
    else if (d === 'VERSION_FORMAT') verErr.value = '版本号须为 x.x.x 格式(如 1.2.0)'
    else if (d === 'PROJECT_READ_ONLY') toast('项目只读:请先恢复/重开再编辑内容', 'warn')
    else throw e
  }
}
function askDelete(p: Project) {
  deleting.value = p
}
async function doDelete() {
  const p = deleting.value!
  await deleteProject(p.id)
  toast(`「${p.name}」已删除`)
  deleting.value = null
  refresh()
}
</script>

<template>
  <div class="content">
    <div class="page-head">
      <div>
        <h1 class="pv">项目总览</h1>
        <div class="pv-sub">平台按项目隔离资源:材料池、文档与批注、版本历史</div>
      </div>
      <div class="spacer" />
      <button class="btn primary" @click="openCreate">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
        新建项目
      </button>
    </div>
    <div class="card">
      <table class="tbl">
        <thead>
          <tr>
            <th>项目</th><th>材料</th><th>批注</th><th>项目版本</th><th>项目状态</th><th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in projects" :key="p.id">
            <td>
              <div style="font-weight: 600">{{ p.name }}</div>
              <div style="color: var(--muted); font-size: 0.8rem; max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ p.description }}</div>
            </td>
            <td><span class="num">{{ p.stats.materials }}</span></td>
            <td>
              <span v-if="p.stats.pending_annos" class="tag warn"><span class="dot" />{{ p.stats.pending_annos }} 待评审</span>
              <span v-else class="tag mute"><span class="dot" />0</span>
            </td>
            <td><span class="num">{{ p.version }}</span></td>
            <td>
              <span class="tag" :class="STATUS_META[p.status]?.cls ?? 'mute'"><span class="dot" />{{ STATUS_META[p.status]?.label ?? p.status }}</span>
            </td>
            <td style="white-space: nowrap; text-align: right">
              <a class="btn sm primary" :href="`#/p/${p.id}/review`" style="text-decoration: none">进入</a>
              <button class="btn sm" @click="openEdit(p)">编辑</button>
              <button class="btn sm danger" @click="askDelete(p)">删除</button>
            </td>
          </tr>
          <tr v-if="!projects.length">
            <td colspan="6"><div class="empty">尚无项目,点击右上角新建</div></td>
          </tr>
        </tbody>
      </table>
    </div>

    <AppModal v-if="modal === 'form'" :title="editing ? '编辑项目' : '新建项目'" @close="modal = null">
      <div class="field" :class="{ invalid: nameErr }">
        <label>项目名称 <span class="req">*</span></label>
        <input v-model="form.name" type="text" placeholder="如:多模态" />
        <div class="err-msg">{{ nameErr }}</div>
      </div>
      <div class="field" :class="{ invalid: verErr }">
        <label>项目版本</label>
        <input v-model="form.version" type="text" placeholder="如 1.2.0" />
        <div class="err-msg">{{ verErr }}</div>
      </div>
      <div v-if="editing" class="field">
        <label>项目状态</label>
        <select v-model="form.status" style="width: 100%; padding: 8px 12px; border: 1px solid var(--border-2); border-radius: var(--radius-sm); background: var(--card); min-height: 38px">
          <option v-for="s in statusOptions" :key="s" :value="s">{{ STATUS_META[s].hint }}</option>
        </select>
      </div>
      <div class="field">
        <label>描述</label>
        <textarea v-model="form.description" placeholder="一句话说明这个需求域管什么" />
      </div>
      <template #foot>
        <span class="d-note">{{ editing ? '名称全局唯一;已暂停/已结项为只读' : '创建后即可上传材料' }}</span>
        <button class="btn" @click="modal = null">取消</button>
        <button class="btn primary" @click="save">{{ editing ? '保存' : '创建' }}</button>
      </template>
    </AppModal>

    <AppModal v-if="deleting" title="删除项目" @close="deleting = null">
      <p style="font-size: 0.9rem; line-height: 1.6">删除「<b>{{ deleting.name }}</b>」？项目下全部材料、文档、版本、批注将永久删除，不可恢复。</p>
      <template #foot>
        <button class="btn" @click="deleting = null">取消</button>
        <button class="btn danger" @click="doDelete">删除</button>
      </template>
    </AppModal>
  </div>
</template>
