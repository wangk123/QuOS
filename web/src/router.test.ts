// hashchange 路由同步：syncFromHash 可重入（初始化/浏览器前进后退共用）
import { afterEach, describe, expect, it } from 'vitest'
import { curSlug, setProject } from './api'
import { syncFromHash, top } from './router'

describe('router syncFromHash', () => {
  afterEach(() => {
    location.hash = ''
    top.value = 'home'
    setProject('')
  })

  it('后退到 #/ 回到 home 态（curSlug 清空）', () => {
    top.value = 'proj'
    setProject('某项目')
    location.hash = '#/'
    syncFromHash()
    expect(top.value).toBe('home')
    expect(curSlug.value).toBe('')
  })

  it('前进/后退到 #/p/<slug> 恢复工作台', () => {
    location.hash = `#/p/${encodeURIComponent('风控云')}`
    syncFromHash()
    expect(top.value).toBe('proj')
    expect(curSlug.value).toBe('风控云')
  })

  it('状态一致时幂等跳过', () => {
    top.value = 'proj'
    setProject('风控云')
    location.hash = `#/p/${encodeURIComponent('风控云')}`
    syncFromHash()
    expect(top.value).toBe('proj')
    expect(curSlug.value).toBe('风控云')
  })

  it('#/p/ 缺 slug 停留当前态', () => {
    top.value = 'proj'
    setProject('某项目')
    location.hash = '#/p/'
    syncFromHash()
    expect(top.value).toBe('proj')
    expect(curSlug.value).toBe('某项目')
  })

  it('畸形 hash 抛错由调用方兜底', () => {
    top.value = 'proj'
    setProject('某项目')
    location.hash = '#/p/%'
    expect(() => syncFromHash()).toThrow()
    expect(top.value).toBe('proj') // 未中途改状态
    expect(curSlug.value).toBe('某项目')
  })
})
