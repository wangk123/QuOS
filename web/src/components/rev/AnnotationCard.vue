<!-- 批注卡:默认折叠(问题首行+编号·类型 meta),展开作答,定位按钮,答完转绿自动收起 -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Question } from '../../api'
import { annoType, ANNO_TYPE_CLS } from '../../utils/annotype'

const props = defineProps<{ q: Question; open: boolean; active: boolean }>()
const emit = defineEmits<{
  'toggle': []
  'locate': []
  'answer': [answer: any]
  'undo': []
}>()

const done = computed(() => props.q.status === 'answered')
const v = computed(() => props.q.answer ?? {})
const typeLabel = computed(() => annoType(props.q))
const typeCls = computed(() => ANNO_TYPE_CLS[typeLabel.value])

/* 输入类作答走本地草稿,显式提交(避免半成品直接落库) */
const isTerm = computed(() => props.q.kind === 'confirm' && props.q.payload?.klabel === '术语确认')
const fillDraft = ref('')
const noteDraft = ref('')
const termDef = ref('')
watch(done, (d) => { if (!d) { fillDraft.value = ''; noteDraft.value = ''; termDef.value = '' } })

const answerText = computed(() => {
  if (!done.value) return ''
  const p = props.q.payload
  if (props.q.kind === 'choice') return p.options?.find((o: any) => o.k === v.value.key)?.t ?? v.value.key
  if (props.q.kind === 'confirm') return v.value.ok ? '已确认' : `已纠正:${v.value.note ?? ''}`
  if (props.q.kind === 'term') return `已收录:${v.value.def ?? ''}`
  if (props.q.kind === 'fill') return v.value.text ?? '已作答'
  return '全部通过'
})

</script>

<template>
  <div class="acard" :class="[typeCls, { ok: done, closed: !open, active }]" :id="'ac-' + q.id">
    <div class="a-top" :title="q.payload.q" @click="emit('toggle')">
      <span class="a-q">{{ q.payload.q }}</span>
      <button v-if="!done" class="a-locate" title="定位到正文" aria-label="定位到正文" @click.stop="emit('locate')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></svg>
      </button>
      <span class="a-chev">▸</span>
    </div>
    <div class="a-meta">
      <span class="a-type" :class="typeCls">{{ typeLabel }}</span>
      <span class="a-id">#{{ q.id }}</span><span>·</span><span class="a-kind">{{ q.payload.klabel }}</span>
      <span v-if="q.source === 'auto'" style="margin-left: auto">软校验</span>
    </div>
    <div class="a-body">
      <div v-if="q.payload.ctx" class="a-ctx">{{ q.payload.ctx }}</div>

      <!-- 选择题 -->
      <div v-if="!done && q.kind === 'choice'" class="a-ops">
        <label v-for="o in q.payload.options" :key="o.k" class="aopt" :class="{ sel: v.key === o.k }" @click="emit('answer', { key: o.k })">
          <span class="k">{{ o.k }}</span>
          <span>{{ o.t }}<span v-if="o.c" class="c">{{ o.c }}</span></span>
        </label>
      </div>

      <!-- 确认题 -->
      <div v-else-if="!done && q.kind === 'confirm'" class="abtns">
        <button class="btn sm yes" :class="{ sel: v.ok === true }" :disabled="isTerm && !termDef.trim()"
                @click="emit('answer', isTerm ? { ok: true, def: termDef } : { ok: true })">✓ {{ isTerm ? '收录' : '确认' }}</button>
        <button class="btn sm no" :class="{ sel: v.ok === false }" @click="emit('answer', { ok: false })">不对</button>
      </div>
      <div v-if="!done && q.kind === 'confirm' && isTerm && v.ok !== false" class="afield">
        <input v-model="termDef" type="text" placeholder="给一句术语定义…" />
      </div>
      <div v-if="!done && q.kind === 'confirm' && v.ok === false" class="afield">
        <input v-model="noteDraft" type="text" placeholder="给出正确内容…" />
        <div class="abtns"><button class="btn sm primary" :disabled="!noteDraft.trim()" @click="emit('answer', { ok: false, note: noteDraft })">提交纠正</button></div>
      </div>

      <!-- 填空 -->
      <div v-else-if="!done && q.kind === 'fill'" class="afield">
        <input v-model="fillDraft" type="text" placeholder="一句话作答…" @keyup.enter="fillDraft.trim() && emit('answer', { text: fillDraft })" />
        <div class="abtns"><button class="btn sm primary" :disabled="!fillDraft.trim()" @click="emit('answer', { text: fillDraft })">提交作答</button></div>
      </div>

      <!-- 批量扫 -->
      <div v-else-if="!done && q.kind === 'scan'" class="scanmini">
        <label v-for="(it, i) in q.payload.items" :key="i" class="sr" :class="{ done: v.items?.[i] }">
          <input type="checkbox" :checked="!!v.items?.[i]"
                 @change="emit('answer', { items: { ...v.items, [i]: ($event.target as any).checked } })" />
          <span>{{ it }}</span><span class="mk">✓</span>
        </label>
      </div>

      <!-- 已答 -->
      <template v-if="done">
        <div class="a-done">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
          <span class="da-text">{{ answerText }}</span>
        </div>
        <div class="abtns" style="margin-top: 8px">
          <button class="btn sm" @click="emit('undo')">重新作答</button>
        </div>
      </template>
    </div>
  </div>
</template>
