<!-- 项目总览:表格/新建/编辑/删除 -->
<script setup lang="ts">
import { ref } from 'vue'
import { createProject, deleteProject, listProjects, patchProject, type Project } from '../api'
import AppModal from '../components/AppModal.vue'
import { toast } from '../components/toast'

const projects = ref<Project[]>([])
let editing: Project | null = null

const modal = ref<null | 'form'>(null)
const form = ref({ name: '', description: '' })
const formErr = ref(false)
const deleting = ref<Project | null>(null)

async function refresh() {
  projects.value = await listProjects()
  // 侧栏项目树只在切页时自刷,增删改后主动通知,避免残留死链接
  window.dispatchEvent(new Event('quos:projects-changed'))
}
refresh()

function openCreate() {
  editing = null
  form.value = { name: '', description: '' }
  formErr.value = false
  modal.value = 'form'
}
function openEdit(p: Project) {
  editing = p
  form.value = { name: p.name, description: p.description }
  formErr.value = false
  modal.value = 'form'
}
async function save() {
  if (!form.value.name.trim()) {
    formErr.value = true
    return
  }
  if (editing) {
    await patchProject(editing.id, form.value)
    toast('项目已更新')
  } else {
    await createProject(form.value.name.trim(), form.value.description)
    toast('项目已创建')
  }
  modal.value = null
  refresh()
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
            <th>项目</th><th>材料</th><th>批注</th><th>当前版本</th><th>草案</th><th style="text-align: right">操作</th>
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
            <td><span class="num">{{ p.stats.version ?? '—' }}</span></td>
            <td>
              <span v-if="p.stats.draft_status === 'reviewing'" class="tag warn"><span class="dot" />草案评审中</span>
              <span v-else class="tag mute"><span class="dot" />无</span>
            </td>
            <td style="white-space: nowrap; text-align: right">
              <a class="btn sm" :href="`#/p/${p.id}/review`" style="text-decoration: none">进入</a>
              <button class="icon-btn" title="编辑" @click="openEdit(p)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4z" /></svg>
              </button>
              <button class="icon-btn" title="删除" @click="askDelete(p)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
              </button>
            </td>
          </tr>
          <tr v-if="!projects.length">
            <td colspan="6"><div class="empty">尚无项目,点击右上角新建</div></td>
          </tr>
        </tbody>
      </table>
    </div>

    <AppModal v-if="modal === 'form'" :title="editing ? '编辑项目' : '新建项目'" @close="modal = null">
      <div class="field" :class="{ invalid: formErr }">
        <label>项目名称 <span class="req">*</span></label>
        <input v-model="form.name" type="text" placeholder="如:多模态" />
        <div class="err-msg">名称必填</div>
      </div>
      <div class="field">
        <label>描述</label>
        <textarea v-model="form.description" placeholder="一句话说明这个需求域管什么" />
      </div>
      <template #foot>
        <span class="d-note">{{ editing ? '改名不影响数据' : '创建后即可上传材料' }}</span>
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
