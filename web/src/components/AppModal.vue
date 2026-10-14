<!-- 共用 UI:toast 与 Modal(Vue 化,样式取原型) -->
<script setup lang="ts">
// Modal:teleport 到 body,esc/遮罩关闭
import { onMounted, onUnmounted } from 'vue'

const props = defineProps<{ title: string }>()
const emit = defineEmits<{ close: [] }>()

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onUnmounted(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <teleport to="body">
    <div class="overlay" @click.self="emit('close')">
      <div class="dialog" role="dialog" aria-modal="true">
        <div class="d-head">
          <h3>{{ title }}</h3>
          <button class="icon-btn" aria-label="关闭" @click="emit('close')">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
          </button>
        </div>
        <div class="d-body"><slot /></div>
        <div class="d-foot"><slot name="foot" /></div>
      </div>
    </div>
  </teleport>
</template>
