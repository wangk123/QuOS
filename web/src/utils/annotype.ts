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
