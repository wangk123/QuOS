<!-- 右栏:批注栏(按章节分组/折叠卡/对照+逐条两模式) -->
<script setup lang="ts">
import { computed } from 'vue'
import type { Question } from '../../api'
import AnnotationCard from './AnnotationCard.vue'

const props = defineProps<{
  annos: Question[]
  openSet: Set<number>
  activeId: number | null
  mode: 'side' | 'focus'
  focusIdx: number
}>()
const emit = defineEmits<{
  'toggle': [qid: number]
  'locate': [qid: number]
  'answer': [qid: number, answer: any]
  'undo': [qid: number]
  'set-mode': [m: 'side' | 'focus']
  'fstep': [d: number]
}>()

const doneCount = computed(() => props.annos.filter((a) => a.status === 'answered').length)
/* 分组:按章节(术语/无章节的归「全局」),组内按 id */
const groups = computed(() => {
  const key = (a: Question) => a.anchor?.chapter_id || a.anchor?.rule_no || '全局'
  const byChapter = new Map<string, Question[]>()
  for (const a of props.annos) {
    const k = key(a)
    byChapter.set(k, [...(byChapter.get(k) ?? []), a])
  }
  return [...byChapter.entries()].map(([k, qs]) => ({ label: k === '全局' ? '全局' : `章节 ${k}`, qs }))
})
const focusQ = computed(() => props.annos[props.focusIdx] ?? props.annos[0])
</script>

<template>
  <div class="anno-rail">
    <div class="anno-head">
      <span class="sum">待处理 <b>{{ annos.length - doneCount }}</b> / {{ annos.length }}</span>
      <span style="flex: 1" />
      <div class="seg">
        <button :class="{ active: mode === 'side' }" title="对照评审" @click="emit('set-mode', 'side')">对照</button>
        <button :class="{ active: mode === 'focus' }" title="逐条评审" @click="emit('set-mode', 'focus')">逐条</button>
      </div>
    </div>

    <div v-if="mode === 'side'" class="anno-list">
      <template v-for="g in groups" :key="g.label">
        <div class="agroup">{{ g.label }}</div>
        <AnnotationCard v-for="q in g.qs" :key="q.id" :q="q" :open="openSet.has(q.id)"
                        :active="activeId === q.id"
                        @toggle="emit('toggle', q.id)" @locate="emit('locate', q.id)"
                        @answer="(a) => emit('answer', q.id, a)" @undo="emit('undo', q.id)" />
      </template>
    </div>

    <template v-else>
      <div v-if="focusQ" class="focusbox">
        <div class="focus-top">
          <span class="fp"><b>{{ focusIdx + 1 }}</b> / {{ annos.length }}</span>
          <div class="focus-nav">
            <button class="btn sm" @click="emit('fstep', -1)">上一条</button>
            <button class="btn sm primary" @click="emit('fstep', 1)">下一条</button>
          </div>
        </div>
        <AnnotationCard :key="focusQ.id" :q="focusQ" :open="true" :active="true"
                        @toggle="() => {}" @locate="emit('locate', focusQ.id)"
                        @answer="(a) => emit('answer', focusQ.id, a)" @undo="emit('undo', focusQ.id)" />
        <div class="focus-jump">
          <span class="fq">#{{ focusQ.id }}</span>
          <span>正文位置:{{ focusQ.anchor?.rule_no ? `规则 ${focusQ.anchor.rule_no}` : '章节' }}{{ focusQ.anchor?.seg ? ` 「${focusQ.anchor.seg}」` : '' }}</span>
          <button class="btn sm" style="margin-left: auto" @click="emit('locate', focusQ.id)">定位正文</button>
        </div>
      </div>
    </template>
  </div>
</template>
