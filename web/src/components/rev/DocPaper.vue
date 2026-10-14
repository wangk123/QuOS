<!-- 中栏:文档正文。批注高亮锚定正文(未答琥珀/已答绿),规则编号 popover;章节按 parent 层级编号,正文块按 type 分派 -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BlockP, ChapterP, DocPayload, Material, Question } from '../../api'
import { flattenChapters, termChapters, GLOSSARY_CH_ID } from '../../utils/chapters'

const props = defineProps<{
  payload: DocPayload
  annos: Question[]
  materials: Material[]
  title: string
  verLabel: string
  /** 目录呈现:pinned=常驻挤占正文 / hover=悬浮浮层 / hidden=只留把手 */
  tocMode: 'pinned' | 'hover' | 'hidden'
}>()
const emit = defineEmits<{ 'activate': [qid: number]; 'jump': [ch: string]; 'toc-show': []; 'toc-hide': [] }>()

/* 术语表章:术语 → 正文出现章节(与旧目录悬浮同口径),chip 点击跳转 */
function termHits(name: string): string[] {
  return termChapters(name, props.payload.chapters.filter((c) => c.id !== GLOSSARY_CH_ID), props.payload.rules)
}
const chById = computed(() => new Map(flattenChapters(props.payload.chapters).map((f) => [f.c.id, f])))
const chNo = (id: string) => chById.value.get(id)?.no ?? id
const chLabel = (id: string) => {
  const f = chById.value.get(id)
  return f ? `${f.no} ${f.c.title}` : id
}

const openRule = ref<string | null>(null)

const esc = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))

/* 规则文本 → 带批注高亮的 html:优先 rule_no+seg 精确锚,术语类按 seg 兜底(仅首个匹配规则) */
function ruleHtml(no: string, text: string): string {
  const hit = props.annos.find(
    (a) => a.anchor.rule_no === no && a.anchor.seg && text.includes(a.anchor.seg),
  )
  if (hit) {
    const seg = esc(hit.anchor.seg)
    const cls = hit.status === 'answered' ? 'anno resolved' : 'anno'
    return esc(text).replace(seg, `<mark class="${cls}" data-a="${hit.id}">${seg}<sup>${hit.id}</sup></mark>`)
  }
  const term = props.annos.find(
    (a) => !a.anchor.rule_no && a.anchor.seg && text.includes(a.anchor.seg)
      && a.payload?.klabel === '术语确认' && !usedTermIds.has(a.id),
  )
  if (term) {
    usedTermIds.add(term.id)
    const seg = esc(term.anchor.seg)
    const cls = term.status === 'answered' ? 'anno resolved' : 'anno'
    return esc(text).replace(seg, `<mark class="${cls}" data-a="${term.id}">${seg}<sup>${term.id}</sup></mark>`)
  }
  return esc(text)
}
const usedTermIds = new Set<number>() // 术语批注只锚首个出现处,跨规则渲染前重置

/* 层级编号复用共享展开(与左栏树一致);表号/图号全篇递增 */
interface Rendered { c: ChapterP; no: string; sub: boolean; rules: { no: string; html: string }[]; blocks: (BlockP & { tno?: string; fno?: string })[] }
const chaptersHtml = computed<Rendered[]>(() => {
  usedTermIds.clear()
  let tbl = 0, fig = 0
  return flattenChapters(props.payload.chapters).map(({ c, no, sub }) => ({
    c, no, sub,
    rules: c.rule_nos.map((no2) => ({ no: no2, html: ruleHtml(no2, props.payload.rules[no2]?.text ?? '') })),
    blocks: (c.blocks ?? []).map((b) => {
      if (b.type === 'table') return { ...b, tno: `表${++tbl}` }
      if (b.type === 'figure') return { ...b, fno: `图${++fig}` }
      return { ...b }
    }),
  }))
})

function chAnnos(chId: string): Question[] {
  return props.annos.filter((a) => a.anchor.chapter_id === chId && a.anchor.chapter)
}
function det(no: string) {
  return props.payload.rules[no] ?? null
}
function matOf(no: string): Material | null {
  const r = det(no)
  return props.materials.find((m) => m.id === r?.material_id) ?? null
}
function flowNodes(states: string): string[] {
  return states.split('→').map((s) => s.trim()).filter(Boolean)
}
function onClickBody(e: MouseEvent) {
  const mark = (e.target as HTMLElement).closest('mark.anno')
  if (mark) {
    emit('activate', Number((mark as HTMLElement).dataset.a))
    return
  }
  const chip = (e.target as HTMLElement).closest('[data-rule]')
  if (chip) {
    const no = (chip as HTMLElement).dataset.rule!
    openRule.value = openRule.value === no ? null : no
    return
  }
  if (!(e.target as HTMLElement).closest('.popover')) openRule.value = null
}
</script>

<template>
  <div class="docpaper" @click="onClickBody">
    <aside v-if="tocMode !== 'hidden'" class="doc-toc" :class="tocMode" @mouseleave="emit('toc-hide')"><slot name="toc" /></aside>
    <button v-else class="toc-handle" type="button" aria-label="展开目录" title="悬浮展开章节目录"
            @mouseenter="emit('toc-show')" @click="emit('toc-show')">›</button>
    <div class="doc-main">
    <div class="doc-title">{{ title }} · 需求文档</div>
    <div class="doc-meta">
      <span>{{ verLabel }}</span>
      <span>{{ payload.meta.date }}</span>
      <span>范围:{{ payload.meta.scope }}</span>
    </div>

    <section v-for="r in chaptersHtml" :id="'ch-' + r.c.id" :key="r.c.id" class="chapter" :class="{ sub: r.sub }">
      <h2 :class="{ sub: r.sub }">
        <span class="chno">{{ r.no }}</span>{{ r.c.title }}<span v-if="r.c.pri" class="pri">{{ r.c.pri }}</span>
        <span v-for="a in chAnnos(r.c.id)" :key="a.id" class="ch-anno" @click.stop="emit('activate', a.id)">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
          {{ a.payload.klabel }} ×{{ chAnnos(r.c.id).length }}
        </span>
      </h2>

      <!-- 术语表末章:词条表(术语/释义/出现章节可跳) -->
      <table v-if="r.c.id === GLOSSARY_CH_ID" class="tbl gtbl">
        <thead><tr><th class="gname-h">术语</th><th>释义</th><th class="ghit-h">出现章节</th></tr></thead>
        <tbody>
          <tr v-for="g in payload.glossary" :key="g.name">
            <td class="gname">{{ g.name }}</td>
            <td>{{ g.definition }}</td>
            <td class="ghit">
              <template v-if="termHits(g.name).length">
                <a v-for="id in termHits(g.name)" :key="id" class="gchip" href="javascript:void 0"
                   :title="chLabel(id)" @click.stop="emit('jump', id)">{{ chNo(id) }}</a>
              </template>
              <span v-else class="gnone">—</span>
            </td>
          </tr>
        </tbody>
      </table>

      <template v-else>
      <p v-if="r.c.background" class="bg">{{ r.c.background }}</p>

      <template v-for="(b, bi) in r.blocks" :key="bi">
        <p v-if="b.type === 'para'" class="bg">{{ b.text }}</p>
        <template v-else-if="b.type === 'states'">
          <div class="sl">状态与流程</div>
          <div class="flowbox">
            <template v-for="(n, i) in flowNodes(b.text ?? '')" :key="i">
              <span v-if="i" class="farr">→</span>
              <span class="fnode" :class="{ term: /SUCCEEDED|CANCELLED|失败/.test(n) }">{{ n }}</span>
            </template>
          </div>
        </template>
        <template v-else-if="b.type === 'table'">
          <div class="sl">{{ b.tno }} · {{ b.title }}</div>
          <table class="tbl">
            <thead><tr><th v-for="col in b.columns" :key="col">{{ col }}</th></tr></thead>
            <tbody>
              <tr v-for="(row, ri) in b.rows" :key="ri">
                <td v-for="(cell, ci) in row" :key="ci" :class="{ num: /^[\d.\-:%ms]+$/.test(cell) }">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
        </template>
        <template v-else-if="b.type === 'figure'">
          <div class="sl">{{ b.fno }} · {{ b.title }}</div>
          <div v-for="(f, fi) in b.flows" :key="fi" class="flowbox" style="margin-bottom: 6px">
            <template v-for="(n, i) in flowNodes(f)" :key="i">
              <span v-if="i" class="farr">→</span>
              <span class="fnode" :class="{ term: /失败|超时|拒绝/.test(n) }">{{ n }}</span>
            </template>
          </div>
        </template>
        <template v-else-if="b.type === 'exceptions'">
          <div class="sl">异常路径</div>
          <ul class="exc">
            <li v-for="(e, i) in b.items" :key="i"><span class="e">E{{ i + 1 }}</span><span>{{ e }}</span></li>
          </ul>
        </template>
      </template>

      <template v-if="r.rules.length">
        <div class="sl">规则</div>
        <div v-for="rule in r.rules" :key="rule.no" class="rline">
          <span class="rno" :data-rule="rule.no" title="点击查看可判定表述与出处">{{ rule.no }}</span>
          <!-- eslint-disable-next-line vue/no-v-html — 内容已 esc 白名单化 -->
          <p v-html="rule.html" />
          <span class="rv" :title="'违反判定'">{{ (det(rule.no)?.violation ?? '').slice(0, 14) || '—' }}</span>
          <!-- 规则详情 popover -->
          <div v-if="openRule === rule.no" class="popover" style="position: static; margin: 6px 0 0 46px; width: auto">
            <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 8px">
              <span style="font-family: var(--mono); font-weight: 700; font-size: 0.74rem; color: var(--primary-dark); background: var(--primary-soft); padding: 1px 8px; border-radius: 4px">{{ rule.no }}</span>
              <span style="font-size: 0.74rem; color: var(--muted)">规则详情</span>
            </div>
            <div style="font-size: 0.84rem; margin-bottom: 8px">
              <b style="font-size: 0.72rem; color: var(--faint); display: block; text-transform: uppercase; letter-spacing: 0.05em">怎样算违反</b>
              {{ det(rule.no)?.violation || '—' }}
            </div>
            <div v-if="det(rule.no)?.quote" style="font-size: 0.8rem; margin-bottom: 8px">
              <b style="font-size: 0.72rem; color: var(--faint); display: block; text-transform: uppercase; letter-spacing: 0.05em">出处引用</b>
              <span style="background: #FFFBEB; border-left: 2px solid #F59E0B; padding: 4px 9px; display: block; color: #78350F">“{{ det(rule.no)!.quote }}”</span>
            </div>
            <div v-if="matOf(rule.no)" style="font-size: 0.76rem; color: var(--muted)">
              {{ matOf(rule.no)!.filename }} <span class="hash">{{ matOf(rule.no)!.sha256.slice(0, 12) }}</span>
            </div>
            <div v-else style="font-size: 0.76rem; color: var(--muted)">图片类材料 · 跳过出处核对</div>
          </div>
        </div>
      </template>
      </template>
    </section>
    </div>
  </div>
</template>
