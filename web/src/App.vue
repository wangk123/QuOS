<!-- 应用骨架:侧栏 + 顶栏(面包屑/页操作插槽) + 内容视图切换 -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { route } from './router'
import { getProject, type Project } from './api'
import SideBar from './components/SideBar.vue'
import ProjectsView from './views/ProjectsView.vue'
import MaterialsView from './views/MaterialsView.vue'
import ReviewView from './views/ReviewView.vue'
import VersionsView from './views/VersionsView.vue'
import { mountToasts } from './components/toast'

const proj = ref<Project | null>(null)
const names: Record<string, string> = { materials: '材料', review: '文档评审', versions: '版本' }

async function loadProj() {
  proj.value = route.pid ? await getProject(route.pid) : null
}
watch(() => route.pid, loadProj)
onMounted(() => {
  const host = document.createElement('div')
  document.body.appendChild(host) // 未挂载的容器渲染在内存,toast 不可见
  mountToasts(host)
  loadProj()
})

const crumbs = computed(() =>
  route.view === 'projects'
    ? [{ label: '项目总览' }]
    : [
        { label: 'QuOS', hash: '#/projects' },
        { label: proj.value?.name ?? '', hash: `#/p/${route.pid}/review` },
        { label: names[route.view] ?? '' },
      ])

const view = computed(() => {
  if (route.view === 'materials') return MaterialsView
  if (route.view === 'review') return ReviewView
  if (route.view === 'versions') return VersionsView
  return ProjectsView
})
</script>

<template>
  <div class="app" :class="{ 'no-side': route.view === 'projects' }">
    <SideBar v-if="route.view !== 'projects'" />
    <div class="main">
      <header class="topbar">
        <div class="crumb">
          <!-- 列表态无侧栏,品牌移到顶栏 -->
          <template v-if="route.view === 'projects'">
            <span class="brand"><span class="mark"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12" /></svg></span>QuOS</span>
            <span class="sep">/</span>
          </template>
          <template v-for="(c, i) in crumbs" :key="i">
            <a v-if="c.hash" :href="c.hash" style="color: var(--muted); text-decoration: none">{{ c.label }}</a>
            <b v-else>{{ c.label }}</b>
            <span v-if="i < crumbs.length - 1" class="sep">/</span>
          </template>
        </div>
        <span class="spacer" />
        <slot name="topbar" />
      </header>
      <component :is="view" :key="`${route.pid}-${route.view}`" />
    </div>
  </div>
</template>
