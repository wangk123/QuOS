/* 需求一页纸骨架解析器——纯函数,容错优先:缺节给空值,未知行忽略,永不抛 */

export interface OneSeg { t: string; hl: boolean }
export interface OneCard {
  name: string
  role: string
  chapters: string
  segs: OneSeg[]
}
export interface OnePagerDoc {
  title: string
  meta: string[]
  head: Array<{ k: string; v: string }>
  flow: Array<{ label: string; human: boolean }>
  flowNote: string
  groups: Array<{ title: string; cards: OneCard[] }>
  scenarios: string[]
  todo: { x: number; y: number; z: number }
}

/* 把含成对 ** 的文本切成 高亮/普通 片段;不成对星号按普通文本收,不抛 */
export function splitSegs(text: string): OneSeg[] {
  const out: OneSeg[] = []
  let rest = text
  let hl = false
  while (rest) {
    const i = rest.indexOf('**')
    if (i < 0) break
    if (i > 0) out.push({ t: rest.slice(0, i), hl })
    rest = rest.slice(i + 2)
    if (hl) { hl = false; continue } // 收口的一对:下一段回归普通——上面 push 的即高亮段
    // 开标记:检查后面是否还有收口
    const j = rest.indexOf('**')
    if (j < 0) break
    if (j > 0) out.push({ t: rest.slice(0, j), hl: true })
    rest = rest.slice(j + 2)
  }
  if (rest) out.push({ t: rest, hl })
  return out.filter((s) => s.t !== '')
}

/* 角色括号宽容:全角为契约语法,半角/缺失容忍(角色空),卡不丢 */
const CARD_RE = /^\*\*(.+?)\*\*(?:（([^）]*)）|\(([^)]*)\))?\s*〔正文\s*(.*?)〕：(.*)$/

export function parseOnePager(md: string): OnePagerDoc {
  const doc: OnePagerDoc = {
    title: '', meta: [], head: [], flow: [], flowNote: '',
    groups: [], scenarios: [], todo: { x: 0, y: 0, z: 0 },
  }
  const lines = md.split('\n')
  let section = ''      // 当前 ## 节
  let group: { title: string; cards: OneCard[] } | null = null
  let flowDone = false  // 链路节里首个含 → 的行才是链,其后是注解

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) continue

    if (line.startsWith('# ')) {
      doc.title = line.slice(2).replace(/\s*·\s*需求一页纸\s*$/, '')
      continue
    }
    if (line.startsWith('> ')) { doc.meta.push(line.slice(2).trim()); continue }
    if (line.startsWith('## ')) {
      section = line.slice(3).trim()
      if (section === '能力速览') group = null
      continue
    }
    if (line.startsWith('### ') && section === '能力速览') {
      group = { title: line.slice(4).trim(), cards: [] }
      doc.groups.push(group)
      continue
    }

    const head = line.match(/^\*\*(.+?)\*\*：(.*)$/)
    if (head && !section) { doc.head.push({ k: head[1], v: head[2] }); continue }

    if (section === '核心链路') {
      if (!flowDone && line.includes('→')) {
        flowDone = true
        for (const part of line.split('→')) {
          const label = part.trim()
          if (label) doc.flow.push({ label: label.replace(/〔人工〕$/, ''), human: label.endsWith('〔人工〕') })
        }
      } else if (flowDone) {
        doc.flowNote = (doc.flowNote ? doc.flowNote + ' ' : '') + line.trim()
      }
      continue
    }

    if (section === '能力速览' && group) {
      const m = line.match(CARD_RE)
      if (m) group.cards.push({ name: m[1], role: m[2] ?? m[3] ?? '', chapters: m[4], segs: splitSegs(m[5]) })
      continue
    }

    if (section === '场景速览') {
      doc.scenarios.push(...line.split(/[、，,]/).map((s) => s.trim()).filter(Boolean))
      continue
    }

    if (section === '待裁事项') {
      const m = line.match(/送裁\s*(\d+).*?确认\s*(\d+).*?填空\s*(\d+)/)
      if (m) doc.todo = { x: Number(m[1]), y: Number(m[2]), z: Number(m[3]) }
      continue
    }
    // 其余未知行:忽略
  }
  return doc
}
