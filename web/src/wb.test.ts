import { describe, expect, it } from 'vitest'
import { deriveBadge } from './wb'
describe('deriveBadge', () => {
  it('未核+冲突合计为待判断', () => expect(deriveBadge({ rules: 39, pend: 4, conf: 1 })).toEqual({ pend: 5, conf: 1 }))
  it('全清显示就绪', () => expect(deriveBadge({ rules: 5, pend: 0, conf: 0 })).toEqual({ pend: 0, conf: 0 }))
})
