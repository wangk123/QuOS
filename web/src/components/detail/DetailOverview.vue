<script setup lang="ts">
// 概要 tab：画像六字段 spec 网格 + 未确认计数行（读侧——字段随条目核验自动更新，写操作 T10/T11）
import type { Profile } from '../../api'
defineProps<{ profile: Profile }>()
</script>

<template>
  <div class="card">
    <h3>概要 <span class="badge b-amber">随条目核验自动更新</span></h3>
    <div class="spec">
      <span class="k">目标</span><span>{{ profile.goal || '—' }}</span>
      <span class="k">入口</span><span>{{ profile.entry || '—' }}</span>
      <span class="k">主流程</span><span>{{ profile.flow || '—' }}</span>
      <span class="k">状态机</span><span>{{ profile.states || '—' }}</span>
      <span class="k">异常</span><span>{{ profile.boundaries || '—' }}</span>
      <span class="k">依赖</span><span>{{ profile.deps || '—' }}</span>
    </div>
    <div v-if="profile.unconfirmed.length" class="rrow unconf">
      <span class="rtxt">未确认 {{ profile.unconfirmed.length }} 项（已转澄清池待问人）<span class="rsrc">{{ profile.unconfirmed.join(' · ') }}</span></span>
    </div>
  </div>
</template>

<style scoped>
.card { display: block; cursor: default; background: #fff; border: 1px solid var(--border2); border-radius: 10px; padding: 15px 18px; }
.card h3 { font-size: 14px; display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-bottom: 8px; }
.spec { display: grid; grid-template-columns: 76px 1fr; gap: 4px 12px; font-size: 12.5px; }
.spec .k { color: var(--muted-fg); }
.spec span:not(.k) { white-space: pre-wrap; overflow-wrap: anywhere; }  /* 多行字段（主流程/状态机等）按原换行渲染 */
.rrow { display: flex; align-items: flex-start; gap: 10px; padding: 8px 2px 0; margin-top: 10px; border-top: 1px solid #f1f5f9; font-size: 12.5px; }
.rrow .rtxt { flex: 1; min-width: 0; }
.rrow .rsrc { display: block; font-size: 11px; color: var(--muted-fg); margin-top: 1px; }
</style>
