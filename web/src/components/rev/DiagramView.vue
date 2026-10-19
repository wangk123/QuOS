<!-- 图渲染:HTML 图源(diagram-design 产物)iframe sandbox 渲染(禁脚本,高自适应);
     存量 mermaid 源降级显示源码+重画提示;flows(线性链路)流程条为主路径 -->
<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ flows?: string[]; source?: string; title?: string }>()

const isHtml = computed(() => /<svg|<!doctype html/i.test(props.source ?? ''))

// 存量 mermaid 源码可能仍带围栏包裹(旧数据),显示前剥掉
const legacyText = computed(() =>
  (props.source ?? '').replace(/^\s*```(mermaid)?|```\s*$/g, '').trim())

const FRAME_MAX_H = 2000   // 异常 HTML 防撑爆页面的高度上限

function onFrameLoad(e: Event) {
  const frame = e.target as HTMLIFrameElement
  try {
    const h = frame.contentDocument?.body?.scrollHeight ?? 0
    if (h > 0) frame.style.height = Math.min(h, FRAME_MAX_H) + 'px'
  } catch { /* 读取受限时保持默认高度,不阻塞显示 */ }
}
</script>

<template>
  <div class="diagram-box">
    <iframe v-if="isHtml" class="mmd-frame" :srcdoc="source" sandbox="allow-same-origin"
            style="width: 100%; border: 0; height: 480px" title="图" @load="onFrameLoad" />
    <template v-else>
      <div v-if="source" class="mmd-degraded">⚠ 存量 mermaid 图，待迭代重画为 diagram-design（图源已单轨）</div>
      <pre v-if="source" class="mmd-src">{{ legacyText }}</pre>
      <div v-if="flows" class="flowbox">
        <template v-for="(n, i) in (flows.join(' → ').split('→'))" :key="i">
          <span v-if="i" class="farr">→</span>
          <span class="fnode">{{ n.trim() }}</span>
        </template>
      </div>
    </template>
  </div>
</template>
