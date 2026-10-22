<!-- 正文内章节目录:层级缩进+每章批注计数;父章可折叠(默认收起);头部图钉切换固定/悬浮显隐 -->
<script setup lang="ts">
import type { ChapterP, Question } from '../../api'
import { computed, ref } from 'vue'
import { flattenChapters } from '../../utils/chapters'

const props = defineProps<{ chapters: ChapterP[]; annos: Question[]; current: string; pinned: boolean }>()
const emit = defineEmits<{ jump: [ch: string]; pin: [] }>()

const flat = computed(() => flattenChapters(props.chapters))
/* 折叠态:openSet 记展开的父章 id,默认空=全部收起;子章仅当祖先链全展开才可见 */
const openSet = ref(new Set<string>())
const parentOf = computed(() => new Map(flat.value.map((f) => [f.c.id, f.c.parent ?? null])))
const hasKids = computed(() => new Set(flat.value.filter((f) => f.c.parent).map((f) => f.c.parent!)))
function visible(f: { c: ChapterP }): boolean {
  let p = parentOf.value.get(f.c.id) ?? null
  while (p) {
    if (!openSet.value.has(p)) return false
    p = parentOf.value.get(p) ?? null
  }
  return true
}
function toggleTw(id: string) {
  const s = new Set(openSet.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  openSet.value = s
}

/* 徽标签额=以该节点为根的子树待处理数(自身+后代):子章默认折叠不可见,父章聚合才对得上总账 */
const pendingByCh = computed(() => {
  const m = new Map<string, number>()
  for (const a of props.annos) {
    if (a.status !== 'answered' && a.anchor?.chapter_id)
      m.set(a.anchor.chapter_id, (m.get(a.anchor.chapter_id) ?? 0) + 1)
  }
  return m
})
const kidsOf = computed(() => {
  const m = new Map<string, ChapterP[]>()
  for (const f of flat.value) {
    if (f.c.parent) m.set(f.c.parent, [...(m.get(f.c.parent) ?? []), f.c])
  }
  return m
})
function annoCount(ch: ChapterP): number {
  let n = pendingByCh.value.get(ch.id) ?? 0
  for (const k of kidsOf.value.get(ch.id) ?? []) n += annoCount(k)
  return n
}
</script>

<template>
  <nav class="toc" aria-label="章节目录">
    <div class="t">章节<button class="toc-pin" :class="{ on: pinned }" type="button" :aria-pressed="pinned"
        :title="pinned ? '取消固定(改为悬浮显隐)' : '固定目录(常驻)'" @click="emit('pin')">
      <svg width="13" height="13" viewBox="0 0 24 24" :fill="pinned ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5" /><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z" /></svg>
    </button></div>
    <template v-for="f in flat" :key="f.c.id">
      <a v-if="visible(f)" href="javascript:void 0"
         :class="{ current: f.c.id === current, [`lv${Math.min(f.depth, 2)}`]: true }"
         :title="`${f.no} ${f.c.title}`" @click="emit('jump', f.c.id)">
        <button v-if="hasKids.has(f.c.id)" class="toc-tw" type="button"
                :aria-expanded="openSet.has(f.c.id)" :title="openSet.has(f.c.id) ? '折叠子章节' : '展开子章节'"
                @click.stop="toggleTw(f.c.id)">{{ openSet.has(f.c.id) ? '▾' : '▸' }}</button>
        <span v-else class="toc-tw-pad" aria-hidden="true" />
        <span class="chno">{{ f.no }}</span><span class="ttl">{{ f.c.title }}</span>
        <span v-if="annoCount(f.c)" class="n-anno">{{ annoCount(f.c) }}</span>
      </a>
    </template>
  </nav>
</template>
