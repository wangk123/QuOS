<script setup lang="ts">
// Task 7 工作台左主区语义树：根卡片（__root__）→ 模块卡（可折叠）→ 叶行。
// 数据源 wb（T5 聚合 /wb/summary 平铺行）；徽章直接用行数据 pend/conf（后端已含冲突，勿再 deriveBadge 双计）。
// 行内编辑：✎/＋ 走 treeOp（数字 path），goal 点击编辑走 PATCH /profiles/{path}（数字路径——full 含 / 路由不匹配）。
import { computed, inject, ref } from 'vue'
import { patchProfileGoal, treeOp, type WbNodeRow } from '../api'
import { refreshWb, wb } from '../wb'

defineProps<{ selected: string }>()
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

/** 根卡片统计徽章：rules/pend 只对顶层行求和——模块行是子树聚合值，再叠叶行会双计；顶层互不重叠且覆盖全树 */
const stat = computed(() => {
  const t = wb.value?.tree ?? []
  const top = mods.value.map(m => m.row)
  return {
    rules: top.reduce((s, r) => s + r.rules, 0),
    pend: top.reduce((s, r) => s + r.pend, 0),
    done: t.filter(r => r.state === 'done').length,
    doing: t.some(r => r.state === 'doing'),
    total: t.length,
  }
})

/** 徽章工作清单：行数据直出（doing 蓝 / pend 琥珀 / conf 红 / rules 灰 / profiled 清零绿） */
function badges(r: WbNodeRow): { cls: string; text: string }[] {
  const b: { cls: string; text: string }[] = []
  if (r.state === 'doing') b.push({ cls: 'doing', text: '处理中' })
  if (r.pend > 0) b.push({ cls: 'warn', text: `${r.pend} 待判断` })
  if (r.conf > 0) b.push({ cls: 'conf', text: `⚠${r.conf}` })
  if (r.rules > 0) b.push({ cls: 'cnt', text: `${r.rules} 条` })
  if (r.profiled && r.pend === 0) b.push({ cls: 'okc', text: '✓' })
  return b
}

/** 折叠态（默认全展开）；按数字 path 记忆 */
const closed = ref(new Set<string>())
function toggle(path: string) {
  const next = new Set(closed.value)
  next.has(path) ? next.delete(path) : next.add(path)
  closed.value = next
}

async function onRename(row: WbNodeRow) {
  const name = prompt('新名称', row.name)
  if (!name?.trim() || name.trim() === row.name) return
  try {
    await treeOp('rename', row.path, name.trim())
    await refreshWb()
  } catch (e) {
    toast(`改名失败：${e instanceof Error ? e.message : e}`)
  }
}

async function onAdd(row: WbNodeRow) {
  const name = prompt(`加子节点 · ${row.name}`)
  if (!name?.trim()) return
  try {
    await treeOp('add', row.path, name.trim())
    await refreshWb()
  } catch (e) {
    toast(`加节点失败：${e instanceof Error ? e.message : e}`)
  }
}

async function onGoal(row: WbNodeRow) {
  const goal = prompt(`「${row.name}」目标（一句话）`, row.goal)
  if (goal === null || goal === row.goal) return
  try {
    await patchProfileGoal(row.path, goal)
    await refreshWb()
  } catch (e) {
    toast(`目标保存失败：${e instanceof Error ? e.message : e}`)
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
          <span v-if="stat.pend" class="badge hot">{{ stat.pend }} 待判断</span>
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
                <span class="mdesc" title="点击编辑目标" @click.stop="onGoal(m.row)">{{ m.row.goal }}</span>
                <span class="mb">
                  <span v-for="b in badges(m.row)" :key="b.cls + b.text" class="nbadge" :class="b.cls">{{ b.text }}</span>
                  <span class="editops">
                    <button title="改名" type="button" @click.stop="onRename(m.row)">✎</button>
                    <button title="加子节点" type="button" @click.stop="onAdd(m.row)">＋</button>
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
                  <span v-if="f.r.goal" class="ldesc" title="点击编辑目标" @click.stop="onGoal(f.r)">{{ f.r.goal }}</span>
                  <span class="lb">
                    <span v-for="b in badges(f.r)" :key="b.cls + b.text" class="nbadge" :class="b.cls">{{ b.text }}</span>
                    <span class="editops">
                      <button title="改名" type="button" @click.stop="onRename(f.r)">✎</button>
                      <button title="加子节点" type="button" @click.stop="onAdd(f.r)">＋</button>
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
            <span v-if="m.row.goal" class="ldesc" title="点击编辑目标" @click.stop="onGoal(m.row)">{{ m.row.goal }}</span>
            <span class="lb">
              <span v-for="b in badges(m.row)" :key="b.cls + b.text" class="nbadge" :class="b.cls">{{ b.text }}</span>
              <span class="editops">
                <button title="改名" type="button" @click.stop="onRename(m.row)">✎</button>
                <button title="加子节点" type="button" @click.stop="onAdd(m.row)">＋</button>
              </span>
            </span>
          </div>
        </template>
      </div>
    </div>
    <p class="hint">这棵树就是需求文档本身——节点、目标随时可改（hover 出现 ✎ ＋），改动即时生效。</p>
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
.modhead .mdesc { color: var(--muted-fg); font-size: 12px; flex: 1; min-width: 120px; cursor: pointer; }
.modhead .mdesc:hover { color: var(--primary); }
.modhead .mb { display: flex; gap: 5px; flex: none; align-items: center; }
.leaves { display: none; border-top: 1px dashed var(--border); background: #fbfdff; padding: 7px 12px 9px 28px; }
.mod.open .leaves { display: block; }
.leaf { display: flex; align-items: center; gap: 8px; padding: 5px 9px; border-radius: 6px; cursor: pointer; position: relative; flex-wrap: wrap; }
.leaf::before { content: ''; position: absolute; left: -11px; top: 50%; width: 11px; height: 1px; background: var(--border2); }
.leaf:hover { background: var(--blue-bg); }
.leaf.sel { background: var(--blue-bg); outline: 1.5px solid var(--secondary); }
.leaf .lname { font-weight: 600; white-space: nowrap; }
.leaf .ldesc { color: var(--muted-fg); font-size: 11.5px; flex: 1; min-width: 80px; cursor: pointer; }
.leaf .ldesc:hover { color: var(--primary); }
.leaf .lb { display: flex; gap: 4px; flex: none; align-items: center; }
.top-leaf { background: #fff; border: 1px solid var(--border2); border-radius: var(--radius); padding: 7px 12px; }
.nbadge { font-size: 10px; font-weight: 700; border-radius: 8px; padding: 0 6px; display: inline-flex; align-items: center; gap: 3px; }
.nbadge.okc { background: var(--green-bg); color: var(--ok); }
.nbadge.warn { background: var(--amber-bg); color: var(--warn); }
.nbadge.cnt { background: var(--muted); color: var(--muted-fg); }
.nbadge.conf { background: var(--red-bg); color: var(--destructive); }
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
.rootcard .corner { position: absolute; top: 12px; right: 14px; display: flex; gap: 6px; }
.rootcard .corner button { background: rgba(255, 255, 255, 0.16); color: #fff; font-size: 11px; padding: 3px 9px; font-weight: 600; border: none; cursor: pointer; border-radius: 6px; }
.rootcard .corner button:hover { background: rgba(255, 255, 255, 0.3); }
.hint { color: var(--muted-fg); font-size: 11.5px; margin-top: 12px; }
</style>
