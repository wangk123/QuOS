// 批注类型:kind → 展示类型(术语确认从 confirm 单列);批注栏筛选与卡片徽标共用
import type { Question } from '../api'

export type AnnoType = '待决策' | '确认' | '术语确认' | '补写' | '批量确认'

export function annoType(q: Question): AnnoType {
  if (q.kind === 'choice') return '待决策'
  if (q.kind === 'confirm') return q.payload?.klabel === '术语确认' ? '术语确认' : '确认'
  if (q.kind === 'fill') return '补写'
  return '批量确认'
}

export const ANNO_TYPE_CLS: Record<AnnoType, string> = {
  '待决策': 't-choice',
  '确认': 't-confirm',
  '术语确认': 't-term',
  '补写': 't-fill',
  '批量确认': 't-scan',
}

export const ANNO_TYPE_ORDER: AnnoType[] = ['待决策', '确认', '术语确认', '补写', '批量确认']

/** 渲染前结构自检:字段取不到返回错误说明(null=正常)。空白渲染=静默降级,违规;异常必须显式亮出 */
export function annoStructErr(q: Question): string | null {
  const p = q.payload ?? {}
  if (!String(p.q ?? '').trim()) return 'payload.q 缺失或为空'
  if (q.kind === 'choice') {
    const opts = p.options
    if (!Array.isArray(opts) || opts.length < 2) return 'choice options 须为 ≥2 元素的数组'
    for (let i = 0; i < opts.length; i++) {
      const o: any = opts[i]
      if (typeof o !== 'object' || o === null || !String(o.k ?? '').trim() || !String(o.t ?? '').trim())
        return `options[${i}] 非 {k, t} 对象(${JSON.stringify(o).slice(0, 40)})`
    }
  }
  return null
}
