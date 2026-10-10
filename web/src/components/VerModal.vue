<script setup lang="ts">
// 版本弹窗：时间线 / 新增版本表单 / 回滚废弃确认 / 预览 markdown 渲染模式。
// 版本 = git tag（手动 x.x.x）；「当前」徽章按 cur 字段（HEAD 所指），非列表末位。
import { computed, inject, nextTick, ref, watch } from 'vue'
import { ApiError, createBaseline, deprecateBaseline, getDoc, listBaselines, restoreBaseline, type Baseline } from '../api'
import { renderMd } from '../utils/md'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  close: []
  /** 新增版本成功——父级重拉基线 */
  saved: []
  /** 回滚完成——父级刷新详情（工作区内容已变） */
  restored: []
}>()

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<Baseline[]>([])
const err = ref('')
const saving = ref(false)
const docOpen = ref(false)
const docText = ref('')
const docMode = ref<'md' | 'src'>('md')

// 新增版本表单
const formOpen = ref(false)
const ver = ref('')
const note = ref('')

// 回滚 / 废弃确认
const confirmBox = ref<null | { kind: 'restore' | 'deprecate'; b: Baseline }>(null)

// 预览章节导航：渲染后从 DOM 提取 h2-h4（h1 为文档唯一标题不入导航）
const mdViewEl = ref<HTMLElement | null>(null)
const docNav = ref<{ level: number; text: string; el: HTMLElement }[]>([])
const activeNav = ref(-1)

function scanNav() {
  docNav.value = mdViewEl.value
    ? [...mdViewEl.value.querySelectorAll('h2,h3,h4')]
        .map(h => ({ level: +h.tagName[1], text: h.textContent?.trim() ?? '', el: h as HTMLElement }))
    : []
  activeNav.value = docNav.value.length ? 0 : -1
}

function jumpNav(i: number) {
  docNav.value[i]?.el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function onDocScroll(e: Event) {  // 当前章节高亮：滚动位置上方最近的标题
  const top = (e.target as HTMLElement).scrollTop + 60
  let cur = -1
  docNav.value.forEach((n, i) => { if (n.el.offsetTop <= top) cur = i })
  if (cur >= 0) activeNav.value = cur
}

const VER_RE = /^\d+\.\d+\.\d+$/
const isNewTag = (t: string) => /^v\d+\.\d+\.\d+$/.test(t)
const num = (s: string) => s.split('.').map(Number) as [number, number, number]
const toKey = (n: [number, number, number]) => n[0] * 1e6 + n[1] * 1e3 + n[2]

/** 前端预校验（与后端三规则同口径）：格式 / 重复 / 不低于已有最大新格式版本 */
const verErr = computed(() => {
  const v = ver.value.trim()
  if (!v) return ''
  if (!VER_RE.test(v)) return '格式须为 x.y.z 三段数字，如 1.2.2'
  if (items.value.some(b => b.tag === `v${v}`)) return `${v} 已存在——版本号不可与已有版本重复`
  const news = items.value.filter(b => isNewTag(b.tag)).map(b => num(b.tag.slice(1)))
  if (news.length && toKey(num(v)) <= Math.max(...news.map(toKey))) {
    const mx = news.map(toKey).indexOf(Math.max(...news.map(toKey)))
    return `不可低于已有最大版本 ${news[mx].join('.')}`
  }
  return ''
})

const maxNewHint = computed(() => {
  const news = items.value.filter(b => isNewTag(b.tag)).map(b => b.tag.slice(1))
  if (!news.length) return ''
  const best = news.reduce((a, v) => (toKey(num(v)) > toKey(num(a)) ? v : a))
  return `；当前最大 ${best}`
})

/** 最后一个 cur 行（HEAD 所指；同 commit 多 tag 时仅此行挂「当前」徽章） */
const lastCur = computed(() => {
  let r = -1
  items.value.forEach((b, i) => { if (b.cur) r = i })
  return r
})

const fmtTime = (t?: number) =>
  t ? new Date(t * 1000).toLocaleString('sv-SE', { hour12: false }).slice(0, 16) : ''
const vmeta = (b: Baseline) =>
  [fmtTime(b.time), b.commit && b.commit.slice(0, 7)].filter(Boolean).join(' · ')
const dispVer = (b: Baseline) => isNewTag(b.tag) ? b.tag.slice(1) : b.tag

async function load() {
  items.value = await listBaselines()
}

watch(
  () => props.open,
  v => {
    if (!v) return
    err.value = ''
    formOpen.value = false
    confirmBox.value = null
    load().catch(e => {
      err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
    })
  },
  { immediate: true },
)

function openForm() {
  ver.value = ''
  note.value = ''
  formOpen.value = true
}

async function save() {
  if (saving.value || !VER_RE.test(ver.value.trim()) || verErr.value) return
  saving.value = true
  try {
    const r = await createBaseline(ver.value.trim(), note.value.trim() || '基线存档')
    toast(`已新增版本 ${r.tag}`, 'ok')
    emit('saved')
    formOpen.value = false
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? `新增失败：${e.message}` : '新增失败', 'warn')
  } finally {
    saving.value = false
  }
}

async function doConfirm() {
  if (!confirmBox.value) return
  const { kind, b } = confirmBox.value
  try {
    if (kind === 'restore') {
      await restoreBaseline(b.tag)
      emit('restored')
      toast(`已回滚到 ${b.tag}——之后的编辑从该版继续`, 'ok')
    } else {
      await deprecateBaseline(b.tag)
      toast(`已废弃 ${b.tag}`, 'ok')
    }
    confirmBox.value = null
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? `操作失败：${e.message}` : '操作失败', 'warn')
  }
}

async function preview() {
  try {
    docText.value = await getDoc()
    docMode.value = 'md'
    docOpen.value = true
    await nextTick()
    scanNav()  // v-html 渲染落 DOM 后提取标题
  } catch (e) {
    toast(e instanceof ApiError ? `导出失败：${e.message}` : '导出失败', 'warn')
  }
}

function download() {
  const url = URL.createObjectURL(new Blob([docText.value], { type: 'text/markdown' }))
  const a = document.createElement('a')
  a.href = url
  a.download = '需求文档.md'
  a.click()
  URL.revokeObjectURL(url)
  toast('已下载 需求文档.md', 'ok')
}
</script>

<template>
  <div class="mask" :class="{ open }" @click.self="$emit('close')">
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>版本</h3>
        <div class="msub">需求文档的存档历史——可回看、可回滚，随时存一版留底</div>
        <button class="x" type="button" aria-label="关闭" @click="$emit('close')">✕</button>
      </div>
      <div class="modal-body">
        <p v-if="err" class="err">{{ err }}</p>
        <div v-if="items.length" class="vtl">
          <div v-for="(b, i) in items" :key="b.tag" class="vitem" :class="{ cur: b.cur, legacy: !isNewTag(b.tag) }">
            <h4><span class="vno">{{ dispVer(b) }}</span>
              <span v-if="b.cur && i === lastCur" class="badge b-green">当前</span>
              <span v-if="!isNewTag(b.tag)" class="badge b-gray">旧格式</span>
              <span class="vacts">
                <button v-if="!b.cur" class="vact" type="button" @click="confirmBox = { kind: 'restore', b }">↩ 回滚到此版</button>
                <button class="vact depr" type="button" @click="confirmBox = { kind: 'deprecate', b }">✕ 废弃</button>
              </span>
            </h4>
            <div class="vmeta">{{ vmeta(b) }}</div>
            <div v-if="b.note" class="vnote">{{ b.note }}</div>
          </div>
        </div>
        <div v-else class="v-empty">还没有版本——需要留底时点新增版本</div>
      </div>
      <div class="modal-foot">
        <span class="fnote">说明为纯文本，不渲染 markdown</span>
        <span class="spacer"></span>
        <button class="btn" type="button" @click="openForm">新增版本</button>
        <button class="btn-ghost" type="button" @click="preview">预览 / 导出需求文档</button>
      </div>
    </div>
  </div>

  <!-- 新增版本表单 -->
  <div v-if="formOpen" class="mask open" @click.self="formOpen = false">
    <div class="modal ver-form" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>新增版本</h3>
        <div class="msub">留一版可回滚的存档点——版本号与说明会显示在时间线</div>
        <button class="x" type="button" aria-label="关闭表单" @click="formOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <label for="ver-no">版本号</label>
        <input id="ver-no" v-model="ver" type="text" placeholder="1.2.2" autocomplete="off"
               :class="{ 'err-in': verErr }">
        <div v-if="verErr" class="ferr">{{ verErr }}</div>
        <div v-else class="fhint">格式 x.y.z（三段数字）{{ maxNewHint }}</div>
        <label for="ver-note">版本说明（可空）</label>
        <textarea id="ver-note" v-model="note" placeholder="留底原因 / 本版要点，纯文本"></textarea>
      </div>
      <div class="modal-foot">
        <span class="fnote">无变更也可存版（tag 指向当前 commit）</span>
        <span class="spacer"></span>
        <button class="btn-ghost" type="button" @click="formOpen = false">取消</button>
        <button class="btn" type="button" data-testid="commit-ver" :disabled="saving || !!verErr || !ver.trim()"
                @click="save">{{ saving ? '存档中…' : '新增版本' }}</button>
      </div>
    </div>
  </div>

  <!-- 回滚 / 废弃确认 -->
  <div v-if="confirmBox" class="mask open" @click.self="confirmBox = null">
    <div class="modal confirm-modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>{{ confirmBox.kind === 'restore' ? `回滚到 ${dispVer(confirmBox.b)}` : `废弃版本 ${dispVer(confirmBox.b)}` }}</h3>
        <div class="msub">{{ confirmBox.kind === 'restore' ? '工作区将完整恢复为该版本内容' : '该版本将从时间线移除' }}</div>
        <button class="x" type="button" aria-label="关闭确认" @click="confirmBox = null">✕</button>
      </div>
      <div class="confirm-body">
        <div class="confirm-icon" :class="confirmBox.kind">
          {{ confirmBox.kind === 'restore' ? '↩' : '✕' }}
        </div>
        <div v-if="confirmBox.kind === 'restore'" class="ctext">
          回滚后「当前」指针移动到 <b>{{ dispVer(confirmBox.b) }}</b>，之后的编辑从该点继续。
          <div class="warn-line">当前未存版的修改将被丢弃，且不可恢复。</div>
          <div class="keep-line">已存版本不受影响，仍留在时间线。</div>
        </div>
        <div v-else class="ctext">
          废弃后 <b>{{ dispVer(confirmBox.b) }}</b> 从时间线彻底消失，无法再回滚或查看。
          <div class="keep-line">存档数据仍保留在 git 历史中，可手动找回。</div>
        </div>
      </div>
      <div class="modal-foot">
        <span class="spacer"></span>
        <button class="btn-ghost" type="button" @click="confirmBox = null">取消</button>
        <button class="btn-danger" type="button" @click="doConfirm">
          {{ confirmBox.kind === 'restore' ? '确认回滚' : '确认废弃' }}
        </button>
      </div>
    </div>
  </div>

  <!-- 导出预览：渲染 / 源码双模式 + 右侧章节导航 -->
  <div v-if="docOpen" class="mask open" @click.self="docOpen = false">
    <div class="modal doc-preview" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>需求文档 · 导出预览</h3>
        <div class="msub">总览开篇 + 按树分层——整份需求一份文档，给评审/开发直接看</div>
        <div class="mode-switch">
          <button :class="{ on: docMode === 'md' }" type="button" @click="docMode = 'md'">渲染</button>
          <button :class="{ on: docMode === 'src' }" type="button" @click="docMode = 'src'">源码</button>
        </div>
        <button class="x" type="button" aria-label="关闭预览" @click="docOpen = false">✕</button>
      </div>
      <div class="modal-body doc-body" @scroll.passive="docMode === 'md' && onDocScroll($event)">
        <div class="doc-main">
          <!-- eslint-disable-next-line vue/no-v-html —— 内容经 renderMd 全量 escape -->
          <div v-if="docMode === 'md'" ref="mdViewEl" class="md-view" v-html="renderMd(docText)"></div>
          <pre v-else class="doc-outline">{{ docText }}</pre>
        </div>
        <nav v-if="docMode === 'md' && docNav.length" class="doc-nav" aria-label="章节导航">
          <div v-for="(n, i) in docNav" :key="i" class="nav-item"
               :class="[`lv${n.level}`, { on: i === activeNav }]" @click="jumpNav(i)">{{ n.text }}</div>
        </nav>
      </div>
      <div class="modal-foot">
        <span class="fnote">下载始终为 .md 源码</span>
        <span class="spacer"></span>
        <button class="btn" type="button" @click="download">下载 .md</button>
        <button class="btn-ghost" type="button" @click="docOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
