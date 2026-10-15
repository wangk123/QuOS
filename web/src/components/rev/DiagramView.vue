<!-- 图渲染:flows(线性链路)与 mermaid 源码统一渲染——flows 自动生成 flowchart TD;失败降级(流程条/源码) -->
<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import mermaid from 'mermaid'

const props = defineProps<{ flows?: string[]; source?: string; title?: string }>()

mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'strict', htmlLabels: false, flowchart: { htmlLabels: false } })
// 每实例随机 uid:组件级 seq 会让多张图 SVG id 相同,内嵌 #id 样式与箭头 marker 全局冲突(节点重叠/错位根因)
const uid = 'mmd-' + Math.random().toString(36).slice(2, 10)

const code = computed(() => {
  if (props.source) return props.source.replace(/^\s*```(mermaid)?|```\s*$/g, '').trim()
  const flows = props.flows ?? []
  const edges: string[] = []
  const id: string[] = []   // 链内节点 id 共享:一条 flow 串成 n1-->n2-->n3
  let n = 0
  const esc = (t: string) => t.replace(/["\\]/g, '').replace(/[<>{}|]/g, ' ')
  for (const f of flows) {
    const nodes = f.split('→').map((s) => s.trim()).filter(Boolean)
    for (let i = 0; i < nodes.length; i++) {
      id.push('n' + ++n)
      edges.push(id[i] + '["' + esc(nodes[i]) + '"]')
    }
    for (let i = 0; i + 1 < nodes.length; i++) edges.push(id[i] + ' --> ' + id[i + 1])
    id.length = 0
  }
  return `flowchart TD\n${edges.join('\n')}`
})

const svg = ref('')
const failed = ref(false)

watchEffect(async () => {
  const src = code.value
  if (!src) return
  failed.value = false
  try {
    const { svg: out } = await mermaid.render(uid, src)
    svg.value = out
  } catch {
    failed.value = true
  }
})
</script>

<template>
  <div class="diagram-box">
    <div v-if="svg && !failed" class="mmd" v-html="svg" />
    <!-- 降级:flows 回退节点流程条;源码回退代码块 -->
    <div v-else-if="flows" class="flowbox">
      <template v-for="(n, i) in (flows.join(' → ').split('→'))" :key="i">
        <span v-if="i" class="farr">→</span>
        <span class="fnode">{{ n.trim() }}</span>
      </template>
    </div>
    <pre v-else-if="source" class="mmd-src">{{ source }}</pre>
  </div>
</template>
