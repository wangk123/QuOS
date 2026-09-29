<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import {
  ApiError,
  askRule,
  confirmRule,
  extractJob,
  getRules,
  getConflicts,
  getEvidence,
  getTree,
  scaffoldTree,
  setRuleNode,
  verifyJob,
  verifyOne,
  type Rule,
  type Conflict,
  type EvidenceItem,
  type TreeNode,
} from '../api'
import { buildGroups } from '../grouping'
import { aiBusy, curName, curPath } from '../router'
import { startJobPolling } from '../jobs'

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<Rule[]>([])
const conflicts = ref<Conflict[]>([])
const evidence = ref<EvidenceItem[]>([])
const treeNodes = ref<TreeNode[]>([])
const err = ref('')
const verifyRecord = ref('') // 全量核验记录条
const expanded = ref<Record<string, boolean>>({}) // 组展开状态（key=父路径）；默认收起——长列表不整页铺开
function expandAll(v: boolean) {
  const m: Record<string, boolean> = {}
  for (const g of groups.value) m[g.key] = v
  expanded.value = m
}

const confBadge: Record<string, [string, string]> = {
  实证: ['b-green', '代码实证'],
  文档: ['b-blue', '文档'],
  推测: ['b-amber', '推测 ⚠'],
  待实证: ['b-red', 'AI待实证'],
  旧文档: ['b-gray', '旧文档'],
}
const prioBadge: Record<string, string> = { P0: 'b-red', P1: 'b-amber', P2: 'b-blue' }

async function load() {
  ;[items.value, conflicts.value, evidence.value, treeNodes.value] = await Promise.all([
    getRules(),
    getConflicts(),
    getEvidence(),
    getTree(),
  ])
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    err.value = e instanceof ApiError ? `加载失败（HTTP ${e.status}）：${e.message}` : String(e)
  }
})

// 树空拦截：手工搭骨架或 AI 从证据池归纳（生成后刷侧栏树+本视图）
const reloadTree = inject<() => Promise<void>>('reloadTree', async () => {})
const refreshClar = inject<() => Promise<void>>('refreshClar', async () => {})
const scaffolding = ref(false)
async function genScaffold() {
  scaffolding.value = true
  try {
    await scaffoldTree()
    await Promise.all([reloadTree(), load()])
    toast('骨架已生成——请在左侧检查调整后开始提取', 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `生成失败：${e.message}` : '生成失败', 'warn')
  } finally { scaffolding.value = false }
}

// 分组数据流：树 + 规则 → 模块›功能点两级分组 + 未归类（grouping.ts 纯函数）。
// 选中节点时聚焦其子树（选父节点 = 包含子节点内容）；未选中显示全部。
const curFullPath = computed(
  () => allPaths.value.find(p => p.digits === curPath.value)?.path ?? '',
)
const scopedRules = computed(() => {
  const full = curFullPath.value
  if (!full) return items.value
  return items.value.filter(a => a.node === full || (a.node ?? '').startsWith(full + '/'))
})
const grouped = computed(() => buildGroups(scopedRules.value, treeNodes.value))
const groups = computed(() => grouped.value.groups)
const unclassified = computed(() => grouped.value.unclassified)

/** 挂载候选全路径：walk 树收集；label 按层级 2 空格缩进，value 保持原始路径；digits = 树数字路径 */
const allPaths = computed(() => {
  const out: { path: string; label: string; digits: string }[] = []
  const walk = (nodes: TreeNode[], prefix: string, digits: string, depth: number) => {
    nodes.forEach((n, i) => {
      const path = prefix ? `${prefix}/${n.name}` : n.name
      const d = digits ? `${digits},${i}` : String(i)
      out.push({ path, label: `${'  '.repeat(depth)}${path}`, digits: d })
      walk(n.children, path, d, depth + 1)
    })
  }
  walk(treeNodes.value, '', '', 0)
  return out
})

/** 行内挂载/改归属：node 为空串 = 移回未归类 */
async function assign(a: Rule, node: string) {
  try {
    await setRuleNode(a.id, node)
    await load()
    toast(node ? `${a.id} → 已挂 ${node}` : `${a.id} → 已移回未归类`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `挂载失败：${e.message}` : '挂载失败', 'warn')
  }
}

const stat = {
  total: () => scopedRules.value.length,
  verified: () => scopedRules.value.filter(a => a.verified).length,
  unverified: () => scopedRules.value.filter(a => !a.verified).length,
  suspectCnt: () => scopedRules.value.filter(a => a.conf === '推测' || a.conf === '待实证').length,
}
const corrected = computed(() => items.value.filter(a => a.suspect))

function inConflict(a: Rule) {
  return conflicts.value.some(c => c.st === 'open' && (c.a === a.id || c.b === a.id))
}
function voided(a: Rule) {
  return conflicts.value.some(c => c.st === 'code' && a.id !== c.resolution && (c.a === a.id || c.b === a.id))
}

/** 提取池中材料：两阶段后台任务（逐份提取→自动核验），进度/汇总由轮询驱动，刷新不丢 */
async function extractAll() {
  try {
    const r = await extractJob()
    startJobPolling(r.job_id, async (msg, cls) => {
      toast(msg, cls)
      await load()
    })
    toast(`提取任务已创建：共 ${r.total} 份材料，提取完自动核验`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `创建提取任务失败：${e.message}` : '创建提取任务失败', 'warn')
  }
}

/** 全量核验：后台任务分批跑（进度/汇总由轮询驱动，刷新不丢）；核完由轮询 toast 汇总 */
async function checkAll() {
  try {
    const r = await verifyJob()
    startJobPolling(r.job_id, async (msg, cls) => {
      toast(msg, cls)
      await load()
      const bad = items.value.filter(a => a.suspect).length
      verifyRecord.value = `AI 逐条比对材料：${r.rules} 条全查${bad ? ` · ${bad} 条读错已修正（标黄待人工确认）` : ' · 全部一致 ✓'}`
    })
  } catch (e) {
    toast(e instanceof ApiError ? `核验失败：${e.message}` : '核验失败', 'warn')
  }
}

async function checkOne(id: string) {
  aiBusy.value = { label: `AI 单点核验 ${id}：比对材料…` }
  try {
    const r = await verifyOne(id)
    await load()
    const res = (r.results ?? []).find(x => (x as any)?.id === id) as any
    if (res?.ok) toast(`${id} 已核验：与材料一致 ✓`, 'ok')
    else if (res?.corrected_text) toast(`${id} AI 读错已修正，标黄待人工确认`, 'warn')
    else toast(`${id} 材料中无依据（推测类）：请「人工过」或「转澄清」`, 'warn')
  } catch (e) {
    toast(e instanceof ApiError ? `核验失败：${e.message}` : '核验失败', 'warn')
  } finally {
    aiBusy.value = null
  }
}

async function confirmOne(a: Rule) {
  try {
    await confirmRule(a.id)
    await load()
    toast(`${a.id} 已人工核过 ✓`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `操作失败：${e.message}` : '操作失败', 'warn')
  }
}

async function toAsk(a: Rule) {
  try {
    await askRule(a.id)
    await load()
    void refreshClar()
    toast(`${a.id} → 已进澄清池（答案确认后自动核过）`, 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? `转澄清失败：${e.message}` : '转澄清失败', 'warn')
  }
}
</script>

<template>
  <div>
    <div class="view-head">
      <h2>① 规则提取 · {{ curName }}</h2>
      <span class="sub">AI 读材料提取行为规则，逐条核验；按模块›功能点分组，组内按重要度排序。</span>
      <div class="spacer" style="flex: 1" />
      <button class="btn" type="button" @click="extractAll">提取池中相关材料</button>
      <button class="btn-accent" type="button" @click="checkAll">AI 全量核验</button>
    </div>

    <div v-if="!treeNodes.length" class="card-box scaffold-guide">
      <div class="hd">功能树还没有骨架</div>
      <div class="bd">
        规则要挂到功能点上——先搭骨架：手工在左侧添加节点，或让 AI 从证据池材料归纳。
        <div style="margin-top: 8px; display: flex; gap: 8px">
          <button class="btn-ghost" type="button" @click="toast('在左侧「＋ 根节点」开始手工搭建')">手工在左侧搭建</button>
          <button class="btn-accent" type="button" :disabled="scaffolding || !evidence.length"
            :title="!evidence.length ? '证据池为空，请先入池' : ''" @click="genScaffold">
            {{ scaffolding ? 'AI 归纳中…' : 'AI 从证据池生成' }}</button>
        </div>
      </div>
    </div>

    <p v-if="err" class="err">{{ err }}</p>
    <div class="statbar">
      <div class="stat"><b>{{ stat.total() }}</b><span>规则</span></div>
      <div class="stat okc"><b>{{ stat.verified() }}</b><span>已核验 ✓</span></div>
      <div class="stat" :class="stat.unverified() ? 'warn' : 'okc'"><b>{{ stat.unverified() }}</b><span>未核验</span></div>
      <div class="stat"><b>{{ stat.suspectCnt() }}</b><span>推测/待实证 ⚠</span></div>
    </div>


    <div v-if="groups.length" class="card-box">
      <div class="hd">
        规则表 · {{ curPath ? `${curName}（含子树）` : '全部节点' }}
        <span class="sub" style="font-weight: 400">「核」= AI 比对材料；一致核过、读错标黄修正、无依据转「人工过 / 转澄清」</span>
        <div class="spacer" style="flex: 1" />
        <button class="btn-ghost btn-sm" type="button" @click="expandAll(true)">全部展开</button>
        <button class="btn-ghost btn-sm" type="button" @click="expandAll(false)">全部收起</button>
      </div>
      <template v-for="g in groups" :key="g.key">
        <div class="grp-hd" @click="expanded[g.key] = !expanded[g.key]">
          <span class="tri" :class="{ closed: !expanded[g.key] }">▾</span>
          <b>{{ g.label }}</b>
          <span class="src">
            {{ g.nodes.reduce((s, n) => s + n.rules.length, 0) }} 条 · 核验
            {{ g.nodes.reduce((s, n) => s + n.rules.filter(r => r.verified).length, 0) }}/{{ g.nodes.reduce((s, n) => s + n.rules.length, 0) }}
          </span>
        </div>
        <template v-if="expanded[g.key]">
          <div v-for="n in g.nodes" :key="n.path" class="pt-sec">
            <div class="pt-hd">
              <span class="src">{{ n.path }}</span>
              <span v-if="n.priority" class="badge" :class="prioBadge[n.priority] ?? 'b-blue'">{{ n.priority }}</span>
              <span class="src">核验 {{ n.rules.filter(r => r.verified).length }}/{{ n.rules.length }}</span>
            </div>
            <table>
              <thead>
                <tr>
                  <th style="width: 38px">#</th><th>规则（必须能判对错）</th><th style="width: 150px">出处</th>
                  <th style="width: 88px">置信度</th><th style="width: 86px">状态</th><th style="width: 200px">核验</th>
                  <th style="width: 210px">归属</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="a in n.rules" :key="a.id" :class="{ suspect: a.suspect }">
                  <td><span class="src">{{ a.id }}</span></td>
                  <td :class="{ strike: voided(a) }">{{ a.text }}</td>
                  <td><span class="src">{{ a.src }}</span></td>
                  <td><span class="badge" :class="(confBadge[a.conf] ?? confBadge['文档'])[0]">{{ (confBadge[a.conf] ?? confBadge['文档'])[1] }}</span></td>
                  <td>
                    <span v-if="voided(a)" class="badge b-gray">已作废</span>
                    <span v-else-if="inConflict(a)" class="badge b-red">冲突</span>
                    <span v-else-if="a.clar" class="badge b-amber" :title="`问#${a.clar} 待回收答案`">已转澄清</span>
                    <span v-else-if="a.nb" class="badge b-amber" :title="a.nb">无依据</span>
                    <span v-else-if="a.suspect" class="badge b-amber">已修正·待确认</span>
                    <span v-else class="badge b-blue">在案</span>
                  </td>
                  <td>
                    <span v-if="a.verified" class="badge b-green">✓ 核过</span>
                    <template v-else>
                      <button class="btn-ghost btn-sm" type="button" title="AI 比对材料核验" @click="checkOne(a.id)">核</button>
                      <template v-if="!a.clar">
                        <button class="btn-ghost btn-sm" type="button" title="我确认这条与实际一致" @click="confirmOne(a)">人工过</button>
                        <button class="btn-ghost btn-sm" type="button" title="进澄清池，答案确认后自动核过" @click="toAsk(a)">转澄清</button>
                      </template>
                      <span v-else class="src">问#{{ a.clar }}</span>
                    </template>
                  </td>
                  <td>
                    <select class="node-sel" :value="a.node || ''" @change="assign(a, ($event.target as HTMLSelectElement).value)">
                      <option value="">（选功能点挂载）</option>
                      <option v-for="p in allPaths" :key="p.path" :value="p.path">{{ p.label }}</option>
                    </select>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>
    </div>
    <div v-else-if="!items.length" class="card-box">
      <div class="bd" style="color: var(--muted-fg); padding: 24px; text-align: center">还没有规则——点「提取池中相关材料」</div>
    </div>

    <div class="card-box unclass-box">
      <div class="hd">未归类 · {{ unclassified.length }} 条
        <span class="sub" style="font-weight: 400">树缺枝的探伤器——左侧补节点后行内选归属；旧数据无归属时，到证据池「重新提取」可自动挂载</span></div>
      <table v-if="unclassified.length">
        <thead>
          <tr>
            <th style="width: 38px">#</th><th>规则（必须能判对错）</th><th style="width: 150px">出处</th>
            <th style="width: 88px">置信度</th><th style="width: 86px">状态</th><th style="width: 200px">核验</th>
            <th style="width: 210px">归属</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in unclassified" :key="a.id" :class="{ suspect: a.suspect }">
            <td><span class="src">{{ a.id }}</span></td>
            <td :class="{ strike: voided(a) }">{{ a.text }}</td>
            <td><span class="src">{{ a.src }}</span></td>
            <td><span class="badge" :class="(confBadge[a.conf] ?? confBadge['文档'])[0]">{{ (confBadge[a.conf] ?? confBadge['文档'])[1] }}</span></td>
            <td>
              <span v-if="voided(a)" class="badge b-gray">已作废</span>
              <span v-else-if="inConflict(a)" class="badge b-red">冲突</span>
              <span v-else-if="a.clar" class="badge b-amber" :title="`问#${a.clar} 待回收答案`">已转澄清</span>
              <span v-else-if="a.nb" class="badge b-amber" :title="a.nb">无依据</span>
              <span v-else-if="a.suspect" class="badge b-amber">已修正·待确认</span>
              <span v-else class="badge b-blue">在案</span>
            </td>
            <td>
              <span v-if="a.verified" class="badge b-green">✓ 核过</span>
              <template v-else>
                <button class="btn-ghost btn-sm" type="button" title="AI 比对材料核验" @click="checkOne(a.id)">核</button>
                <template v-if="!a.clar">
                  <button class="btn-ghost btn-sm" type="button" title="我确认这条与实际一致" @click="confirmOne(a)">人工过</button>
                  <button class="btn-ghost btn-sm" type="button" title="进澄清池，答案确认后自动核过" @click="toAsk(a)">转澄清</button>
                </template>
                <span v-else class="src">问#{{ a.clar }}</span>
              </template>
            </td>
            <td>
              <select class="node-sel" :value="a.node || ''" @change="assign(a, ($event.target as HTMLSelectElement).value)">
                <option value="">（选功能点挂载）</option>
                <option v-for="p in allPaths" :key="p.path" :value="p.path">{{ p.label }}</option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="verifyRecord" class="card-box">
      <div class="hd">全量核验记录</div>
      <div class="bd" style="font-size: 12.5px">
        <span class="badge b-green">{{ verifyRecord }}</span>
        <span v-if="corrected.length" style="color: var(--muted-fg); margin-left: 10px">可疑项标黄置顶待人工确认：{{ corrected.map(a => a.id).join('、') }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.err { font-size: 12px; color: var(--destructive); background: var(--red-bg); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
.grp-hd { display: flex; align-items: center; gap: 8px; padding: 8px 16px; background: var(--muted); border-bottom: 1px solid var(--border); font-size: 12.5px; cursor: pointer; user-select: none; }
.grp-hd .tri { display: inline-block; font-size: 10px; color: var(--muted-fg); transition: transform 0.15s; }
.grp-hd .tri.closed { transform: rotate(-90deg); }
.pt-hd { display: flex; align-items: center; gap: 8px; padding: 8px 16px 0; flex-wrap: wrap; }
.pt-sec table { margin-top: 2px; }
.node-sel { font-size: 11.5px; font-family: var(--mono); padding: 3px 6px; border: 1px solid var(--border2); border-radius: 5px; background: #fff; max-width: 200px; }
</style>
