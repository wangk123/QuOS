<!-- 需求一页纸:画像式渲染(文档头四行→核心链路人工琥珀→主线/支撑能力卡→场景→待裁)。
     样式基准 web/prototype/onepager-r1.html(R3);卡色按序循环,点卡/正文↗ emit jump(章号串) -->
<script setup lang="ts">
import type { OneCard, OnePagerDoc } from '../../utils/onepager'

const props = defineProps<{ doc: OnePagerDoc }>()
const emit = defineEmits<{ jump: [chapters: string] }>()

const PALETTE = ['#2563EB', '#16A34A', '#CA8A04', '#0D9488', '#9333EA',
                 '#DC2626', '#C026D3', '#EA580C', '#6366F1', '#4D7C0F', '#0E7490']

const cards = () => props.doc.groups.flatMap((g) => g.cards)
const color = (c: OneCard) => PALETTE[cards().indexOf(c) % PALETTE.length]
</script>

<template>
  <div class="onepager">
    <header class="op-head">
      <div class="op-title-row">
        <h1>{{ doc.title }}</h1>
        <span class="op-tag">需求一页纸</span>
      </div>
      <div v-if="doc.meta.length" class="op-meta">{{ doc.meta.join(' · ') }}</div>
      <div class="op-rows">
        <template v-for="h in doc.head" :key="h.k">
          <span class="k">{{ h.k }}</span>
          <span class="v">{{ h.v }}</span>
        </template>
      </div>
    </header>

    <section v-if="doc.flow.length" class="op-flow">
      <div class="sec-t">核心链路 · 它是怎么工作的</div>
      <div class="flow">
        <template v-for="(n, i) in doc.flow" :key="i">
          <span v-if="i" class="farr">→</span>
          <span class="fnode" :class="{ human: n.human }">{{ n.label }}</span>
        </template>
      </div>
      <div v-if="doc.flowNote" class="flow-note"><b>琥珀色 = 人工环节</b>。{{ doc.flowNote }}</div>
    </section>

    <section v-for="g in doc.groups" :key="g.title" class="grp">
      <div class="grp-t">{{ g.title }}</div>
      <div class="op-grid">
        <div v-for="c in g.cards" :key="c.name" class="dom" :style="{ '--c': color(c) }"
             role="button" tabindex="0" title="点击跳转正文对应章" @click="emit('jump', c.chapters)">
          <div class="dom-h">
            <h2>{{ c.name }}</h2>
            <span v-if="c.role" class="role">{{ c.role }}</span>
            <span class="jump" title="跳转正文对应章">正文 ↗</span>
          </div>
          <p class="dom-body">
            <template v-for="(s, i) in c.segs" :key="i"><b v-if="s.hl">{{ s.t }}</b><template v-else>{{ s.t }}</template></template>
          </p>
        </div>
      </div>
    </section>

    <section v-if="doc.scenarios.length" class="op-tail">
      <span class="sec-t" style="margin: 0">场景速览</span>
      <span v-for="sc in doc.scenarios" :key="sc" class="scen-chip">{{ sc }}</span>
    </section>

    <section v-if="doc.todo.x || doc.todo.y || doc.todo.z" class="op-todo">
      <div class="todo-n t1"><span class="num">{{ doc.todo.x }}</span><span class="cap">送裁 · 选择</span></div>
      <div class="todo-n t2"><span class="num">{{ doc.todo.y }}</span><span class="cap">确认题</span></div>
      <div class="todo-n t3"><span class="num">{{ doc.todo.z }}</span><span class="cap">填空题</span></div>
      <span class="todo-hint">评审前先看文档末「问题清单」</span>
    </section>
  </div>
</template>

<style scoped>
.onepager { padding: 4px 2px 24px; font-size: 14px; line-height: 1.75; color: var(--ink, #1F2937); }
.op-head { background: #fff; border-radius: 14px; padding: 20px 24px; margin-bottom: 12px; }
.op-title-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.op-title-row h1 { font-size: 20px; font-weight: 700; }
.op-tag { font-size: 12px; font-weight: 600; color: #0E7C86; background: #E6F4F5; padding: 2px 10px; border-radius: 999px; }
.op-meta { color: #6B7280; font-size: 12.5px; margin-top: 4px; }
.op-rows { margin-top: 12px; display: grid; grid-template-columns: 76px 1fr; row-gap: 7px; column-gap: 10px; }
.op-rows .k { font-size: 12.5px; color: #9CA3AF; padding-top: 1px; }
.op-rows .v { font-size: 13.5px; color: #111827; }
.op-flow { background: #fff; border-radius: 14px; padding: 16px 24px; margin-bottom: 12px; }
.sec-t { font-size: 12px; font-weight: 600; color: #9CA3AF; letter-spacing: 0.08em; margin-bottom: 8px; }
.flow { display: flex; align-items: center; flex-wrap: wrap; row-gap: 8px; }
.fnode { font-size: 13px; font-weight: 600; color: #374151; background: #F3F4F6; border-radius: 8px; padding: 3px 11px; white-space: nowrap; }
.fnode.human { color: #92400E; background: #FEF3C7; border: 1px solid #FDE68A; }
.farr { color: #C4C9D0; margin: 0 6px; }
.flow-note { margin-top: 10px; font-size: 12.5px; color: #6B7280; }
.flow-note b { color: #92400E; font-weight: 600; }
.grp { margin-bottom: 12px; }
.grp-t { font-size: 13px; font-weight: 600; color: #6B7280; margin-bottom: 8px; padding-left: 2px; }
.op-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.dom { background: #fff; border-radius: 12px; padding: 13px 18px 12px; border-left: 4px solid var(--c); cursor: pointer; }
.dom:hover { box-shadow: 0 1px 6px rgb(0 0 0 / 8%); }
.dom-h { display: flex; align-items: center; gap: 9px; margin-bottom: 5px; }
.dom-h h2 { font-size: 14.5px; font-weight: 700; color: #111827; }
.dom-h .role { font-size: 12px; font-weight: 600; color: var(--c); }
.dom-h .jump { margin-left: auto; font-size: 12px; color: #C4C9D0; }
.dom-body { font-size: 13px; color: #4B5563; }
.dom-body b { color: var(--c); font-weight: 600; }
.op-tail { background: #fff; border-radius: 12px; padding: 12px 18px; margin-bottom: 12px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.scen-chip { font-size: 12.5px; color: #4B5563; background: #F3F4F6; border-radius: 999px; padding: 2px 12px; }
.op-todo { background: #fff; border-radius: 12px; padding: 12px 18px; display: flex; align-items: center; gap: 26px; flex-wrap: wrap; }
.todo-n { display: flex; align-items: baseline; gap: 7px; }
.todo-n .num { font-size: 23px; font-weight: 700; }
.todo-n .cap { font-size: 12px; color: #6B7280; }
.t1 .num { color: #B45309; } .t2 .num { color: #0E7C86; } .t3 .num { color: #6D28D9; }
.todo-hint { margin-left: auto; font-size: 12.5px; color: #9CA3AF; }
@media (max-width: 760px) { .op-grid { grid-template-columns: 1fr; } .op-rows { grid-template-columns: 1fr; } }
</style>
