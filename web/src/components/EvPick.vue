<script setup lang="ts">
// EvPick：材料多选 chips——替换原生 multiple select（原生列表丑且交互差）：pill 点选切换、选中蓝底、超长省略
import { computed } from 'vue'
import type { EvidenceItem } from '../api'

const props = defineProps<{ modelValue: string[]; evidence: EvidenceItem[]; excludeZip?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [ids: string[]] }>()

const list = computed(() => props.evidence.filter(e => !props.excludeZip || e.type !== '压缩包'))
const on = (id: string) => props.modelValue.includes(id)

function toggle(id: string) {
  emit('update:modelValue', on(id) ? props.modelValue.filter(x => x !== id) : [...props.modelValue, id])
}
</script>

<template>
  <div class="evpick" role="group" aria-label="选择材料">
    <button
      v-for="e in list" :key="e.id" type="button" class="evchip" :class="{ on: on(e.id) }"
      :title="e.name" :aria-pressed="on(e.id)" @click="toggle(e.id)"
    >{{ on(e.id) ? '✓ ' : '' }}{{ e.name }}</button>
    <span v-if="!list.length" class="none">池中还没有材料</span>
  </div>
</template>

<style scoped>
.evpick { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.evchip { background: #fff; color: var(--muted-fg); border: 1px solid var(--border2); border-radius: 999px;
  padding: 4px 12px; font-size: 12px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.evchip:hover { border-color: var(--secondary); background: #f8faff; }
.evchip.on { background: var(--blue-bg); color: var(--primary); border-color: var(--primary); font-weight: 600; }
.none { font-size: 11.5px; color: var(--muted-fg); align-self: center; }
</style>
