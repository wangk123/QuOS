<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { ApiError, assemble, assembleBatch, getProfile, getDoc, type Profile } from '../api'
import { aiBusy, curName, curPath } from '../router'
import { jobRunning, startJobPolling } from '../jobs'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const card = ref<Profile | null>(null)
const err = ref('')
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
    card.value = await getProfile(curPath.value)
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

// 树上切目标节点：同视图不重挂载，须跟随 curPath 重新拉取该节点画像
watch(curPath, async () => {
  card.value = null
  err.value = ''
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
  aiBusy.value = { label: 'AI 生成画像：规则挂树 · 标置信度 · 并入补充意见…' }
  try {
    await assemble(curPath.value, note.value.trim())
    await load()
    toast(note.value.trim() ? '画像已生成（补充意见已并入「补充说明」）' : '画像已生成 · 未实证规则标黄', 'ok')
  } catch (e) {
    if (e instanceof ApiError && e.unqualified) {
      toast(`生成被阻断：${e.unqualified.join('、')} 未核验/待实证——先回 ① 核验`, 'warn')
    } else {
      toast(e instanceof ApiError ? `生成失败：${e.message}` : '生成失败', 'warn')
    }
  } finally {
    aiBusy.value = null
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

/** 批量生成：创建后台任务（全部叶子），进度与汇总由 jobs.ts 轮询后端驱动——
 *  页面刷新/关闭不影响后端执行，重进页面自动恢复进度 */
async function assembleAll() {
  try {
    const r = await assembleBatch('')
    startJobPolling(r.job_id, toast)
    toast(`批量任务已创建：共 ${r.total} 个叶子，后台执行中`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `创建批量任务失败：${e.message}` : '创建批量任务失败', 'warn')
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
      <h2>③ 生成画像 · {{ curName }}</h2>
      <span class="sub">核验通过的规则聚合成需求画像草稿——挂不上的 = 树缺枝，补。</span>
      <div class="spacer" style="flex: 1" />
      <button class="btn-ghost" type="button" :disabled="!card" @click="openDoc">预览结果文档</button>
      <button class="btn-accent" type="button" :disabled="jobRunning" @click="assembleAll">
        {{ jobRunning ? '批量生成中…' : '生成全部叶子' }}</button>
      <button v-if="!card" class="btn" type="button" :disabled="!curPath" @click="openAssemble">生成选中（含子树）</button>
      <button v-else class="btn" type="button" @click="openAssemble">补充意见并重新生成</button>
    </div>

    <p v-if="err" class="err">{{ err }}</p>

    <div v-if="!card" class="empty">
      <template v-if="!curPath">先在左侧功能树选中整理目标（树叶节点）</template>
      <template v-else>规则就绪，点击「生成选中（含子树）」· {{ curName }}<br /><span style="font-size: 11.5px">（要求全部规则已核验且非「待实证」）</span></template>
    </div>

    <template v-else>
      <div class="spec-head">
        <h3>{{ card.node }}</h3>
        <span class="badge b-red">本次修改 · 高风险</span>
      </div>
      <div class="spec-meta">
        <span>画像 {{ card.rules.length }} 条规则</span>
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
        <b>未确认项（转澄清池）</b>{{ card.unconfirmed.join(' · ') }}
      </div>
      <div v-else class="warn-strip ok-strip">
        <b>✓ 全部规则已实证</b>用户画像可存档进基线
      </div>
    </template>

    <div v-if="showAssemble" class="modal-bg" @click.self="showAssemble = false">
      <div class="modal" role="dialog" aria-modal="true">
        <h3>AI 生成 / 重新生成画像</h3>
        <p style="font-size: 12px; color: var(--muted-fg); margin-bottom: 8px">
          补充你的意见（AI 不知道的：口头约定、历史坑、业务约束）——它会并入用户画像「补充说明」并影响规则。
        </p>
        <textarea v-model="note" placeholder="如：张开发说重试时余额要校验；上次生产事故就是金额改了没同步" />
        <div class="foot">
          <button class="btn-ghost" type="button" @click="showAssemble = false">取消</button>
          <button class="btn" type="button" @click="doAssemble">生成画像</button>
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
