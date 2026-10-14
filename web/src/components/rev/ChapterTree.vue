<!-- 正文内章节目录:层级缩进(最多三层)+每章批注计数,头部可折叠整个隐藏 -->
<script setup lang="ts">
import type { ChapterP, Question } from '../../api'
import { computed } from 'vue'
import { flattenChapters } from '../../utils/chapters'

const props = defineProps<{ chapters: ChapterP[]; annos: Question[]; current: string }>()
const emit = defineEmits<{ jump: [ch: string]; fold: [] }>()

const flat = computed(() => flattenChapters(props.chapters))

function annoCount(ch: ChapterP): number {
  return props.annos.filter((a) => a.anchor.chapter_id === ch.id).length
}
</script>

<template>
  <nav class="toc" aria-label="章节目录">
    <div class="t">章节<button class="toc-fold" type="button" aria-label="折叠目录" @click="emit('fold')">⟨</button></div>
    <a v-for="f in flat" :key="f.c.id" href="javascript:void 0"
       :class="{ current: f.c.id === current, [`lv${Math.min(f.depth, 2)}`]: true }"
       :title="`${f.no} ${f.c.title}`" @click="emit('jump', f.c.id)">
      <span class="chno">{{ f.no }}</span><span class="ttl">{{ f.c.title }}</span>
      <span v-if="annoCount(f.c)" class="n-anno">{{ annoCount(f.c) }}</span>
    </a>
  </nav>
</template>
