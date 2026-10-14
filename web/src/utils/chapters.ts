// 章节层级工具:DocPaper(正文编号渲染)与 ChapterTree(左栏树)共用同一份展开逻辑
import type { ChapterP } from '../api'

/** 术语表合成章节 id:ReviewView 注入 payload.chapters 末尾,DocPaper 特判渲染词条表,目录随之出现单条入口 */
export const GLOSSARY_CH_ID = '__glossary__'

export interface FlatChapter { c: ChapterP; no: string; sub: boolean; depth: number }

/** 按 parent 展开为线性序(子章紧随父章),编号 1 / 1.1,depth 0 起(目录缩进用);parent 断链的孤儿按顶层兜底 */
export function flattenChapters(chapters: ChapterP[]): FlatChapter[] {
  const ids = new Set(chapters.map((c) => c.id))
  const kids = new Map<string, ChapterP[]>()
  const tops: ChapterP[] = []
  for (const c of chapters) {
    if (c.parent && ids.has(c.parent)) kids.set(c.parent, [...(kids.get(c.parent) ?? []), c])
    else tops.push(c)
  }
  const out: FlatChapter[] = []
  const walk = (c: ChapterP, prefix: string, depth: number, idx: number) => {
    const no = prefix ? `${prefix}.${idx}` : `${idx}`
    out.push({ c, no, sub: depth > 0, depth })
    for (const [i, k] of (kids.get(c.id) ?? []).entries()) walk(k, no, depth + 1, i + 1)
  }
  for (const [i, t] of tops.entries()) walk(t, '', 0, i + 1)
  const seen = new Set(out.map((o) => o.c.id))
  for (const c of chapters) if (!seen.has(c.id)) walk(c, '', 0, out.length + 1)
  return out
}

/** 术语在正文中的出现章节:确定性字符串匹配(标题/背景/正文块/规则文本),按线性序首个命中 */
export function termChapters(term: string, chapters: ChapterP[], rules: Record<string, { text?: string }>): string[] {
  const ids: string[] = []
  for (const { c } of flattenChapters(chapters)) {
    const texts = [c.title, c.background, ...(c.blocks ?? []).map((b) =>
      b.type === 'table' ? (b.rows ?? []).flat().join(' ') : `${b.text ?? ''} ${(b.items ?? []).join(' ')} ${(b.flows ?? []).join(' ')}`)]
    for (const no of c.rule_nos) texts.push(rules[no]?.text ?? '')
    if (texts.some((t) => t?.includes(term))) ids.push(c.id)
  }
  return ids
}
