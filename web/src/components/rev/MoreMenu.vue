<!-- ⋮ 更多菜单:低频设置收纳(页宽三档,图形化选项),可扩展新分组 -->
<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ docWidth: string }>()
const emit = defineEmits<{ 'set-width': [w: string] }>()
const open = ref(false)

/* 页宽图形:页面轮廓 + 不同宽度填充条 */
function icon(w: number): string {
  return `<svg width="22" height="14" viewBox="0 0 22 14" fill="none"><rect x="0.5" y="0.5" width="21" height="13" rx="2.5" stroke="currentColor" opacity=".45"/><rect x="${w}" y="4" width="${22 - 2 * w}" height="6" rx="1" fill="currentColor"/></svg>`
}

const opts = [
  { k: 'normal', label: '常规', w: 7 },
  { k: 'wide', label: '超宽', w: 4 },
  { k: 'full', label: '全宽', w: 1.5 },
]
</script>

<template>
  <div class="more-wrap">
    <button class="more-btn" aria-label="更多设置" title="更多设置" @click.stop="open = !open">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
        <circle cx="12" cy="5" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="12" cy="19" r="1.6" />
      </svg>
    </button>
    <div v-if="open" class="more-menu" @click.stop>
      <div class="mm-t">阅读设置 · 页宽</div>
      <button v-for="o in opts" :key="o.k" :class="{ sel: props.docWidth === o.k }"
              @click="emit('set-width', o.k); open = false">
        <span class="mm-ic" v-html="icon(o.w)" /><span class="mm-lb">{{ o.label }}</span><span class="mm-dot" />
      </button>
    </div>
  </div>
</template>
