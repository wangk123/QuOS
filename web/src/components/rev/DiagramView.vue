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

let seq = 0
watchEffect(async (onCleanup) => {
  const src = code.value
  if (!src) return
  // 竞态守卫:payload 先取基线快照再切草案会产生两轮渲染,旧一轮的异步结果
  // (尤其是失败)晚归时不得覆盖新一轮;每轮独立 id,残留清理互不误删
  const myId = uid + '-' + ++seq
  let stale = false
  onCleanup(() => { stale = true })
  failed.value = false
  try {
    const { svg: out } = await mermaid.render(myId, src)
    if (!stale) svg.value = out
  } catch {
    if (!stale) failed.value = true
  } finally {
    // mermaid 失败残留清理:错误卡容器 #id 与样式容器 d#id 会留在 body 末尾(文档流尾部堆积可见)
    document.getElementById(myId)?.remove()
    document.getElementById('d' + myId)?.remove()
  }
})
</script>

<template>
  <div class="diagram-box">
    <div v-if="svg && !failed" class="mmd" v-html="svg" />
    <!-- 降级为 bug 兜底(常态路径:导入时语法校验已拒收),显示时必须显式标注 -->
    <template v-else>
      <div v-if="source" class="mmd-degraded">⚠ 此图渲染失败,已降级显示源码——请修正 markdown 后重新导入</div>
      <div v-else class="mmd-degraded">⚠ 图渲染失败,降级为流程条显示</div>
      <div v-if="flows" class="flowbox">
        <template v-for="(n, i) in (flows.join(' → ').split('→'))" :key="i">
          <span v-if="i" class="farr">→</span>
          <span class="fnode">{{ n.trim() }}</span>
        </template>
      </div>
      <pre v-else-if="source" class="mmd-src">{{ source }}</pre>
    </template>
  </div>
</template>
