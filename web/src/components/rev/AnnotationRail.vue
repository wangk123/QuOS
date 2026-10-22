<!-- 右栏:批注栏。两级筛选(状态×类型)+按章节分组(标题=章节号+章名,可跳正文),固定对照列表 -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Question } from '../../api'
import AnnotationCard from './AnnotationCard.vue'
import { annoType, ANNO_TYPE_CLS, ANNO_TYPE_ORDER } from '../../utils/annotype'

const props = defineProps<{
  annos: Question[]
  openSet: Set<number>
  activeId: number | null
}>()
const emit = defineEmits<{
  'toggle': [qid: number]
  'locate': [qid: number]
  'answer': [qid: number, answer: any]
  'undo': [qid: number]
  'jump': [ch: string]
  'collapse': []
}>()

/* 两级筛选:一级=处理状态,二级=问题类型;AND 组合,单选互斥,默认全开不预过滤 */
const fStatus = ref<'all' | 'pending' | 'answered'>('all')
const fType = ref('') // ''=全部类型

const doneCount = computed(() => props.annos.filter((a) => a.status === 'answered').length)
const types = computed(() => {
  const present = new Set(props.annos.map(annoType))
  return ANNO_TYPE_ORDER.filter((t) => present.has(t))
})
const nOf = (status: 'all' | 'pending' | 'answered') =>
  props.annos.filter((a) => status === 'all' || (a.status === 'answered') === (status === 'answered')).length

const filtered = computed(() =>
  props.annos.filter((a) =>
    (fStatus.value === 'all' || (a.status === 'answered') === (fStatus.value === 'answered'))
    && (!fType.value || annoType(a) === fType.value)))

/* 分组:章节锚优先(标题取注入的 chapter_label,按文档顺序),仅规则锚归「规则 x」,无锚归「全局」 */
const groups = computed(() => {
  const byKey = new Map<string, Question[]>()
  for (const a of filtered.value) {
    const k = a.anchor?.chapter_id || a.anchor?.rule_no || '全局'
    byKey.set(k, [...(byKey.get(k) ?? []), a])
  }
  return [...byKey.entries()]
    .map(([k, qs]) => ({
      chId: qs[0].anchor?.chapter_id || '',
      ord: qs[0].anchor?._ord ?? 9999,
      label: k === '全局' ? '全局' : qs[0].anchor?.chapter_label ? `章节 ${qs[0].anchor.chapter_label}` : `规则 ${k}`,
      qs,
    }))
    .filter((g) => g.qs.length)
    .sort((x, y) => x.ord - y.ord)
})
</script>

<template>
  <div class="anno-rail">
    <div class="anno-head">
      <span class="sum">待处理 <b>{{ annos.length - doneCount }}</b> / {{ annos.length }}</span>
      <span style="flex: 1" />
      <button class="a-collapse" type="button" title="收起批注栏" aria-label="收起批注栏" @click="emit('collapse')">»</button>
    </div>

    <div class="afilter">
      <div class="fsegs" role="group" aria-label="按处理状态筛选">
        <button type="button" :class="{ on: fStatus === 'all' }" @click="fStatus = 'all'">全部<i>{{ annos.length }}</i></button>
        <button type="button" :class="{ on: fStatus === 'pending' }" @click="fStatus = 'pending'">待处理<i>{{ nOf('pending') }}</i></button>
        <button type="button" :class="{ on: fStatus === 'answered' }" @click="fStatus = 'answered'">已处理<i>{{ nOf('answered') }}</i></button>
      </div>
      <div v-if="types.length > 1" class="ftypes" role="group" aria-label="按问题类型筛选(点已选类型取消)">
        <button v-for="t in types" :key="t" type="button" :class="[ANNO_TYPE_CLS[t], { on: fType === t }]"
                :title="`只看${t}`" @click="fType = fType === t ? '' : t">{{ t }}</button>
      </div>
    </div>

    <div class="anno-list">
      <div v-if="!filtered.length" class="af-empty">无匹配批注</div>
      <template v-for="g in groups" :key="g.label">
        <div class="agroup">
          <span class="lbl" :title="g.label">{{ g.label }}</span>
          <button v-if="g.chId" class="gjump" title="跳到该章" aria-label="跳到该章" @click="emit('jump', g.chId)">↗</button>
        </div>
        <AnnotationCard v-for="q in g.qs" :key="q.id" :q="q" :open="openSet.has(q.id)"
                        :active="activeId === q.id"
                        @toggle="emit('toggle', q.id)" @locate="emit('locate', q.id)"
                        @answer="(a) => emit('answer', q.id, a)" @undo="emit('undo', q.id)" />
      </template>
    </div>
  </div>
</template>
