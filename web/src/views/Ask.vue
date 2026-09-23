<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { ApiError, answerClar, getClarifications, verifyClar, type Clarification } from '../api'
import { curName } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<Clarification[]>([])
const picks = ref<Record<number, number>>({})
const err = ref('')
const exported = ref(false)

const stBadge: Record<string, [string, string]> = {
  wait: ['b-amber', '待问'],
  answered: ['b-blue', '已答·待实证'],
  verified: ['b-green', '已实证'],
}

async function load() {
  items.value = await getClarifications()
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
  }
})

const waiting = computed(() => items.value.filter(c => c.st === 'wait'))

const exportText = computed(() => {
  const lines = waiting.value.map(
    c => `${c.no}. ${c.q}\n   ${c.opts.map((o, i) => String.fromCharCode(65 + i) + '. ' + o).join('  ')}`,
  )
  return `【需求确认 ×${waiting.value.length}】${curName.value}，麻烦一次性回我：\n${lines.join('\n')}\n——回个编号+选项就行`
})

async function answer(c: Clarification) {
  try {
    await answerClar(c.no, picks.value[c.no] ?? 0)
    await load()
    toast(`${c.no} 已记录（口头答案=推测级）`)
  } catch (e) {
    toast(e instanceof ApiError ? `记录失败：${e.message}` : '记录失败', 'warn')
  }
}

async function verify(c: Clarification) {
  try {
    await verifyClar(c.no)
    await load()
    toast(`${c.no} 已实证：答案与代码一致，规则升级实证`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `实证失败：${e.message}` : '实证失败', 'warn')
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
  <div>
    <div class="view-head">
      <h2>⑤ 问人 · {{ curName }}</h2>
      <span class="sub">攒一批一次问，给选择题不给问答题。</span>
      <div class="spacer" style="flex: 1" />
      <button class="btn" type="button" :disabled="!waiting.length" @click="exported = true">导出提问文本（发 IM）</button>
    </div>

    <p v-if="err" class="err">{{ err }}</p>
    <div class="card-box">
      <div class="hd">待问 / 已答 · {{ items.length }} 项</div>
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
                <button class="btn-ok btn-sm" type="button" @click="verify(c)">落码验证</button>
              </template>
              <span v-else class="src">答：{{ c.answer }} ✓</span>
            </td>
          </tr>
          <tr v-if="!items.length">
            <td colspan="5" style="color: var(--muted-fg); padding: 24px; text-align: center">空——在 ②③ 把矛盾/空白转过来</td>
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
  </div>
</template>

<style scoped>
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
</style>
