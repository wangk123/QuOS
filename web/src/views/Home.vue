<script setup lang="ts">
import { inject, onMounted, ref } from 'vue'
import {
  ApiError,
  archiveProject,
  createProject,
  getArchivedProjects,
  getProjects,
  patchProject,
  purgeProject,
  restoreProject,
  type ProjectInfo,
} from '../api'
import { enterProject } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})
const items = ref<ProjectInfo[]>([])
const archived = ref<ProjectInfo[]>([])
const loading = ref(true)
const err = ref('')
const showNew = ref(false)
const newName = ref('')
const newDesc = ref('')
const showArchived = ref(false)
const editSlug = ref('')
const editName = ref('')
const editDesc = ref('')

async function load() {
  err.value = ''
  loading.value = true
  try {
    items.value = await getProjects()
    loading.value = false  // 主列表先出，归档列表不阻塞
    archived.value = await getArchivedProjects()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : '无法连接后端'
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function submitNew() {
  const name = newName.value.trim()
  if (!name) return
  try {
    await createProject(name, newDesc.value.trim())
    toast(`已创建「${name}」`)
    showNew.value = false
    newName.value = ''
    newDesc.value = ''
    await load()
  } catch (e) {
    toast(e instanceof ApiError && e.status === 409 ? '项目已存在（含归档侧）' : '创建失败', 'warn')
  }
}

async function onArchive(p: ProjectInfo) {
  if (!confirm(`归档「${p.name}」？工作台将不可访问，可随时恢复`)) return
  await archiveProject(p.slug).catch(() => toast('归档失败', 'warn'))
  await load()
}

function startEdit(p: ProjectInfo) {
  editSlug.value = p.slug
  editName.value = p.name
  editDesc.value = p.description
}

async function submitEdit() {
  const name = editName.value.trim()
  const slug = editSlug.value
  if (!slug || !name) return
  try {
    await patchProject(slug, { name, description: editDesc.value.trim() })
    toast('已保存')
    editSlug.value = ''
    await load()
  } catch (e) {
    toast(e instanceof ApiError && e.status === 422 ? '项目名不合法' : '保存失败', 'warn')
  }
}

async function onDelete(p: ProjectInfo) {
  const typed = prompt(`删除「${p.name}」将移除全部需求资产与基线历史，不可恢复。\n输入项目名确认：`)
  if (typed !== p.name) {
    toast('名称不一致，已取消')
    return
  }
  try {
    await archiveProject(p.slug)  // 彻底删除仅限归档态，先归档再清（purge 语义不变）
    await purgeProject(p.slug)
    toast(`已删除「${p.name}」`)
  } catch {
    toast('删除失败，项目可能已移入归档区', 'warn')
  }
  await load()
}

async function onRestore(p: ProjectInfo) {
  await restoreProject(p.slug).catch((e) =>
    toast(e instanceof ApiError && e.status === 409 ? '活跃侧已有同名项目' : '恢复失败', 'warn'))
  await load()
}

async function onPurge(p: ProjectInfo) {
  const typed = prompt(`彻底删除「${p.name}」将移除全部需求资产与基线历史，不可恢复。\n输入项目名确认：`)
  if (typed !== p.name) {
    toast('名称不一致，已取消')
    return
  }
  await purgeProject(p.slug).catch(() => toast('删除失败', 'warn'))
  await load()
}
</script>

<template>
  <main class="home">
    <h1>项目</h1>
    <p v-if="err" class="err">{{ err }}</p>
    <div v-if="loading && !err" class="empty">加载中…</div>
    <div v-else-if="!items.length && !err" class="empty">
      还没有项目——输入第一个项目名开始整理需求
      <form data-test="new" @submit.prevent="submitNew">
        <input data-test="new-name" v-model="newName" placeholder="项目名（如：风控云）" />
        <button type="submit">创建</button>
      </form>
    </div>
    <template v-else>
      <div class="home-bar">
        <button class="ghost" @click="showNew = !showNew">＋ 新建项目</button>
      </div>
      <form v-show="showNew" class="new-form" @submit.prevent="submitNew">
        <input data-test="new-name" v-model="newName" placeholder="项目名" />
        <input v-model="newDesc" placeholder="描述（可选）" />
        <button type="submit" class="btn">创建</button>
      </form>
      <div class="cards">
        <div
          v-for="p in items"
          :key="p.slug"
          class="card"
          data-test="proj-card"
          @click="editSlug === p.slug || enterProject(p.slug)"
        >
          <form
            v-if="editSlug === p.slug"
            class="edit-form"
            data-test="edit-form"
            @submit.prevent="submitEdit"
            @click.stop
          >
            <input data-test="edit-name" v-model="editName" placeholder="项目名" />
            <input data-test="edit-desc" v-model="editDesc" placeholder="描述（可选）" />
            <div class="edit-actions">
              <button type="submit" class="btn btn-sm">保存</button>
              <button type="button" class="ghost" @click.stop="editSlug = ''">取消</button>
            </div>
          </form>
          <template v-else>
            <b>{{ p.name }}</b>
            <span class="muted">{{ p.description || '—' }}</span>
            <span class="muted">创建 {{ p.created_at.slice(0, 10) }}</span>
            <div class="card-actions">
              <button class="ghost" @click.stop="startEdit(p)">编辑</button>
              <button class="ghost" @click.stop="onArchive(p)">归档</button>
              <button class="danger" @click.stop="onDelete(p)">删除</button>
            </div>
          </template>
        </div>
      </div>
      <section v-if="archived.length" class="archived-sec">
        <button class="ghost" @click="showArchived = !showArchived">已归档（{{ archived.length }}）</button>
        <div v-if="showArchived" class="cards">
          <div v-for="p in archived" :key="p.slug" class="card archived">
            <b>{{ p.name }}</b>
            <button class="ghost" @click="onRestore(p)">恢复</button>
            <button class="danger" @click="onPurge(p)">彻底删除</button>
          </div>
        </div>
      </section>
    </template>
  </main>
</template>
