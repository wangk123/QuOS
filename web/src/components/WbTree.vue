<script setup lang="ts">
// Task 7 工作台左主区语义树：根卡片（__root__）→ 模块卡（可折叠）→ 叶行。
// 数据源 wb（T5 聚合 /wb/summary 平铺行）；徽章直接用行数据 pend/conf（后端已含冲突，勿再 deriveBadge 双计）。
// 行内编辑：✎/＋ 走 treeOp（数字 path），goal 点击编辑走 PATCH /profiles/{path}（数字路径——full 含 / 路由不匹配）。
import { computed, inject, ref } from 'vue'
import { patchProfileGoal, treeOp, type WbNodeRow } from '../api'
import { refreshWb, wb } from '../wb'

const props = defineProps<{ selected: string }>()
const emit = defineEmits<{ pick: [full: string]; 'edit-root': []; 'refresh-root': [] }>()
const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

/** 顶层行（path 单段）+ 其全部后代平铺（depth=模块内相对层级）；后端按树序平铺，单趟分组即可 */
interface FlatRow { r: WbNodeRow; depth: number }
const mods = computed<{ row: WbNodeRow; rows: FlatRow[] }[]>(() => {
  const out: { row: WbNodeRow; rows: FlatRow[] }[] = []
  let cur: { row: WbNodeRow; rows: FlatRow[] } | null = null
  for (const r of wb.value?.tree ?? []) {
    const d = r.path.split(',').length - 1
    if (d === 0) {
      cur = { row: r, rows: [] }
      out.push(cur)
    } else if (cur) {
      cur.rows.push({ r, depth: d - 1 })
    }
  }
  return out
})

/** 根卡片统计徽章：只对顶层行求和——模块行是子树聚合值，再叠叶行会双计；顶层互不重叠且覆盖全树 */
const stat = computed(() => {
  const t = wb.value?.tree ?? []
  const top = mods.value.map(m => m.row)
  return {
    rules: top.reduce((s, r) => s + r.rules, 0),
    unverified: top.reduce((s, r) => s + r.unverified, 0),
    conf: top.reduce((s, r) => s + r.conf, 0),
    gaps: top.reduce((s, r) => s + r.gaps, 0),
    done: t.filter(r => r.state === 'done').length,
    doing: t.some(r => r.state === 'doing'),
    total: t.length,
  }
})

/** 徽章工作清单（四原子规范，模块行=子树聚合）：
 * doing 蓝=处理中 / unverified 灰「n 待核」/ conf 红「⚠n」冲突 / gaps 琥珀「△n」缺口 / cnt 灰「n 条」/ profiled 绿 ✓ */
function badges(r: WbNodeRow): { cls: string; text: string; title: string }[] {
  const b: { cls: string; text: string; title: string }[] = []
  if (r.state === 'doing') b.push({ cls: 'doing', text: '处理中', title: '后台正在完善该节点' })
  if (r.unverified > 0) b.push({ cls: 'unv', text: `${r.unverified} 待核`, title: `${r.unverified} 条未核验，条目 tab 行内核验` })
  if (r.conf > 0) b.push({ cls: 'conf', text: `⚠${r.conf}`, title: `${r.conf} 处条目冲突待裁决（存疑 tab）` })
  if (r.gaps > 0) b.push({ cls: 'doubt', text: `△${r.gaps}`, title: `${r.gaps} 条材料缺口待澄清（存疑 tab，含子树）` })
  if (r.rules > 0) b.push({ cls: 'cnt', text: `${r.rules} 条`, title: `${r.rules} 条行为条目（含子树）` })
  if (r.profiled && r.unverified === 0) b.push({ cls: 'okc', text: '✓', title: '画像就绪，无待核' })
  return b
}

/** 折叠态（默认全展开）；按数字 path 记忆 */
const closed = ref(new Set<string>())
function toggle(path: string) {
  const next = new Set(closed.value)
  next.has(path) ? next.delete(path) : next.add(path)
  closed.value = next
}

// ── 编辑弹窗：add=加节点（parent 空=顶层模块）/ edit=改名+概要；path 均为数字路径 ──
const MAX_DEPTH = 5
const canAdd = (r: WbNodeRow) => r.path.split(',').length < MAX_DEPTH

const dlg = ref<null | { mode: 'add' | 'edit'; parent: WbNodeRow | null; row: WbNodeRow | null; name: string; goal: string }>(null)
function openAdd(parent: WbNodeRow | null) {
  dlg.value = { mode: 'add', parent, row: null, name: '', goal: '' }
}
function openEdit(row: WbNodeRow) {
  dlg.value = { mode: 'edit', parent: null, row, name: row.name, goal: row.goal }
}

/** 新节点数字路径 = 父节点现有直接子数（顶层则顶层节点数）——add 后按此寻址补概要 */
function childPath(parent: WbNodeRow | null): string {
  const rows = wb.value?.tree ?? []
  const n = parent
    ? rows.filter(r => r.path.startsWith(parent.path + ',')
      && r.path.split(',').length === parent.path.split(',').length + 1).length
    : rows.filter(r => !r.path.includes(',')).length
  return parent ? `${parent.path},${n}` : `${n}`
}

async function saveDlg() {
  const d = dlg.value
  if (!d || !d.name.trim()) return
  try {
    if (d.mode === 'add') {
      await treeOp('add', d.parent?.path, d.name.trim())
      if (d.goal.trim()) await patchProfileGoal(childPath(d.parent), d.goal.trim())
    } else if (d.row) {
      if (d.name.trim() !== d.row.name) await treeOp('rename', d.row.path, d.name.trim())
      if (d.goal !== d.row.goal) await patchProfileGoal(d.row.path, d.goal)
    }
    dlg.value = null
    await refreshWb()
  } catch (e) {
    toast(`保存失败：${e instanceof Error ? e.message : e}`)
  }
}

// ── 删除确认弹窗（应用内，替代原生 confirm——与编辑弹窗同族，危险操作红色调） ──
const del = ref<null | { row: WbNodeRow; kids: number; rules: number }>(null)

function onDelete(row: WbNodeRow) {
  const rows = wb.value?.tree ?? []
  del.value = {
    row,
    kids: rows.filter(r => r.path.startsWith(row.path + ',')).length,
    rules: rows.find(r => r.path === row.path)?.rules ?? 0,
  }
}

async function confirmDel() {
  const d = del.value
  if (!d) return
  try {
    await treeOp('del', d.row.path)
    // 选中行落在被删子树内 → 回根详情，防右栏悬空
    if (props.selected === d.row.full || props.selected.startsWith(d.row.full + '/')) emit('pick', '__root__')
    del.value = null
    await refreshWb()
  } catch (e) {
    toast(`删除失败：${e instanceof Error ? e.message : e}`)
  }
}
</script>

<template>
  <div v-if="wb" class="wbtree">
    <div class="rootcard" :class="{ sel: selected === '__root__' }" @click="emit('pick', '__root__')">
      <h2>◉ 需求总览</h2>
      <p>{{ wb.root?.goal || '根画像未生成——生成需求后由 AI 汇总，也可点右上 ✎ 手工补一句' }}</p>
      <div class="rmeta">
        <span v-if="stat.doing" class="badge">正在完善 {{ stat.done }}/{{ stat.total }}</span>
        <template v-else-if="stat.total">
          <span class="badge">{{ stat.rules }} 条目</span>
          <span v-if="stat.unverified" class="badge">{{ stat.unverified }} 待核</span>
          <span v-if="stat.conf" class="badge hot">⚠{{ stat.conf }}</span>
          <span v-if="stat.gaps" class="badge warm">△{{ stat.gaps }}</span>
          <span v-else class="badge">判断清零 ✓</span>
        </template>
        <span v-else class="badge">大纲就绪</span>
      </div>
      <div class="corner">
        <button class="refresh" type="button" @click.stop="emit('refresh-root')">↻ 摘要</button>
        <button class="edit" type="button" @click.stop="emit('edit-root')">✎</button>
      </div>
    </div>

    <div class="tree">
      <div class="mods">
        <template v-for="m in mods" :key="m.row.path">
          <!-- 顶层模块：卡+折叠叶区 -->
          <div v-if="m.rows.length" class="mod" :class="{ open: !closed.has(m.row.path) }">
            <div class="modcard">
              <div class="modhead" @click="toggle(m.row.path)">
                <span class="chev" />
                <span class="mname">{{ m.row.name }}</span>
                <span class="mdesc">{{ m.row.goal }}</span>
                <span class="mb">
                  <span v-for="b in badges(m.row)" :key="b.cls + b.text" class="nbadge" :class="b.cls">{{ b.text }}</span>
                  <span class="editops">
                    <button title="编辑（名称/概要）" type="button" @click.stop="openEdit(m.row)">✎</button>
                    <button v-if="canAdd(m.row)" title="加子节点" type="button" @click.stop="openAdd(m.row)">＋</button>
                    <button title="删除节点" type="button" @click.stop="onDelete(m.row)">✕</button>
                  </span>
                </span>
              </div>
              <div class="leaves">
                <div
                  v-for="f in m.rows"
                  :key="f.r.path"
                  class="leaf"
                  :class="{ sel: selected === f.r.full }"
                  :style="{ marginLeft: `${f.depth * 14}px` }"
                  @click="emit('pick', f.r.full)"
                >
                  <span class="lname">{{ f.r.name }}</span>
                  <span v-if="f.r.goal" class="ldesc">{{ f.r.goal }}</span>
                  <span class="lb">
                    <span v-for="b in badges(f.r)" :key="b.cls + b.text" class="nbadge" :class="b.cls">{{ b.text }}</span>
                    <span class="editops">
                      <button title="编辑（名称/概要）" type="button" @click.stop="openEdit(f.r)">✎</button>
                      <button v-if="canAdd(f.r)" title="加子节点" type="button" @click.stop="openAdd(f.r)">＋</button>
                      <button title="删除节点" type="button" @click.stop="onDelete(f.r)">✕</button>
                    </span>
                  </span>
                </div>
              </div>
            </div>
          </div>
          <!-- 顶层叶（无子）不套卡，直接一行 -->
          <div
            v-else
            class="leaf top-leaf"
            :class="{ sel: selected === m.row.full }"
            @click="emit('pick', m.row.full)"
          >
            <span class="lname">{{ m.row.name }}</span>
            <span v-if="m.row.goal" class="ldesc">{{ m.row.goal }}</span>
            <span class="lb">
              <span v-for="b in badges(m.row)" :key="b.cls + b.text" class="nbadge" :class="b.cls">{{ b.text }}</span>
              <span class="editops">
                <button title="编辑（名称/概要）" type="button" @click.stop="openEdit(m.row)">✎</button>
                <button v-if="canAdd(m.row)" title="加子节点" type="button" @click.stop="openAdd(m.row)">＋</button>
                <button title="删除节点" type="button" @click.stop="onDelete(m.row)">✕</button>
              </span>
            </span>
          </div>
        </template>
      </div>
      <button class="add-root" type="button" @click="openAdd(null)">＋ 加模块</button>
    </div>
    <p class="hint">这棵树就是需求文档本身——hover 行内 ✎ 编辑（名称+概要）、＋ 加子（最深 5 级）、✕ 删除（概要编辑也走 ✎）。</p>

    <!-- 编辑弹窗：加节点（可带概要）/ 改名+概要。
      Teleport 到 body：左栏 .treezone 是 sticky（恒建层叠上下文），mask 的 fixed+z-index 被困在
      左栏上下文里压不过右栏 .detailzone——遮罩盖不住右侧；送出后与 App 顶层弹窗同层级 -->
    <Teleport to="body">
      <div v-if="dlg" class="mask open" @click.self="dlg = null">
      <div class="modal tdlg" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h3>{{ dlg.mode === 'add' ? (dlg.parent ? `加子节点 · ${dlg.parent.name}` : '加顶层模块') : `编辑 · ${dlg.row?.name}` }}</h3>
          <button class="x" type="button" aria-label="关闭" @click="dlg = null">✕</button>
        </div>
        <div class="modal-body">
          <label>名称</label>
          <input v-model="dlg.name" type="text" data-test="dlg-name" placeholder="名词短语，2-8 字" @keyup.enter="saveDlg" />
          <label>概要（这个节点要达成什么，一句话，可后补）</label>
          <textarea v-model="dlg.goal" data-test="dlg-goal" rows="2" placeholder="例：验证用户输入企业名称后系统自动开网页" />
        </div>
        <div class="modal-foot">
          <span class="fnote">{{ dlg.mode === 'add' ? '名称必填；概要留空可稍后在行内 ✎ 补' : '名称与概要可同时改' }}</span>
          <button class="btn" type="button" data-test="dlg-save" :disabled="!dlg.name.trim()" @click="saveDlg">保存</button>
        </div>
      </div>
      </div>
    </Teleport>

    <!-- 删除确认弹窗：应用内样式（替代原生 confirm），危险操作红色调；Teleport 同上 -->
    <Teleport to="body">
      <div v-if="del" class="mask open" @click.self="del = null">
      <div class="modal deldlg" role="alertdialog" aria-modal="true">
        <div class="modal-head">
          <h3>删除节点</h3>
          <button class="x" type="button" aria-label="关闭" @click="del = null">✕</button>
        </div>
        <div class="modal-body">
          <p class="del-q">确定删除 <b>「{{ del.row.name }}」</b>{{ del.kids ? `及其 ${del.kids} 个子节点` : '' }}？</p>
          <p v-if="del.rules" class="del-warn">该子树挂载的 {{ del.rules }} 条条目将失去归属（可在①规则页重新挂载），相关画像与缺口绑定一并失效。</p>
          <p class="del-warn">此操作不可恢复。</p>
          <p class="del-note">若当前选中在被删子树内，删除后自动回需求总览</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" data-test="del-cancel" @click="del = null">取消</button>
          <button class="btn-danger-ghost" type="button" data-test="del-ok" @click="confirmDel">删除</button>
        </div>
      </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
@keyframes spin { to { transform: rotate(360deg); } }
.tree { position: relative; padding-left: 26px; margin-top: 12px; }
.tree::before { content: ''; position: absolute; left: 10px; top: -14px; bottom: 12px; width: 2px; background: var(--border2); }
.mods { display: flex; flex-direction: column; gap: 9px; position: relative; }
.mod { position: relative; }
.mod::before { content: ''; position: absolute; left: -16px; top: 20px; width: 16px; height: 2px; background: var(--border2); }
.modcard { background: #fff; border: 1px solid var(--border2); border-radius: var(--radius); overflow: hidden; }
.modhead { display: flex; align-items: center; gap: 10px; padding: 9px 13px; cursor: pointer; flex-wrap: wrap; }
.modhead:hover { background: #f1f5fd; }
.modhead .chev { width: 0; height: 0; border-left: 5px solid var(--muted-fg); border-top: 4px solid transparent; border-bottom: 4px solid transparent; transition: transform 0.15s; flex: none; }
.mod.open .modhead .chev { transform: rotate(90deg); }
.modhead .mname { font-weight: 700; font-size: 13.5px; color: var(--primary); white-space: nowrap; }
.modhead .mdesc { color: var(--muted-fg); font-size: 12px; flex: 1; min-width: 120px; }
.modhead .mb { display: flex; gap: 5px; flex: none; align-items: center; }
.leaves { display: none; border-top: 1px dashed var(--border); background: #fbfdff; padding: 7px 12px 9px 28px; }
.mod.open .leaves { display: block; }
.leaf { display: flex; align-items: center; gap: 8px; padding: 5px 9px; border-radius: 6px; cursor: pointer; position: relative; flex-wrap: wrap; }
.leaf::before { content: ''; position: absolute; left: -11px; top: 50%; width: 11px; height: 1px; background: var(--border2); }
.leaf:hover { background: var(--blue-bg); }
.leaf.sel { background: var(--blue-bg); outline: 1.5px solid var(--secondary); }
.leaf .lname { font-weight: 600; white-space: nowrap; }
.leaf .ldesc { color: var(--muted-fg); font-size: 11.5px; flex: 1; min-width: 80px; }
.leaf .lb { display: flex; gap: 4px; flex: none; align-items: center; }
.top-leaf { background: #fff; border: 1px solid var(--border2); border-radius: var(--radius); padding: 7px 12px; }
.nbadge { font-size: 10px; font-weight: 700; border-radius: 8px; padding: 0 6px; display: inline-flex; align-items: center; gap: 3px; }
.nbadge.okc { background: var(--green-bg); color: var(--ok); }
.nbadge.unv { background: var(--muted); color: var(--muted-fg); }
.nbadge.cnt { background: var(--muted); color: var(--muted-fg); }
.nbadge.conf { background: var(--red-bg); color: var(--destructive); }
.nbadge.doubt { background: var(--amber-bg); color: var(--warn); }
.nbadge.doing { background: var(--blue-bg); color: var(--primary); }
.nbadge.doing::before { content: ''; width: 7px; height: 7px; border: 1.8px solid var(--primary); border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; }
.editops { display: none; gap: 3px; margin-left: 4px; }
.modhead:hover .editops, .leaf:hover .editops { display: inline-flex; }
.editops button { background: var(--muted); color: var(--muted-fg); width: 20px; height: 20px; border-radius: 5px; font-size: 11px; display: inline-flex; align-items: center; justify-content: center; }
.editops button:hover { background: var(--blue-bg); color: var(--primary); }
.unbucket { position: relative; margin: 10px 0; }
.unbucket .modcard { border-style: dashed; }
.unbucket .modhead .mname { color: var(--muted-fg); }
.rootcard { background: linear-gradient(135deg, #1e40af, #3b82f6); color: #fff; border-radius: 10px; padding: 14px 18px; cursor: pointer; position: relative; }
.rootcard:hover { box-shadow: 0 4px 16px rgba(30, 64, 175, 0.3); }
.rootcard.sel { outline: 2.5px solid var(--secondary); }
.rootcard h2 { font-size: 14.5px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rootcard p { margin-top: 5px; font-size: 12.5px; opacity: 0.93; }
.rootcard .rmeta { display: flex; gap: 7px; margin-top: 8px; flex-wrap: wrap; }
.rootcard .rmeta .badge { font-size: 11px; font-weight: 600; padding: 1px 8px; border-radius: 999px; display: inline-flex; align-items: center; background: rgba(255, 255, 255, 0.18); color: #fff; }
.rootcard .rmeta .badge.hot { background: #fecaca; color: #991b1b; }
.rootcard .rmeta .badge.warm { background: var(--amber-bg); color: var(--warn); }
.rootcard .corner { position: absolute; top: 12px; right: 14px; display: flex; gap: 6px; }
.rootcard .corner button { background: rgba(255, 255, 255, 0.16); color: #fff; font-size: 11px; padding: 3px 9px; font-weight: 600; border: none; cursor: pointer; border-radius: 6px; }
.rootcard .corner button:hover { background: rgba(255, 255, 255, 0.3); }
.hint { color: var(--muted-fg); font-size: 11.5px; margin-top: 12px; }
.add-root { width: 100%; margin-top: 9px; background: none; border: 1.5px dashed var(--border2); border-radius: var(--radius);
  color: var(--muted-fg); font-size: 12px; font-weight: 600; padding: 7px 0; cursor: pointer; }
.add-root:hover { border-color: var(--secondary); color: var(--primary); background: #f8faff; }
.tdlg { width: 400px; }
.tdlg textarea { width: 100%; border: 1px solid var(--border2); border-radius: 6px; padding: 7px 10px;
  font-family: inherit; font-size: 12.5px; resize: vertical; }
.deldlg { width: 400px; }
.deldlg .modal-foot { justify-content: flex-end; } /* foot 只留操作钮：右对齐一行，说明文字上移正文 */
.deldlg .del-q { font-size: 13.5px; }
.deldlg .del-q b { color: var(--fg); }
.deldlg .del-warn { font-size: 12px; color: var(--warn); margin-top: 8px; background: var(--amber-bg);
  border-radius: 6px; padding: 7px 10px; }
.deldlg .del-note { font-size: 11.5px; color: var(--muted-fg); margin-top: 8px; }
</style>
