<script setup lang="ts">
import { inject, onMounted, ref } from 'vue'
import {
  ApiError,
  archiveProject,
  createProject,
  getArchivedProjects,
  getProjects,
  purgeProject,
  restoreProject,
  type ProjectInfo,
} from '../api'
import { enterProject } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})
const items = ref<ProjectInfo[]>([])
const archived = ref<ProjectInfo[]>([])
const err = ref('')
const showNew = ref(false)
const newName = ref('')
const newDesc = ref('')
const showArchived = ref(false)

async function load() {
  err.value = ''
  try {
    items.value = await getProjects()
    archived.value = await getArchivedProjects()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : '无法连接后端'
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
    <div v-if="!items.length && !err" class="empty">
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
          @click="enterProject(p.slug)"
        >
          <b>{{ p.name }}</b>
          <span class="muted">{{ p.description || '—' }}</span>
          <span class="muted">创建 {{ p.created_at.slice(0, 10) }}</span>
          <button class="ghost" @click.stop="onArchive(p)">归档</button>
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
