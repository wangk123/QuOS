import { describe, expect, it } from 'vitest'
import { buildGroups } from './grouping'
import type { Rule, TreeNode } from './api'

const A = (id: string, node: string, verified = true): Rule =>
  ({ id, text: id, src: 's', conf: '实证', st: 'open', verified, suspect: false, node })

const TREE: TreeNode[] = [
  { name: '支付', children: [{ name: '放款重试', children: [], open: true, priority: 'P1' }], open: true, priority: '' },
  { name: '风控', children: [{ name: '额度', children: [], open: true, priority: 'P0' },
    { name: '黑名单', children: [], open: true, priority: '' }], open: true, priority: 'P2' },
]

describe('buildGroups', () => {
  it('按父路径分组，功能点挂父组', () => {
    const { groups, unclassified } = buildGroups([A('R1', '支付/放款重试'), A('R2', '风控/额度')], TREE)
    expect(unclassified).toHaveLength(0)
    const pay = groups.find(g => g.label === '支付')!
    expect(pay.nodes.map(n => n.path)).toEqual(['支付/放款重试'])
    expect(pay.nodes[0].rules.map(r => r.id)).toEqual(['R1'])
  })
  it('组内功能点按 P0→P1→P2→空 再按树序', () => {
    const { groups } = buildGroups([A('R1', '风控/额度'), A('R2', '风控/黑名单')], TREE)
    expect(groups.find(g => g.label === '风控')!.nodes.map(n => n.name)).toEqual(['额度', '黑名单'])
  })
  it('顶层功能点（无父）进「（未分组）」且置顶', () => {
    const tree: TreeNode[] = [{ name: '放款', children: [], open: true, priority: '' }]
    const { groups } = buildGroups([A('R1', '放款')], tree)
    expect(groups[0].label).toBe('（未分组）')
  })
  it('node 失配（改名残留）与空 node 都进未归类，不丢', () => {
    const { unclassified } = buildGroups([A('R1', ''), A('R2', '已被改名/旧路径')], TREE)
    expect(unclassified.map(a => a.id)).toEqual(['R1', 'R2'])
  })
  it('组头统计：核验 n/m', () => {
    const { groups } = buildGroups([A('R1', '风控/额度'), A('R2', '风控/额度', false)], TREE)
    const n = groups.find(g => g.label === '风控')!.nodes[0]
    expect(n.rules.length).toBe(2)
    expect(n.rules.filter(r => r.verified).length).toBe(1)
  })
})
