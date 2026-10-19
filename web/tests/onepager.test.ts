import { describe, expect, it } from 'vitest'
import { parseOnePager } from '../src/utils/onepager'

/* 一页纸骨架解析器测试:完整骨架逐字段 / 容错不抛 */

const MD = `# 瀚海多模态服务 · 需求一页纸

> draft-v1 · 2026-10-15 · 待裁 19 题

**这是什么**：给尽调做多材料**结构化的流水线服务**。
**解决什么**：人工逐份抄录口径不一 → 全链路自动处理。
**给谁用**：业务操作员、材料配置管理员、外部系统（机器）。
**不做什么**：不产业务结论；不代下游加工报文。

## 核心链路
材料进入 → 解析识别 → 自动分类 → 人工确认〔人工〕 → 结构化抽取 → 人工复核〔人工〕 → 发布固化 → API 交付

机器负责识别与计算，人只做确认与裁决。

## 能力速览

### 主线 · 从材料到交付
**受理单与影像树**（业务载体）〔正文 5〕：全部业务动作挂在**受理单**上；影像树定义这笔业务要哪些影像。

### 支撑 · 质量与运转
**材料分类**（定型）〔正文 7〕：机器双路径给候选，**人做终审**。

**规则管理**（校验配置）〔正文 13-14〕：规则在这里设计、发布。

## 场景速览
受理办结、审阅修复、配置上线、机器对接

## 待裁事项
送裁 7 · 确认 7 · 填空 5——评审前先看文档末问题清单
`

describe('parseOnePager 完整骨架', () => {
  const doc = parseOnePager(MD)

  it('title 去掉「· 需求一页纸」后缀', () => {
    expect(doc.title).toBe('瀚海多模态服务')
  })

  it('meta 收引用行', () => {
    expect(doc.meta).toEqual(['draft-v1 · 2026-10-15 · 待裁 19 题'])
  })

  it('head 四行按 k/v 收', () => {
    expect(doc.head.map((h) => h.k)).toEqual(['这是什么', '解决什么', '给谁用', '不做什么'])
    expect(doc.head[0].v).toContain('结构化的流水线服务')
  })

  it('链路节点切分且〔人工〕剥离置 human', () => {
    expect(doc.flow.map((n) => n.label)).toEqual(
      ['材料进入', '解析识别', '自动分类', '人工确认', '结构化抽取', '人工复核', '发布固化', 'API 交付'])
    expect(doc.flow.filter((n) => n.human).map((n) => n.label)).toEqual(['人工确认', '人工复核'])
  })

  it('链路注解行为 flowNote', () => {
    expect(doc.flowNote).toBe('机器负责识别与计算，人只做确认与裁决。')
  })

  it('两组卡:组名/卡名/角色/章号/正文 segs 高亮位', () => {
    expect(doc.groups.map((g) => g.title)).toEqual(['主线 · 从材料到交付', '支撑 · 质量与运转'])
    const main = doc.groups[0].cards[0]
    expect(main.name).toBe('受理单与影像树')
    expect(main.role).toBe('业务载体')
    expect(main.chapters).toBe('5')
    expect(main.segs.some((s) => s.hl && s.t === '受理单')).toBe(true)
    const sup = doc.groups[1].cards
    expect(sup.map((c) => c.name)).toEqual(['材料分类', '规则管理'])
    expect(sup[1].chapters).toBe('13-14')
  })

  it('场景按「、」切', () => {
    expect(doc.scenarios).toEqual(['受理办结', '审阅修复', '配置上线', '机器对接'])
  })

  it('待裁三数解析', () => {
    expect(doc.todo).toEqual({ x: 7, y: 7, z: 5 })
  })
})

describe('parseOnePager 容错', () => {
  it('缺节不抛:无待裁/无场景/无链路 → 空值兜底', () => {
    const doc = parseOnePager('# X · 需求一页纸\n\n**这是什么**：一句话。\n')
    expect(doc.title).toBe('X')
    expect(doc.todo).toEqual({ x: 0, y: 0, z: 0 })
    expect(doc.flow).toEqual([])
    expect(doc.scenarios).toEqual([])
    expect(doc.groups).toEqual([])
  })

  it('未知行与未知节被忽略', () => {
    const doc = parseOnePager(MD.replace('## 场景速览', '## 未知节\n乱七八糟\n\n## 场景速览'))
    expect(doc.scenarios).toEqual(['受理办结', '审阅修复', '配置上线', '机器对接'])
  })

  it('半角括号宽容识别:卡不丢,角色照样解析', () => {
    const doc = parseOnePager(MD.replace('（业务载体）', '(业务载体)'))
    expect(doc.groups[0].cards[0].role).toBe('业务载体')
  })

  it('半角冒号宽容:卡与头行照样解析', () => {
    const doc = parseOnePager(MD.replace('〔正文 7〕：机器双路径', '〔正文 7〕:机器双路径')
                                 .replace('**这是什么**：', '**这是什么**: '))
    expect(doc.groups[1].cards[0].segs.length).toBeGreaterThan(0)
    expect(doc.head[0].v).toContain('流水线服务')
  })

  it('不成对粗体整段低亮不抛', () => {
    const doc = parseOnePager(MD.replace('**受理单**', '**受理单'))
    const segs = doc.groups[0].cards[0].segs
    expect(segs.length).toBeGreaterThan(0)
    expect(segs.every((s) => typeof s.hl === 'boolean')).toBe(true)
  })
})

/* 组件挂载冒烟:OnePager 渲染组/卡/链路,点卡 emit jump */
import { mount } from '@vue/test-utils'
import OnePager from '../src/components/rev/OnePager.vue'

describe('OnePager.vue 冒烟', () => {
  const doc = parseOnePager(MD)
  const w = mount(OnePager, { props: { doc } })

  it('渲染两组卡与链路人工节点', () => {
    expect(w.findAll('.dom')).toHaveLength(3)
    expect(w.findAll('.grp-t').map((g) => g.text())).toContain('主线 · 从材料到交付')
    expect(w.findAll('.fnode.human')).toHaveLength(2)
  })

  it('点卡 emit jump(章号串)', async () => {
    await w.findAll('.dom')[1].trigger('click')
    expect(w.emitted('jump')![0]).toEqual(['7'])
  })

  it('文本插值不做 esc:含 & 显示为 & 而非实体', async () => {
    const d = parseOnePager(MD.replace('机器双路径给候选', 'A & B 机器双路径给候选'))
    const w2 = mount(OnePager, { props: { doc: d } })
    const all = w2.findAll('.dom-body').map((x) => x.text()).join('\n')
    expect(all).toContain('A & B')
    expect(all).not.toContain('&amp;')
  })
})

/* 入口数据源判定:有草案只认草案(重导清空不回退),基线态(empty 响应)才看基线 */
import { resolveOnePagerMd } from '../src/utils/onepager'

describe('resolveOnePagerMd', () => {
  it('有 reviewing 草案:只认草案', () => {
    expect(resolveOnePagerMd({ one_pager_md: 'x' }, { one_pager_md: 'y' })).toBe('x')
  })
  it('草案已清空:不回退旧基线(重导清空语义)', () => {
    expect(resolveOnePagerMd({ one_pager_md: null }, { one_pager_md: 'y' })).toBeNull()
  })
  it('无草案(empty:true 响应):看基线——finalize 后入口不消失', () => {
    expect(resolveOnePagerMd({ empty: true }, { one_pager_md: 'y' })).toBe('y')
  })
  it('双空', () => {
    expect(resolveOnePagerMd(null, null)).toBeNull()
  })
})
