<!-- 正文内章节目录:层级缩进+每章批注计数;头部图钉切换固定/悬浮显隐 -->
<script setup lang="ts">
import type { ChapterP, Question } from '../../api'
import { computed } from 'vue'
import { flattenChapters } from '../../utils/chapters'

const props = defineProps<{ chapters: ChapterP[]; annos: Question[]; current: string; pinned: boolean }>()
const emit = defineEmits<{ jump: [ch: string]; pin: [] }>()

const flat = computed(() => flattenChapters(props.chapters))

function annoCount(ch: ChapterP): number {
  return props.annos.filter((a) => a.anchor.chapter_id === ch.id).length
}
</script>

<template>
  <nav class="toc" aria-label="章节目录">
    <div class="t">章节<button class="toc-pin" :class="{ on: pinned }" type="button" :aria-pressed="pinned"
        :title="pinned ? '取消固定(改为悬浮显隐)' : '固定目录(常驻)'" @click="emit('pin')">
      <svg width="13" height="13" viewBox="0 0 24 24" :fill="pinned ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5" /><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z" /></svg>
    </button></div>
    <a v-for="f in flat" :key="f.c.id" href="javascript:void 0"
       :class="{ current: f.c.id === current, [`lv${Math.min(f.depth, 2)}`]: true }"
       :title="`${f.no} ${f.c.title}`" @click="emit('jump', f.c.id)">
      <span class="chno">{{ f.no }}</span><span class="ttl">{{ f.c.title }}</span>
      <span v-if="annoCount(f.c)" class="n-anno">{{ annoCount(f.c) }}</span>
    </a>
  </nav>
</template>
