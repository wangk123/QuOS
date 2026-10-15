<!-- 文档评审页(核心):固定视口三栏独立滚动;无草案时渲染基线只读态 -->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { answerQuestion, finalizeDoc, getBaseline, getDraft, getProject, getVersions, listMaterials, listQuestions, ApiError } from '../api'
import { route, go } from '../router'
import { toast } from '../components/toast'
import AppModal from '../components/AppModal.vue'
import ChapterTree from '../components/rev/ChapterTree.vue'
import DocPaper from '../components/rev/DocPaper.vue'
import AnnotationRail from '../components/rev/AnnotationRail.vue'
import { GLOSSARY_CH_ID } from '../utils/chapters'

const projName = ref('')
const draft = ref<any>(null)
const baseline = ref<any>(null)
const annos = ref<any[]>([])
const materials = ref<any[]>([])
const versions = ref<any[]>([])

const mode = ref<'side' | 'focus'>('side')
/* 章节目录三态:固定(常驻挤占正文)/悬浮(鼠标移入浮现、移开隐藏)/隐藏(只留把手);固定态记忆到 localStorage */
const tocPinned = ref(localStorage.getItem('quos.tocPin') === '1')
const tocHover = ref(false)
const tocMode = computed(() => (tocPinned.value ? 'pinned' : tocHover.value ? 'hover' : 'hidden') as 'pinned' | 'hover' | 'hidden')
watch(tocPinned, v => localStorage.setItem('quos.tocPin', v ? '1' : '0'))
function togglePin() {
  tocPinned.value = !tocPinned.value
  if (!tocPinned.value) tocHover.value = true // 指针还在面板上:先转悬浮,移开再隐藏
}
function tocShow() { if (!tocPinned.value) tocHover.value = true }
function tocHide() { if (!tocPinned.value) tocHover.value = false }
const focusIdx = ref(0)
const openSet = ref(new Set<number>())
const activeId = ref<number | null>(null)
const showFinalize = ref(false)
const fin = ref({ version: '', note: '' })
const finErr = ref(false)

const payload = computed(() => {
  const src: any = draft.value?.payload ?? baseline.value?.snapshot ?? null
  if (!src) return null
  // 深拷贝后加工:computed 内不得 mutate 响应式源(旧写法改 raw.chapters 触发递归更新)
  const raw = JSON.parse(JSON.stringify(src))
  raw.glossary ??= []
  raw.new_terms ??= []
  raw.chapters = (raw.chapters ?? []).map((c: any) => {
    const ch = { blocks: [], rule_nos: [], parent: null, background: '', pri: 'P1', ...c }
    // 旧快照兼容:无 blocks 时把旧 states/exceptions 槽合成为块,渲染路径单一
    if (!ch.blocks?.length) {
      if (ch.states) ch.blocks = [{ type: 'states', text: ch.states }, ...ch.blocks]
      if (ch.exceptions?.length) ch.blocks = [...ch.blocks, { type: 'exceptions', items: ch.exceptions }]
    }
    return ch
  })
  raw.rules ??= {}
  // 术语表合成为文档末章(编号随 flatten 自动顺延):目录出现单条入口,正文渲染词条表,不再整块塞进目录栏
  if (raw.glossary.length) {
    raw.chapters = [...raw.chapters,
      { id: GLOSSARY_CH_ID, title: '术语表', pri: '', parent: null, background: '', blocks: [], rule_nos: [] }]
  }
  return raw
})
const hasDraft = computed(() => !!draft.value && draft.value.empty !== true)
const verLabel = computed(() => (hasDraft.value ? `${baseline.value?.version ?? '首版'} · 草案评审中` : baseline.value?.version ?? '—'))
const summary = computed(() =>
  payload.value ? `${payload.value.chapters.filter((c: any) => c.id !== GLOSSARY_CH_ID).length} 章 · ${Object.keys(payload.value.rules).length} 条规则` : '')
const suggestedVer = computed(() => `v${versions.value.length + 1}`)

async function load() {
  const p = await getProject(route.pid)
  projName.value = p.name
  materials.value = await listMaterials(route.pid)
  versions.value = await getVersions(route.pid)
  baseline.value = await getBaseline(route.pid)
  draft.value = await getDraft(route.pid)
  const all = await listQuestions(route.pid)
  annos.value = all.filter((q: any) => q.status !== 'withdrawn')
}
onMounted(load)

/* 批注分组标题注入章节名(anchor 只有 chapter_id) */
watch(payload, (p) => {
  if (!p) return
  const titles = new Map(p.chapters.map((c: any) => [c.id, c.title]))
  for (const a of annos.value) {
    if (a.anchor?.chapter_id) a.anchor.chapter_title = titles.get(a.anchor.chapter_id) ?? a.anchor.chapter_id
  }
})

/* ── 交互 ── */
function toggle(qid: number) {
  const s = new Set(openSet.value)
  if (s.has(qid)) s.delete(qid)
  else s.add(qid)
  openSet.value = s
}
async function locateAnno(qid: number) {
  activeId.value = qid
  openSet.value = new Set([...openSet.value, qid])
  await nextTick()
  const mk = document.getElementById('mk-' + qid)
  if (mk) {
    mk.scrollIntoView({ behavior: 'smooth', block: 'center' })
    mk.classList.add('hit')
    setTimeout(() => mk.classList.remove('hit'), 1400)
    return
  }
  const a = annos.value.find((q: any) => q.id === qid)
  if (a?.anchor?.chapter_id) {
    document.getElementById('ch-' + a.anchor.chapter_id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}
async function activateFromDoc(qid: number) {
  activeId.value = qid
  openSet.value = new Set([...openSet.value, qid])
  await nextTick()
  document.getElementById('ac-' + qid)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}
async function answer(qid: number, ans: any) {
  try {
    const updated = await answerQuestion(qid, ans)
    const q = annos.value.find((x: any) => x.id === qid)
    if (q) {
      Object.assign(q, updated)
      openSet.value.delete(qid) // 答完自动收起
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) toast('该批注已作答', 'warn')
    else throw e
  }
}
function undo(qid: number) {
  /* M1 简化:本地重开输入(再次提交覆盖);平台无 undo 端点 */
  openSet.value = new Set([...openSet.value, qid])
  const q = annos.value.find((x: any) => x.id === qid)
  if (q) {
    q.status = 'pending'
    q.answer = null
  }
  toast('已重开,重新作答后提交', 'warn')
}
function fstep(d: number) {
  focusIdx.value = (focusIdx.value + d + annos.value.length) % annos.value.length
  const q = annos.value[focusIdx.value]
  if (q) locateAnno(q.id)
}
function jumpChapter(ch: string) {
  document.getElementById('ch-' + ch)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/* ── 发版 ── */
function openFinalize() {
  fin.value = { version: suggestedVer.value, note: '' }
  finErr.value = false
  showFinalize.value = true
}
async function doFinalize() {
  if (!fin.value.version.trim()) {
    finErr.value = true
    return
  }
  try {
    await finalizeDoc(route.pid, draft.value.draft_id, fin.value.version.trim(), fin.value.note)
    showFinalize.value = false
    toast(`已发版 ${fin.value.version}`)
    go(`#/p/${route.pid}/versions`)
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      finErr.value = true
      toast('版本号已存在', 'warn')
    } else throw e
  }
}
</script>

<template>
  <div class="content fixed">
    <div class="rev-toolbar">
      <span class="tag warn"><span class="dot" />{{ hasDraft ? '草案评审中' : '当前基线' }}</span>
      <span style="font-size: 0.82rem; color: var(--muted)">基于 <b>{{ baseline?.version ?? '—' }}</b> · {{ summary }}</span>
      <span class="spacer" />
      <button v-if="hasDraft" id="btnFinalize" class="btn primary sm" @click="openFinalize">定稿发版</button>
    </div>

    <div class="rev-body full">
      <div class="rev-col doc-col">
        <DocPaper v-if="payload" :payload="payload" :annos="annos" :materials="materials"
                  :title="projName" :ver-label="verLabel" :toc-mode="tocMode"
                  @activate="activateFromDoc" @jump="jumpChapter" @toc-show="tocShow" @toc-hide="tocHide">
          <template v-if="tocMode !== 'hidden'" #toc>
            <ChapterTree :chapters="payload.chapters" :annos="annos" current="" :pinned="tocPinned"
                         @jump="jumpChapter" @pin="togglePin" />
          </template>
        </DocPaper>
        <div v-else class="card" style="margin: 20px">
          <div class="empty">尚无文档:上传材料后由 agent 发起整理,或等待草案提交</div>
        </div>
      </div>

      <aside class="rev-col rail-col">
        <AnnotationRail :annos="annos" :open-set="openSet" :active-id="activeId"
                        :mode="mode" :focus-idx="focusIdx"
                        @toggle="toggle" @locate="locateAnno" @answer="answer" @undo="undo"
                        @set-mode="mode = $event" @fstep="fstep" />
      </aside>
    </div>

    <AppModal v-if="showFinalize" title="定稿发版" @close="showFinalize = false">
      <div class="field" :class="{ invalid: finErr }">
        <label>版本号 <span class="req">*</span></label>
        <input v-model="fin.version" type="text" placeholder="如 v3 或 v2.1" />
        <div class="err-msg">版本号必填,且不能与历史版本重复</div>
      </div>
      <div class="field">
        <label>发版说明</label>
        <textarea v-model="fin.note" placeholder="这一版改了什么、为什么(写入版本历史)" />
      </div>
      <p style="font-size: 0.8rem; color: var(--muted); margin-top: 8px">
        未处理批注将标记「发版时未决」,不阻塞;批准人 owner;发版后版本只增不改,可回看与回退。
      </p>
      <template #foot>
        <button class="btn" @click="showFinalize = false">再想想</button>
        <button class="btn primary" @click="doFinalize">确认发版</button>
      </template>
    </AppModal>
  </div>
</template>
