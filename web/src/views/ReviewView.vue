<!-- 文档评审页(核心):固定视口三栏独立滚动;无草案时渲染基线只读态 -->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { answerQuestion, finalizeDoc, getBaseline, getDraft, getProject, getVersions, listMaterials, listQuestions, reopenQuestion, ApiError } from '../api'
import { route, go } from '../router'
import { toast } from '../components/toast'
import AppModal from '../components/AppModal.vue'
import ChapterTree from '../components/rev/ChapterTree.vue'
import DocPaper from '../components/rev/DocPaper.vue'
import AnnotationRail from '../components/rev/AnnotationRail.vue'
import OnePager from '../components/rev/OnePager.vue'
import { GLOSSARY_CH_ID, flattenChapters } from '../utils/chapters'
import { parseOnePager, resolveOnePagerMd } from '../utils/onepager'

const projName = ref('')
// 需求状态(等谁):平台派生五态,评审页工具条徽标展示
const REQ_LABEL: Record<string, { label: string; cls: string }> = {
  idle: { label: '未开始', cls: 'mute' },
  in_review: { label: '待评审', cls: 'warn' },
  await_resubmit: { label: '待重交', cls: 'info' },
  await_finalize: { label: '待定稿', cls: 'warn' },
  finalized: { label: '已定稿', cls: 'ok' },
}
const reqStatus = ref('idle')
const draft = ref<any>(null)
const baseline = ref<any>(null)
const annos = ref<any[]>([])
const materials = ref<any[]>([])
const versions = ref<any[]>([])

/* 章节目录三态:固定(常驻挤占正文)/悬浮(鼠标移入浮现、移开隐藏)/隐藏(只留把手);固定态记忆到 localStorage */const tocPinned = ref(localStorage.getItem('quos.tocPin') === '1')
const tocHover = ref(false)
const tocMode = computed(() => (tocPinned.value ? 'pinned' : tocHover.value ? 'hover' : 'hidden') as 'pinned' | 'hover' | 'hidden')
watch(tocPinned, v => localStorage.setItem('quos.tocPin', v ? '1' : '0'))
function togglePin() {
  tocPinned.value = !tocPinned.value
  if (!tocPinned.value) tocHover.value = true // 指针还在面板上:先转悬浮,移开再隐藏
}
function tocShow() { if (!tocPinned.value) tocHover.value = true }
function tocHide() { if (!tocPinned.value) tocHover.value = false }
const openSet = ref(new Set<number>())
const activeId = ref<number | null>(null)
/* 批注栏整栏开合:收起后正文独占全宽;记忆到 localStorage(默认展开) */
const railOpen = ref(localStorage.getItem('quos.railOpen') !== '0')
watch(railOpen, v => localStorage.setItem('quos.railOpen', v ? '1' : '0'))
const pendingN = computed(() => annos.value.filter((a: any) => a.status !== 'answered').length)
const showFinalize = ref(false)
const fin = ref({ version: '', note: '' })
const finErr = ref(false)
const finErrMsg = ref('版本号必填,且不能与历史版本重复')

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
const verLabel = computed(() => (hasDraft.value ? `${baseline.value?.version ?? '首版'} · ${REQ_LABEL[reqStatus.value]?.label ?? ''}` : baseline.value?.version ?? '—'))
const summary = computed(() =>
  payload.value ? `${payload.value.chapters.filter((c: any) => c.id !== GLOSSARY_CH_ID).length} 章 · ${Object.keys(payload.value.rules).length} 条规则` : '')
const XV = /^\d+\.\d+\.\d+$/
// 建议值:基线命中 x.x.x → patch 位递增;无基线或存量旧格式 → 1.0.0
const suggestedVer = computed(() => {
  const b: string = baseline.value?.version ?? ''
  if (!XV.test(b)) return '1.0.0'
  const [a, c, d] = b.split('.').map(Number)
  return `${a}.${c}.${d + 1}`
})

async function load() {
  const p = await getProject(route.pid)
  projName.value = p.name
  reqStatus.value = p.stats.requirement_status ?? 'idle'
  materials.value = await listMaterials(route.pid)
  versions.value = await getVersions(route.pid)
  baseline.value = await getBaseline(route.pid)
  draft.value = await getDraft(route.pid)
  const all = await listQuestions(route.pid)
  annos.value = all.filter((q: any) => q.status !== 'withdrawn')
}
onMounted(load)

/* 批注分组标题注入章节号+章名(anchor 只有 chapter_id);_ord=文档顺序,供分组排序。
   双源监听:payload 与 annos 加载先后不定,任一到位都重注入。
   seg-only 锚(无/假 chapter_id)按文档顺序回填首个文本命中章:树计数/分组/chip/行内高亮随之归位 */
watch([payload, annos], ([p]) => {
  if (!p) return
  const flat = flattenChapters(p.chapters)
  const info = new Map(flat.map((f, i) => [f.c.id, { label: `${f.no} ${f.c.title}`, ord: i }]))
  const textsOf = new Map(flat.map((f) => [f.c.id, [f.c.background ?? '',
    ...(f.c.blocks ?? []).flatMap((b) => b.type === 'para' ? [b.text ?? ''] : b.type === 'exceptions' ? (b.items ?? []) : [])]]))
  for (const a of annos.value) {
    const cid = a.anchor?.chapter_id
    if (a.anchor?.seg && (!cid || !info.has(cid))) {
      const hit = flat.find((f) => (textsOf.get(f.c.id) ?? []).some((t) => t.includes(a.anchor.seg)))
      if (hit) a.anchor.chapter_id = hit.c.id
    }
    const inf = a.anchor?.chapter_id ? info.get(a.anchor.chapter_id) : undefined
    if (inf) {
      a.anchor.chapter_label = inf.label
      a.anchor._ord = inf.ord
    }
  }
})

/* ── 交互 ── */
function toggle(qid: number) {
  const s = new Set(openSet.value)
  if (s.has(qid)) s.delete(qid)
  else s.add(qid)
  openSet.value = s
}
/* 定位链:行内 mark → 规则行角标 → 章节 chip → 章首兜底;命中滚动居中并闪烁 */
async function locateAnno(qid: number) {
  activeId.value = qid
  openSet.value = new Set([...openSet.value, qid])
  await nextTick()
  const el = document.querySelector(`mark[data-a="${qid}"]`)
    ?? document.getElementById('ra-' + qid)
    ?? document.getElementById('ca-' + qid)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('hit')
    setTimeout(() => el.classList.remove('hit'), 2900)
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
async function undo(qid: number) {
  /* 重新作答=平台持久化重开(清空旧答案),刷新不回弹;重新提交仍走 answer 覆盖 */
  try {
    const updated = await reopenQuestion(qid)
    const q = annos.value.find((x: any) => x.id === qid)
    if (q) Object.assign(q, updated)
    openSet.value = new Set([...openSet.value, qid])
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) toast('该批注不可重开(仅已答可重开)', 'warn')
    else throw e
  }
}
function jumpChapter(ch: string) {
  document.getElementById('ch-' + ch)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/* 需求一页纸:有 reviewing 草案只认草案(重导不带=清空,不得回退旧基线防陈旧画像);基线态才看基线 */
const view = ref<'doc' | 'onepager'>('doc')
const onepagerMd = computed(() => resolveOnePagerMd(draft.value, baseline.value))
const onepagerDoc = computed(() =>
  view.value === 'onepager' && onepagerMd.value ? parseOnePager(onepagerMd.value) : null)
function onepagerJump(chapters: string) {
  const n = String(parseInt(chapters, 10))
  const hit = payload.value
    ? flattenChapters(payload.value.chapters).find(f => f.no === n || f.no.startsWith(n + '.'))
    : null
  if (!hit) return  // 章号不存在(skill 写错/文档改版):静默不跳
  view.value = 'doc'
  // 视图刚切回,图 iframe/表格异步渲染会再撑高布局,立即 smooth 滚会被打断——延迟到布局稳定后执行
  nextTick(() => setTimeout(() =>
    document.getElementById('ch-' + hit.c.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 250))
}

/* ── 发版 ── */
function openFinalize() {
  fin.value = { version: suggestedVer.value, note: '' }
  finErr.value = false
  showFinalize.value = true
}
async function doFinalize() {
  const v = fin.value.version.trim()
  if (!v) {
    finErrMsg.value = '版本号必填'
    finErr.value = true
    return
  }
  if (!XV.test(v)) {
    finErrMsg.value = '版本号须为 x.x.x 格式(如 1.2.0)'
    finErr.value = true
    return
  }
  try {
    await finalizeDoc(route.pid, draft.value.draft_id, v, fin.value.note)
    showFinalize.value = false
    toast(`已发版 ${v}`)
    go(`#/p/${route.pid}/versions`)
  } catch (e) {
    if (e instanceof ApiError && (e.status === 409 || e.detail?.code === 'VERSION_FORMAT')) {
      finErr.value = true
      finErrMsg.value = e.detail?.code === 'VERSION_FORMAT' ? '版本号须为 x.x.x 格式(如 1.2.0)' : '版本号与历史版本重复'
      toast(finErrMsg.value, 'warn')
    } else throw e
  }
}
</script>

<template>
  <div class="content fixed">
    <div class="rev-toolbar">
      <span class="tag" :class="hasDraft ? (REQ_LABEL[reqStatus]?.cls ?? 'warn') : 'ok'"><span class="dot" />{{ hasDraft ? (REQ_LABEL[reqStatus]?.label ?? '评审中') : '当前基线' }}</span>
      <span style="font-size: 0.82rem; color: var(--muted)">基于 <b>{{ baseline?.version ?? '—' }}</b> · {{ summary }}</span>
      <span class="spacer" />
      <button v-if="onepagerMd" class="btn sm" :class="{ primary: view === 'onepager' }"
              @click="view = view === 'onepager' ? 'doc' : 'onepager'">一页纸</button>
      <button v-if="hasDraft" id="btnFinalize" class="btn primary sm" @click="openFinalize">定稿发版</button>
    </div>

    <div class="rev-body full" :class="{ 'rail-closed': !railOpen }">
      <div class="rev-col doc-col">
        <OnePager v-if="onepagerDoc" :doc="onepagerDoc" style="padding: 18px 22px" @jump="onepagerJump" />
        <DocPaper v-else-if="payload" :payload="payload" :annos="annos" :materials="materials"
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

      <button v-if="!railOpen" class="rail-handle" type="button"
              :title="`展开批注栏(待处理 ${pendingN})`" @click="railOpen = true">
        « 批注 <span class="n">{{ pendingN }}</span>
      </button>

      <aside v-show="railOpen" class="rev-col rail-col">
        <AnnotationRail :annos="annos" :open-set="openSet" :active-id="activeId"
                        @toggle="toggle" @locate="locateAnno" @answer="answer" @undo="undo"
                        @jump="jumpChapter" @collapse="railOpen = false" />
      </aside>
    </div>

    <AppModal v-if="showFinalize" title="定稿发版" @close="showFinalize = false">
      <div class="field" :class="{ invalid: finErr }">
        <label>版本号 <span class="req">*</span></label>
        <input v-model="fin.version" type="text" placeholder="如 1.2.0" />
        <div class="err-msg">{{ finErrMsg }}</div>
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
