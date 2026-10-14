<!-- 版本页:时间线(草案评审中+历史定稿)、条款变更 diff、「回退到此版」 -->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getBaseline, getChanges, getDraft, getVersions, revertDoc } from '../api'
import { route } from '../router'
import { toast } from '../components/toast'
import AppModal from '../components/AppModal.vue'

const versions = ref<any[]>([])
const baseline = ref<any>(null)
const hasDraft = ref(false)
const selVer = ref('')
const changes = ref<any[]>([])
const expanded = ref<Set<number>>(new Set())
const reverting = ref<any>(null)

async function load() {
  versions.value = await getVersions(route.pid)
  baseline.value = await getBaseline(route.pid)
  hasDraft.value = (await getDraft(route.pid)).empty !== true
  if (!selVer.value || !versions.value.some((v) => v.version === selVer.value)) {
    selVer.value = versions.value[0]?.version ?? ''
  }
  await loadChanges()
}
async function loadChanges() {
  if (!selVer.value) {
    changes.value = []
    return
  }
  changes.value = await getChanges(route.pid, selVer.value)
}
onMounted(load)

function select(v: string) {
  selVer.value = v
  expanded.value = new Set()
  loadChanges()
}
function toggleRow(i: number) {
  const s = new Set(expanded.value)
  if (s.has(i)) s.delete(i)
  else s.add(i)
  expanded.value = s
}
async function doRevert() {
  const v = reverting.value?.version
  if (!v) return
  await revertDoc(route.pid, v)
  reverting.value = null
  toast(`已回退,当前基线 ${v}`, 'warn')
  load()
}
const kindTag: Record<string, { cls: string; label: string }> = {
  added: { cls: 'ok', label: '新增' },
  modified: { cls: 'warn', label: '修改' },
  voided: { cls: 'err', label: '作废' },
}
</script>

<template>
  <div class="content">
    <div class="page-head">
      <div>
        <h1 class="pv">版本</h1>
        <div class="pv-sub">定稿即基线:只增不改,条款级变更留痕,可回看任意历史版与回退</div>
      </div>
    </div>
    <div class="ver-layout">
      <div class="card" style="padding: 14px 12px 6px">
        <div class="vline">
          <div v-if="hasDraft" class="vitem">
            <div class="vv">(草案)<span class="tag warn"><span class="dot" />评审中</span></div>
            <div class="vd">尚未发版 · 去「文档评审」处理批注后定稿</div>
          </div>
          <div v-for="v in versions" :key="v.version" class="vitem" :class="{ sel: v.version === selVer }" @click="select(v.version)">
            <div class="vv">
              {{ v.version }}
              <span class="tag" :class="baseline?.version === v.version ? 'ok' : 'mute'">
                <span class="dot" />{{ baseline?.version === v.version ? '当前基线' : '历史' }}
              </span>
              <button class="btn sm v-act" title="以该版为当前基线" @click.stop="reverting = v">回退到此版</button>
            </div>
            <div class="vd">{{ v.created_at.slice(0, 10) }} · {{ v.note || '—' }}</div>
          </div>
          <div v-if="!versions.length && !hasDraft" class="empty" style="padding: 16px">尚无版本</div>
        </div>
      </div>

      <div>
        <div class="page-head" style="margin-bottom: 12px">
          <div><h1 class="pv" style="font-size: 1.05rem">{{ selVer || '—' }} 变更记录</h1></div>
        </div>
        <div v-for="(c, i) in changes" :key="i" class="crow">
          <div class="ch" @click="toggleRow(i)">
            <span class="cno">{{ c.rule_no }}</span>
            <span class="tag" :class="kindTag[c.kind]?.cls"><span class="dot" />{{ kindTag[c.kind]?.label }}</span>
            <span class="cs">{{ c.new_text || c.old_text }}</span>
            <span style="color: var(--faint); font-size: 0.78rem">▾</span>
          </div>
          <div v-if="expanded.has(i)" class="cb">
            <div v-if="c.kind === 'modified'" class="diff2">
              <div class="old"><div class="dl">旧</div><div class="dt">{{ c.old_text }}</div></div>
              <div class="new"><div class="dl">新</div><div class="dt">{{ c.new_text }}</div></div>
            </div>
            <div v-else-if="c.kind === 'added'" class="diff2">
              <div class="new" style="grid-column: 1/3"><div class="dl">新增内容</div><div class="dt">{{ c.new_text }}</div></div>
            </div>
            <div v-else-if="c.kind === 'voided'" class="diff2">
              <div class="old" style="grid-column: 1/3"><div class="dl">作废内容</div><div class="dt">{{ c.old_text }}</div></div>
            </div>
            <div class="cmeta">
              <span>原因:{{ c.reason || '—' }}</span><span>批准:{{ c.approver }}</span>
            </div>
          </div>
        </div>
        <div v-if="!changes.length" class="card"><div class="empty">{{ selVer ? '该版本无变更记录' : '发版后生成变更记录' }}</div></div>
      </div>
    </div>

    <AppModal v-if="reverting" :title="`回退到 ${reverting.version}`" @close="reverting = null">
      <p style="font-size: 0.9rem; color: var(--fg-2)">将 <b>{{ reverting.version }}</b> 设为当前基线:</p>
      <ul style="font-size: 0.86rem; color: var(--fg-2); display: grid; gap: 6px; padding-left: 18px; margin-top: 8px">
        <li>后续草案基于 <b>{{ reverting.version }}</b> 加工</li>
        <li>{{ reverting.version }} 之后的版本保留在历史中,不删除</li>
      </ul>
      <p style="font-size: 0.8rem; color: var(--muted); margin-top: 12px">当前评审中的草案将作废,需 agent 重新基于基线提交。</p>
      <template #foot>
        <button class="btn" @click="reverting = null">取消</button>
        <button class="btn primary" @click="doRevert">确认回退</button>
      </template>
    </AppModal>
  </div>
</template>
