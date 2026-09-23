<script setup lang="ts">
import type { TreeNode } from '../api'

const props = defineProps<{ nodes: TreeNode[]; prefix: string; depth: number; curPath: string }>()
const emit = defineEmits<{
  pick: [path: string]
  toggle: [path: string]
  op: [op: 'add' | 'rename' | 'del', path: string]
}>()

const pathOf = (i: number) => (props.prefix ? `${props.prefix},${i}` : `${i}`)
const hasKids = (n: TreeNode) => n.children.length > 0
</script>

<template>
  <template v-for="(n, i) in nodes" :key="pathOf(i)">
    <div
      class="node"
      :class="{ l0: depth === 0, active: pathOf(i) === curPath }"
      role="button"
      tabindex="0"
      :data-path="pathOf(i)"
      @click="emit('pick', pathOf(i))"
      @keydown.enter="emit('pick', pathOf(i))"
    >
      <span v-for="g in depth" :key="g" class="ig" />
      <button
        class="caret-btn"
        :class="{ open: n.open, leaf: !hasKids(n) }"
        type="button"
        aria-label="展开/折叠"
        @click.stop="hasKids(n) && emit('toggle', pathOf(i))"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6"><path d="M9 6l6 6-6 6" /></svg>
      </button>
      <span class="nm">{{ n.name }}</span>
      <span v-if="n.stats?.ok && !n.stats?.warn" class="nbadge okc" title="卡片已实证">
        <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2"><path d="M20 6L9 17l-5-5" /></svg>
      </span>
      <span v-if="n.stats?.warn" class="nbadge warn" :title="`待确认 ${n.stats.warn} 项（空白/矛盾/推测）`">{{ n.stats.warn }}</span>
      <span v-if="n.stats?.asrt" class="nbadge cnt" :title="`${n.stats.asrt} 条断言`">{{ n.stats.asrt }}</span>
      <span class="nops">
        <button type="button" data-op="add" title="加子节点" @click.stop="emit('op', 'add', pathOf(i))">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14" /></svg>
        </button>
        <button type="button" data-op="rename" title="改名" @click.stop="emit('op', 'rename', pathOf(i))">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.83 2.83 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z" /></svg>
        </button>
        <button type="button" class="del" data-op="del" title="删除" @click.stop="emit('op', 'del', pathOf(i))">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6" /></svg>
        </button>
      </span>
    </div>
    <FuncTreeNode
      v-if="hasKids(n) && n.open"
      :nodes="n.children"
      :prefix="pathOf(i)"
      :depth="depth + 1"
      :cur-path="curPath"
      @pick="p => emit('pick', p)"
      @toggle="p => emit('toggle', p)"
      @op="(o, p) => emit('op', o, p)"
    />
  </template>
</template>

<style scoped>
.node {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px 6px 4px 2px;
  border-radius: 6px;
  color: #334155;
  font-size: 12.5px;
  cursor: pointer;
  position: relative;
  min-height: 26px;
}
.node:hover { background: var(--muted); }
.node.active {
  background: var(--blue-bg);
  color: var(--primary);
  font-weight: 600;
  box-shadow: inset 2.5px 0 0 var(--primary);
}
.node .ig { width: 14px; align-self: stretch; flex-shrink: 0; position: relative; margin: 0 1px; }
.node .ig::before {
  content: '';
  position: absolute;
  left: 7px;
  top: 2px;
  bottom: 2px;
  border-left: 1px solid #e2e8f0;
}
.node:hover .ig::before { border-color: #cbd5e1; }
.caret-btn {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
  border: none;
  background: none;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  padding: 0;
}
.caret-btn:hover { background: #fff; color: var(--primary); }
.caret-btn svg { width: 11px; height: 11px; transition: transform 0.15s; }
.caret-btn.open svg { transform: rotate(90deg); }
.caret-btn.leaf { visibility: hidden; }
.nm {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 3px;
}
.node.l0 > .nm { font-weight: 600; letter-spacing: 0.01em; }
.nbadge {
  height: 16px;
  min-width: 17px;
  padding: 0 5px;
  border-radius: 9px;
  font-size: 9.5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: var(--mono);
  font-weight: 700;
  flex-shrink: 0;
  line-height: 1;
  margin-right: 2px;
}
.nbadge.warn { background: #f59e0b; color: #fff; }
.nbadge.cnt { color: #b6c2d2; font-weight: 500; }
.nbadge.okc { width: 16px; min-width: 16px; padding: 0; background: var(--green-bg); color: #16a34a; border-radius: 50%; }
.nops {
  display: none;
  gap: 1px;
  flex-shrink: 0;
  position: absolute;
  right: 4px;
  padding-left: 14px;
  background: linear-gradient(to right, rgba(255, 255, 255, 0), #fff 16px);
}
.node:hover .nops,
.node.active .nops { display: flex; }
.node.active .nops { background: linear-gradient(to right, rgba(219, 234, 254, 0), var(--blue-bg) 16px); }
.nops button {
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  color: #94a3b8;
  padding: 0;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.nops button:hover { background: var(--blue-bg); color: var(--primary); }
.nops button.del:hover { background: var(--red-bg); color: var(--destructive); }
.nops svg { width: 11px; height: 11px; }
</style>
