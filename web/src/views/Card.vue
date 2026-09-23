<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { ApiError, assemble, getCard, getDoc, type Card } from '../api'
import { curName, curPath } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const card = ref<Card | null>(null)
const err = ref('')
const aiLabel = ref('')
const showAssemble = ref(false)
const note = ref('')
const showDoc = ref(false)
const docText = ref('')

const confBadge: Record<string, [string, string]> = {
  实证: ['b-green', '代码实证'],
  文档: ['b-blue', '文档'],
  推测: ['b-amber', '推测 ⚠'],
  待实证: ['b-red', 'AI待实证'],
  旧文档: ['b-gray', '旧文档'],
  冲突: ['b-red', '冲突'],
}

async function load() {
  if (!curPath.value) return
  try {
    card.value = await getCard(curPath.value)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) card.value = null
    else throw e
  }
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
  }
})

const waitCnt = computed(() => card.value?.unconfirmed.length ?? 0)

function openAssemble() {
  note.value = card.value?.note ?? ''
  showAssemble.value = true
}

async function doAssemble() {
  showAssemble.value = false
  aiLabel.value = 'AI 组装卡片：断言挂树 · 标置信度 · 并入补充意见…'
  try {
    await assemble(curPath.value, note.value.trim())
    await load()
    toast(note.value.trim() ? '卡片已生成（补充意见已并入「补充说明」）' : '卡片已生成 · 未实证规则标黄', 'ok')
  } catch (e) {
    if (e instanceof ApiError && e.unqualified) {
      toast(`组装被阻断：${e.unqualified.join('、')} 未核验/待实证——先回 ① 核验`, 'warn')
    } else {
      toast(e instanceof ApiError ? `组装失败：${e.message}` : '组装失败', 'warn')
    }
  } finally {
    aiLabel.value = ''
  }
}

async function openDoc() {
  try {
    docText.value = await getDoc()
    showDoc.value = true
  } catch (e) {
    toast(e instanceof ApiError ? `导出失败：${e.message}` : '导出失败', 'warn')
  }
}

function copyDoc() {
  navigator.clipboard?.writeText(docText.value).then(
    () => toast('已复制', 'ok'),
    () => toast('手动选择复制'),
  )
}

function downloadDoc() {
  const blob = new Blob([docText.value], { type: 'text/markdown' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = '结构化需求规格.md'
  a.click()
  URL.revokeObjectURL(a.href)
  toast('已下载 .md', 'ok')
}
</script>

<template>
  <div>
    <div class="view-head">
      <h2>④ 成卡片 · {{ curName }}</h2>
      <span class="sub">断言挂到树叶上；挂不上的 = 树缺枝，补。</span>
      <div class="spacer" style="flex: 1" />
      <button class="btn-ghost" type="button" :disabled="!card" @click="openDoc">预览结果文档</button>
      <button v-if="!card" class="btn" type="button" :disabled="!curPath" @click="openAssemble">AI 组装卡片草稿</button>
      <button v-else class="btn" type="button" @click="openAssemble">补充意见并重新生成</button>
    </div>

    <p v-if="err" class="err">{{ err }}</p>
    <div v-if="aiLabel" class="ai-run">
      <span class="spin" /><span>{{ aiLabel }}</span><div class="bar"><i /></div>
    </div>

    <div v-if="!card" class="empty">
      <template v-if="!curPath">先在左侧功能树选中整理目标（树叶节点）</template>
      <template v-else>断言就绪，点击「AI 组装卡片草稿」· {{ curName }}<br /><span style="font-size: 11.5px">（组装要求全部断言已核验且非「待实证」）</span></template>
    </div>

    <template v-else>
      <div class="spec-head">
        <h3>{{ card.node }}</h3>
        <span class="badge b-red">本次修改 · 高风险</span>
      </div>
      <div class="spec-meta">
        <span>断言 {{ card.rules.length }} 条规则</span>
        <span>待确认 {{ waitCnt }} 项</span>
      </div>
      <div class="spec-grid">
        <div class="k">业务目标</div><div class="v">{{ card.goal || '—' }}</div>
        <div class="k">入口 / 触发</div><div class="v">{{ card.entry || '—' }}</div>
        <div class="k">主流程</div><div class="v">{{ card.flow || '—' }}</div>
        <div class="k">规则</div>
        <div class="v">
          <div v-for="r in card.rules" :key="r.id" class="rule-row">
            <span class="rule-id">{{ r.id }}</span>{{ r.text }}<span class="src">{{ r.src }}</span>
            <span class="badge" :class="(confBadge[r.conf] ?? confBadge['旧文档'])[0]">{{ (confBadge[r.conf] ?? confBadge['旧文档'])[1] }}</span>
          </div>
          <div v-if="!card.rules.length" style="color: var(--muted-fg)">—</div>
        </div>
        <div class="k">状态机</div><div class="v">{{ card.states || '—' }}</div>
        <div class="k">异常边界</div><div class="v">{{ card.boundaries || '—' }}</div>
        <div class="k">补充说明</div>
        <div class="v">
          <template v-if="card.note">{{ card.note }} <span class="badge b-amber">人工补充</span></template>
          <template v-else>—（AI 生成后可补充意见重新生成）</template>
        </div>
        <div class="k">依赖</div><div class="v">{{ card.deps || '—' }}</div>
      </div>
      <div v-if="waitCnt" class="warn-strip">
        <b>未确认项（转「问人」）</b>{{ card.unconfirmed.join(' · ') }}
      </div>
      <div v-else class="warn-strip ok-strip">
        <b>✓ 全部规则已实证</b>卡片可存档进基线
      </div>
    </template>

    <div v-if="showAssemble" class="modal-bg" @click.self="showAssemble = false">
      <div class="modal" role="dialog" aria-modal="true">
        <h3>AI 组装 / 重新生成卡片</h3>
        <p style="font-size: 12px; color: var(--muted-fg); margin-bottom: 8px">
          补充你的意见（AI 不知道的：口头约定、历史坑、业务约束）——它会并入卡片「补充说明」并影响规则。
        </p>
        <textarea v-model="note" placeholder="如：张开发说重试时余额要校验；上次生产事故就是金额改了没同步" />
        <div class="foot">
          <button class="btn-ghost" type="button" @click="showAssemble = false">取消</button>
          <button class="btn" type="button" @click="doAssemble">生成卡片</button>
        </div>
      </div>
    </div>

    <div v-if="showDoc" class="modal-bg" @click.self="showDoc = false">
      <div class="modal wide" role="dialog" aria-modal="true">
        <h3>最终结果文档 · 结构化需求规格（自动生成）</h3>
        <div class="q-export" style="max-height: 52vh; overflow: auto">{{ docText }}</div>
        <div class="foot">
          <button class="btn-ghost" type="button" @click="showDoc = false">关闭</button>
          <button class="btn-ghost" type="button" @click="copyDoc">复制</button>
          <button class="btn" type="button" @click="downloadDoc">下载 .md</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
</style>
