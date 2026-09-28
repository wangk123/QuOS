// 规则表分组：按 模块（父路径）› 功能点 两级聚合；组内功能点按 P0→P1→P2→空、再按树序。
// 失配归属（节点改名残留）与空 node 均进 unclassified，由人工重新挂载。
import type { Assertion, TreeNode } from './api'

export interface GroupedPoint {
  path: string
  name: string
  priority: string
  order: number
  rules: Assertion[]
}
export interface RuleGroup {
  key: string
  label: string
  order: number
  nodes: GroupedPoint[]
}
export interface GroupResult {
  groups: RuleGroup[]
  unclassified: Assertion[]
}

const PRIO_RANK: Record<string, number> = { P0: 0, P1: 1, P2: 2, '': 3 }

interface Index {
  path: string
  name: string
  parent: string // 父路径；顶层节点为 ''
  priority: string
  order: number
}

function indexTree(nodes: TreeNode[], prefix = '', counter = { n: 0 }): Index[] {
  const out: Index[] = []
  for (const nd of nodes) {
    const path = prefix ? `${prefix}/${nd.name}` : nd.name
    out.push({ path, name: nd.name, parent: prefix, priority: nd.priority ?? '', order: counter.n++ })
    out.push(...indexTree(nd.children, path, counter))
  }
  return out
}

export function buildGroups(rules: Assertion[], treeNodes: TreeNode[]): GroupResult {
  const idx = indexTree(treeNodes)
  const byPath = new Map(idx.map(i => [i.path, i]))
  const rulesOf = new Map<string, Assertion[]>()
  const unclassified: Assertion[] = []
  for (const r of rules) {
    if (r.node && byPath.has(r.node)) {
      const arr = rulesOf.get(r.node) ?? []
      arr.push(r)
      rulesOf.set(r.node, arr)
    } else {
      unclassified.push(r)
    }
  }
  const groupMap = new Map<string, RuleGroup>()
  for (const i of idx) {
    const rs = rulesOf.get(i.path)
    if (!rs?.length) continue
    const g =
      groupMap.get(i.parent) ??
      ({ key: i.parent, label: i.parent || '（未分组）', order: -1, nodes: [] } as RuleGroup)
    g.nodes.push({ path: i.path, name: i.name, priority: i.priority, order: i.order, rules: rs })
    groupMap.set(i.parent, g)
  }
  const groups = [...groupMap.values()]
  for (const g of groups) {
    g.order = idx.find(i => i.path === (g.nodes[0] as GroupedPoint).path)!.order
    g.nodes.sort((a, b) => PRIO_RANK[a.priority] - PRIO_RANK[b.priority] || a.order - b.order)
  }
  groups.sort((a, b) => (a.key === '' ? -1 : b.key === '' ? 1 : a.order - b.order))
  return { groups, unclassified }
}
