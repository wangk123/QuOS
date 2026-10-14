<!-- 侧栏:项目树 + 项目内子导航(材料/文档评审/版本)+ 归档区 -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { route } from '../router'
import { listProjects, type Project } from '../api'

const projects = ref<Project[]>([])

async function refresh() {
  projects.value = await listProjects()
}
refresh()
// 跨页签切换时刷新徽标数(评审作答会改变 pending)
window.addEventListener('hashchange', () => refresh())

const inProj = computed(() => route.view !== 'projects')
const subs = computed(() => {
  const p = projects.value.find((x) => x.id === route.pid)
  return [
    { key: 'materials', label: '材料', cnt: p?.stats.materials ?? 0, cls: 'blue' },
    { key: 'review', label: '文档评审', cnt: p?.stats.pending_annos ?? 0, cls: '' },
    { key: 'versions', label: '版本', cnt: 0, cls: '' },
  ]
})
</script>

<template>
  <aside class="side">
    <div class="side-logo">
      <span class="mark"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12" /></svg></span>
      QuOS
    </div>
    <div class="side-sec">项目</div>
    <a class="item" :class="{ active: !inProj }" href="#/projects">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>
      项目总览
    </a>
    <template v-for="p in projects" :key="p.id">
      <a class="item" :class="{ active: inProj && p.id === route.pid && !subs.some((s) => s.key === route.view) }"
         :href="`#/p/${p.id}/review`" style="padding-left: 14px">
        <span class="proj-name">{{ p.name }}</span>
        <span v-if="p.stats.draft_status === 'reviewing'" class="cnt blue" title="草案评审中">草</span>
      </a>
      <template v-if="inProj && p.id === route.pid">
        <a v-for="s in subs" :key="s.key" class="item" :class="{ active: route.view === s.key }"
           :href="`#/p/${p.id}/${s.key}`" style="padding-left: 34px; font-size: 0.83rem">
          <span class="proj-name">{{ s.label }}</span>
          <span v-if="s.cnt" class="cnt" :class="s.cls">{{ s.cnt }}</span>
        </a>
      </template>
    </template>
    <div class="side-foot">
      <span class="proto">v2</span><br />质量工作台
    </div>
  </aside>
</template>
