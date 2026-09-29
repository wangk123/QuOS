<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import {
  ApiError,
  createBaseline,
  getRules,
  getClarifications,
  getDoc,
  getTree,
  listBaselines,
  listProfiles,
  type Baseline,
  type TreeNode,
} from '../api'
import { baseTag } from '../router'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

// 定稿 = 项目级：整份结果文档 git commit + tag（与左侧选中节点无关；节点级重生成在 ③ 生成画像页）
const profNodes = ref<string[]>([])
const leafCnt = ref(0)
const ruleCnt = ref(0)
const waitCnt = ref(0)
const baselines = ref<Baseline[]>([])
const err = ref('')
const showDoc = ref(false)
const docText = ref('')
const saving = ref(false)

function countLeaves(nodes: TreeNode[]): number {
  return nodes.reduce((n, x) => n + (x.children.length ? countLeaves(x.children) : 1), 0)
}

async function load() {
  const [rules, clars, bls, tree, profs] = await Promise.all([
    getRules(),
    getClarifications(),
    listBaselines(),
    getTree(),
    listProfiles(),
  ])
  ruleCnt.value = rules.length
  waitCnt.value = clars.filter(c => c.st === 'wait').length
  baselines.value = bls
  leafCnt.value = countLeaves(tree)
  profNodes.value = profs
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
  }
})

const profCnt = computed(() => profNodes.value.length)
const canSave = computed(() => profCnt.value > 0)

async function newBaseline() {
  saving.value = true
  try {
    const b = await createBaseline(`定稿存档 · ${profCnt.value} 份画像 · ${ruleCnt.value} 条规则`)
    baseTag.value = `基线 ${b.tag} · ${b.commit.slice(0, 7)}`
    await load()
    toast(`已并入基线 ${b.tag}（commit+tag）`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `存档失败：${e.message}` : '存档失败', 'warn')
  } finally {
    saving.value = false
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
      <h2>⑤ 定稿存档</h2>
      <span class="sub">整份结果文档存入项目基线（git commit + tag）。</span>
    </div>

    <p v-if="err" class="err">{{ err }}</p>

    <div class="save2">
      <div class="col-main">
        <div class="statbar">
          <div class="stat" :class="{ okc: leafCnt > 0 && profCnt >= leafCnt }">
            <b>{{ profCnt }}/{{ leafCnt }}</b><span>画像已生成 / 功能点</span>
          </div>
          <div class="stat"><b>{{ ruleCnt }}</b><span>规则总数</span></div>
          <div class="stat" :class="waitCnt ? 'warn' : 'okc'">
            <b>{{ waitCnt }}</b><span>待确认（澄清池）</span>
          </div>
        </div>

        <div class="card-box cta">
          <div class="hd">并入基线 <span class="hd-sub">· 项目级</span></div>
          <div class="bd">
            <div class="cta-note">
              将整份结果文档（{{ profCnt }} 份画像 + {{ ruleCnt }} 条规则 + 澄清档案）固化为
              <span class="mono">git commit + tag</span>，之后新需求 diff 可定位增量。
            </div>
            <div v-if="!canSave" class="warn-strip cta-warn">
              <b>还没有任何画像</b>
              先回 ③ 生成画像——空文档没有存档意义（规则与证据会随档案一并入库）。
            </div>
            <div v-else-if="waitCnt" class="warn-strip cta-warn">
              <b>还有 {{ waitCnt }} 项待确认</b>
              建议先在顶栏澄清池收口，否则带「?」进基线。
            </div>
            <div class="cta-actions">
              <button class="btn btn-lg" type="button" :disabled="!canSave || saving" @click="newBaseline">
                {{ saving ? '存档中…' : '✔ 并入基线（commit + tag）' }}</button>
              <button class="btn-ghost" type="button" @click="openDoc">预览结果文档</button>
            </div>
          </div>
        </div>
      </div>

      <div class="col-side">
        <div class="card-box">
          <div class="hd">版本时间线</div>
          <div class="bd">
            <div v-if="baselines.length" class="tl">
              <div v-for="(b, i) in baselines" :key="b.tag" class="tl-item" :class="{ cur: i === baselines.length - 1 }">
                <h4>{{ b.tag }} <span v-if="i === baselines.length - 1" class="badge b-blue">当前</span></h4>
                <div class="meta">{{ b.commit }}</div>
              </div>
            </div>
            <div v-else style="color: var(--muted-fg)">还没有基线——定稿存档后出现</div>
          </div>
        </div>

        <div class="card-box">
          <div class="hd">本次将存档</div>
          <div class="bd">
            <div class="arc-row"><span>用户画像</span><b>{{ profCnt }} 份</b></div>
            <div class="arc-row"><span>规则</span><b>{{ ruleCnt }} 条</b></div>
            <div class="arc-row"><span>结果文档</span><b>结构化需求规格.md</b></div>
            <div class="arc-row"><span>澄清池关联记录</span><b>随档案写入</b></div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showDoc" class="modal-bg" @click.self="showDoc = false">
      <div class="modal wide" role="dialog" aria-modal="true">
        <h3>最终结果文档 · 结构化需求规格（自动生成）</h3>
        <div class="q-export" style="max-height: 52vh; overflow: auto">{{ docText }}</div>
        <div class="foot">
          <button class="btn-ghost" type="button" @click="showDoc = false">关闭</button>
          <button class="btn" type="button" @click="downloadDoc">下载 .md</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
.save2 { display: grid; grid-template-columns: minmax(0, 1.7fr) 300px; gap: 14px; align-items: start; }
.hd-sub { font-weight: 400; color: var(--muted-fg); font-size: 12px; }
.cta { border-color: var(--secondary); }
.cta .bd { display: flex; flex-direction: column; gap: 10px; }
.cta-note { font-size: 12.5px; color: var(--muted-fg); }
.cta-note .mono { font-family: var(--mono); font-size: 11.5px; color: var(--fg); }
.cta-warn { margin: 0; }
.cta-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.btn-lg { padding: 10px 22px; font-size: 13.5px; }
.col-side .card-box { margin-bottom: 14px; }
.col-side .card-box:last-child { margin-bottom: 0; }
.arc-row { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; padding: 7px 0; border-bottom: 1px dashed var(--border); font-size: 12.5px; }
.arc-row:last-child { border-bottom: none; }
.arc-row span { color: var(--muted-fg); }
.arc-row b { font-weight: 600; text-align: right; }
@media (max-width: 960px) { .save2 { grid-template-columns: 1fr; } }
</style>
