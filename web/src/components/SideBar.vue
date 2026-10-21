<!-- 项目内资源导航:仅进入项目后呈现(列表态由 App.vue 不渲染);模块配置驱动,未来模块上线改 live 即插 -->
<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { route } from '../router'
import { getProject, type Project } from '../api'

const proj = ref<Project | null>(null)

async function refresh() {
  proj.value = route.pid ? await getProject(route.pid) : null
}
refresh()
// 跨页签切换刷新徽标 + 项目增删改同步;组件随进入/退出项目反复挂载,卸载必须摘除监听
const onHash = () => refresh()
const onProjects = () => refresh()
window.addEventListener('hashchange', onHash)
window.addEventListener('quos:projects-changed', onProjects)
onUnmounted(() => {
  window.removeEventListener('hashchange', onHash)
  window.removeEventListener('quos:projects-changed', onProjects)
})

// 项目内资源模块注册表:live=已上线;未来模块灰色占位「即将上线」,上线时置 live 并接路由
const FUTURES = [
  { key: 'cases', label: '案例管理', icon: 'flask' },
  { key: 'api-auto', label: '接口自动化', icon: 'plug' },
  { key: 'ui-auto', label: 'UI 自动化', icon: 'monitor' },
  { key: 'perf', label: '性能测试', icon: 'gauge' },
  { key: 'security', label: '安全测试', icon: 'shield' },
  { key: 'env', label: '环境管理', icon: 'server' },
]
const ICONS: Record<string, string> = {
  back: '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
  clip: '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  msg: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  hist: '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/>',
  flask: '<path d="M10 2v7.5a2 2 0 0 1-.2.9L4.7 20.5a1 1 0 0 0 .9 1.5h12.8a1 1 0 0 0 .9-1.5L14.2 10.4a2 2 0 0 1-.2-.9V2"/><line x1="8.5" y1="2" x2="15.5" y2="2"/><line x1="7" y1="16" x2="17" y2="16"/>',
  plug: '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  server: '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
}
const ic = (n: string) =>
  `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="flex:none">${ICONS[n]}</svg>`

const subs = computed(() => [
  { key: 'materials', label: '材料', cnt: proj.value?.stats.materials ?? 0, cls: 'blue', icon: 'clip' },
  { key: 'review', label: '文档评审', cnt: proj.value?.stats.pending_annos ?? 0, cls: '', icon: 'msg' },
  { key: 'versions', label: '版本', cnt: 0, cls: '', icon: 'hist' },
])
</script>

<template>
  <aside class="side">
    <div class="side-logo">
      <span class="mark"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12" /></svg></span>
      QuOS
    </div>
    <a class="item" href="#/projects">
      <span v-html="ic('back')" /><span class="proj-name">返回项目列表</span>
    </a>
    <div class="proj-head" :title="proj?.name">{{ proj?.name ?? '' }}</div>
    <div class="side-sec">需求管理</div>
    <a v-for="s in subs" :key="s.key" class="item" :class="{ active: route.view === s.key }"
       :href="`#/p/${route.pid}/${s.key}`" style="padding-left: 34px; font-size: 0.83rem">
      <span v-html="ic(s.icon)" /><span class="proj-name">{{ s.label }}</span>
      <span v-if="s.cnt" class="cnt" :class="s.cls">{{ s.cnt }}</span>
    </a>
    <div class="side-sec" style="margin-top: 8px">更多模块</div>
    <button v-for="f in FUTURES" :key="f.key" class="item soon" :aria-disabled="true" disabled>
      <span v-html="ic(f.icon)" /><span class="proj-name">{{ f.label }}</span><span class="soon-tag">即将上线</span>
    </button>
    <div class="side-foot">
      <span class="proto">v2</span><br />质量工作台
    </div>
  </aside>
</template>
