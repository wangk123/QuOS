<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { ApiError, answerClar, getClarifications, verifyClar, type Clarification } from '../api'
import AskDrawerV2 from './AskDrawerV2.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  close: []
  changed: []
}>()

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<Clarification[]>([])
const picks = ref<Record<number, number>>({})
const err = ref('')
const exported = ref(false)
// 新版预览开关：开=用户画像流+补材料题型（mock 示例数据），关=线上现状
const previewV2 = ref(false)

const stBadge: Record<string, [string, string]> = {
  wait: ['b-amber', '待问'],
  answered: ['b-blue', '已答·待实证'],
  verified: ['b-green', '已实证'],
}

async function load() {
  items.value = await getClarifications()
}

// 抽屉仅在打开时拉取（替代原视图 onMounted）
watch(
  () => props.open,
  v => {
    if (!v) return
    err.value = ''
    load().catch(e => {
      err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
    })
  },
)

const waiting = computed(() => items.value.filter(c => c.st === 'wait'))

const exportText = computed(() => {
  const lines = waiting.value.map(
    c => `${c.no}. ${c.q}\n   ${c.opts.map((o, i) => String.fromCharCode(65 + i) + '. ' + o).join('  ')}`,
  )
  return `【需求确认 ×${waiting.value.length}】本批，麻烦一次性回我：\n${lines.join('\n')}\n——回个编号+选项就行`
})

async function answer(c: Clarification) {
  try {
    await answerClar(c.no, picks.value[c.no] ?? 0)
    await load()
    emit('changed')
    toast(`${c.no} 已记录（口头答案=推测级）`)
  } catch (e) {
    toast(e instanceof ApiError ? `记录失败：${e.message}` : '记录失败', 'warn')
  }
}

async function verify(c: Clarification) {
  try {
    await verifyClar(c.no)
    await load()
    emit('changed')
    toast(`${c.no} 已标记确认${c.ref ? ' · 关联规则已同步核过' : ''}`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `标记失败：${e.message}` : '标记失败', 'warn')
  }
}

function copyExport() {
  navigator.clipboard?.writeText(exportText.value).then(
    () => toast('已复制', 'ok'),
    () => toast('手动选择复制'),
  )
}
</script>

<template>
  <div v-if="open" class="drawer-bg" @click.self="$emit('close')">
    <div class="drawer" :class="{ 'drawer-v2': previewV2 }" role="dialog" aria-modal="true">
      <AskDrawerV2 v-if="previewV2" :open="open" @close="$emit('close')" @toggle="previewV2 = false" />

      <template v-else>
      <div class="dw-hd">
        <h3>澄清池 <span class="src">{{ items.length }} 项 · 待问 {{ waiting.length }}</span></h3>
        <div class="hd-right">
          <label class="pv-toggle" title="用户画像流 + 补材料题型（示例数据）">
            <input v-model="previewV2" type="checkbox" />
            <span class="pv-track" aria-hidden="true" /><span class="pv-lbl">新版预览</span>
          </label>
          <button class="ghost" type="button" @click="$emit('close')">✕</button>
        </div>
      </div>
      <p class="dw-sub">攒一批一次问，给选择题不给问答题——规则提取/冲突裁决/查漏补缺的存疑项都汇到这里。</p>

      <p v-if="err" class="err">{{ err }}</p>
      <div class="card-box">
        <div class="hd">
          待问 / 已答 · {{ items.length }} 项
          <button class="btn" type="button" style="margin-left: auto" :disabled="!waiting.length" @click="exported = true">导出提问文本（发 IM）</button>
        </div>
        <table>
          <thead>
            <tr>
              <th style="width: 40px">#</th><th>问题</th><th style="width: 240px">选项</th>
              <th style="width: 110px">状态</th><th style="width: 190px">答案回收</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in items" :key="c.no">
              <td><span class="src">{{ c.no }}</span></td>
              <td>{{ c.q }}</td>
              <td>{{ c.opts.map((o, i) => String.fromCharCode(65 + i) + '. ' + o).join('　') }}</td>
              <td><span class="badge" :class="(stBadge[c.st] ?? stBadge['wait'])[0]">{{ (stBadge[c.st] ?? stBadge['wait'])[1] }}</span></td>
              <td>
                <template v-if="c.st === 'wait'">
                  <select v-model="picks[c.no]" style="font-size: 12px; padding: 3px 6px; border: 1px solid var(--border2); border-radius: 5px">
                    <option v-for="(_o, i) in c.opts" :key="i" :value="i">{{ String.fromCharCode(65 + i) }}</option>
                  </select>
                  <button class="btn-ghost btn-sm" type="button" @click="answer(c)">记录</button>
                </template>
                <template v-else-if="c.st === 'answered'">
                  <span class="src">答：{{ c.answer }}</span>
                  <button class="btn-ok btn-sm" type="button" @click="verify(c)">标记已确认</button>
                </template>
                <span v-else class="src">答：{{ c.answer }} ✓</span>
              </td>
            </tr>
            <tr v-if="!items.length">
              <td colspan="5" style="color: var(--muted-fg); padding: 24px; text-align: center">空——②冲突、④缺口、①无依据规则可转到这里</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="exported" class="card-box">
        <div class="hd">导出预览（复制发 IM）</div>
        <div class="bd">
          <div class="q-export">{{ exportText }}</div>
          <div style="margin-top: 10px">
            <button class="btn-ghost btn-sm" type="button" @click="copyExport">复制文本</button>
          </div>
        </div>
      </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.drawer-bg { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 90; }
.drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(720px, 92vw);
  background: #fff; box-shadow: -4px 0 24px rgba(0,0,0,.12); padding: 16px 20px; overflow-y: auto; }
.dw-hd { display: flex; justify-content: space-between; align-items: center; }
.hd-right { display: flex; align-items: center; gap: 10px; }
.pv-toggle { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; }
.pv-toggle input { position: absolute; opacity: 0; width: 0; height: 0; }
.pv-track { width: 30px; height: 17px; border-radius: 999px; background: var(--border2); position: relative; transition: background 0.18s; flex-shrink: 0; }
.pv-track::after { content: ''; position: absolute; top: 2px; left: 2px; width: 13px; height: 13px; border-radius: 50%; background: #fff; transition: transform 0.18s; box-shadow: 0 1px 2px rgba(0,0,0,.2); }
.pv-toggle input:checked + .pv-track { background: var(--primary); }
.pv-toggle input:checked + .pv-track::after { transform: translateX(13px); }
.pv-toggle input:focus-visible + .pv-track { outline: 2px solid var(--primary); outline-offset: 2px; }
.pv-lbl { font-size: 11.5px; color: var(--muted-fg); }
.drawer-v2 { width: min(880px, 94vw); overflow: hidden; display: flex; flex-direction: column; }
.dw-sub { font-size: 12px; color: var(--muted-fg); margin: 4px 0 12px; }
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
</style>
