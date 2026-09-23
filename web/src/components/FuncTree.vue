<script setup lang="ts">
import type { TreeNode } from '../api'
import FuncTreeNode from './FuncTreeNode.vue'

defineProps<{ nodes: TreeNode[]; curPath: string }>()
const emit = defineEmits<{
  pick: [path: string]
  toggle: [path: string]
  op: [op: 'add' | 'rename' | 'del', path: string]
}>()
</script>

<template>
  <div class="tree-title">
    <span>功能树（任意层级）</span>
    <button type="button" class="root-add" data-op="add" @click="emit('op', 'add', '')">＋ 根节点</button>
  </div>
  <div class="func-tree">
    <FuncTreeNode
      :nodes="nodes"
      prefix=""
      :depth="0"
      :cur-path="curPath"
      @pick="p => emit('pick', p)"
      @toggle="p => emit('toggle', p)"
      @op="(o, p) => emit('op', o, p)"
    />
    <div v-if="!nodes.length" class="tree-empty">（空——点右上「＋ 根节点」开始）</div>
  </div>
  <div class="tree-legend">hover 节点 → 右侧出图标按钮（加 / 改 / 删）</div>
</template>

<style scoped>
.tree-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted-fg);
  letter-spacing: 0.05em;
  padding: 4px 8px 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.tree-title .root-add { font-size: 11px; color: var(--primary); background: none; padding: 2px 6px; }
.tree-empty { padding: 16px 8px; color: var(--muted-fg); font-size: 12px; }
.tree-legend {
  font-size: 10.5px;
  color: var(--muted-fg);
  padding: 10px 8px 4px;
  line-height: 1.9;
  border-top: 1px solid var(--border);
  margin-top: 8px;
}
</style>
