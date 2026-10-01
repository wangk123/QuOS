// Task 9 Workbench 布局壳：树空→Landing；树非空→左 WbTree(.treezone)/右 WbDetail(.detailzone)。
// brief Step 1 测试按 mock 结构改写（@vue/test-utils，T6 裁定：无 @testing-library/vue）。
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Workbench from '../Workbench.vue'
import { jobRunning } from '../../jobs'

// 可变 wb mock（vi.hoisted 保证 vi.mock 工厂执行时可引用；useWb 返回同一共享 ref）
const wbData = vi.hoisted(() => ({
  root: null as { goal: string } | null,
  tree: [] as {
    path: string; name: string; full: string; goal: string; kind: 'module' | 'leaf'
    rules: number; pend: number; conf: number; profiled: boolean; state: '' | 'done' | 'doing'
  }[],
}))
const mockRefreshWb = vi.hoisted(() => vi.fn())
vi.mock('../../wb', () => {
  const wb = ref(wbData)
  return { wb, refreshWb: mockRefreshWb, useWb: () => ({ wb, refreshWb: mockRefreshWb, stop: vi.fn() }) }
})
// jobRunning 的 ref 在 mock 工厂内创建（hoisted 回调早于 import 初始化，不能引用顶层 ref）
vi.mock('../../jobs', async () => {
  const { ref } = await import('vue')
  return { jobRunning: ref(false) }
})

// 子组件桩：WbTree 点击发 pick；WbDetail 透显 nodeFull·state 供断言
vi.mock('../../components/WbTree.vue', () => ({
  default: { name: 'WbTree', props: ['selected'], emits: ['pick', 'refresh-root', 'edit-root'], template: '<div class="stub-tree" @click="$emit(\'pick\', \'工具模块\')">树</div>' },
}))
vi.mock('../Landing.vue', () => ({
  default: { name: 'Landing', emits: ['generated'], template: '<div class="landing">导入框</div>' },
}))
vi.mock('../WbDetail.vue', () => ({
  default: { name: 'WbDetail', props: ['nodeFull', 'state'], emits: ['jump'], template: '<div class="detailzone">{{ nodeFull }}·{{ state }}</div>' },
}))

const ROW = {
  path: '0', name: '工具模块', full: '工具模块', goal: '五技能', kind: 'module' as const,
  rules: 73, pend: 3, conf: 1, profiled: true, state: 'done' as const,
}

describe('Workbench 布局壳', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    wbData.root = null
    wbData.tree = []
    jobRunning.value = false
  })

  it('树空整页渲染 Landing，generated 后 refreshWb 切态', async () => {
    const w = mount(Workbench)
    expect(w.find('.landing').exists()).toBe(true)
    expect(w.find('.treezone').exists()).toBe(false)
    mockRefreshWb.mockClear() // 隔离 useWb 挂载期的首次拉取
    await w.findComponent({ name: 'Landing' }).vm.$emit('generated')
    expect(mockRefreshWb).toHaveBeenCalledTimes(1)
    w.unmount()
  })

  it('树非空渲染左树右详情（默认选中根，根无 running job 视为就绪）', () => {
    wbData.root = { goal: '总览' }
    wbData.tree = [ROW]
    const w = mount(Workbench)
    expect(w.find('.treezone').exists()).toBe(true)
    expect(w.find('.detailzone').exists()).toBe(true)
    expect(w.find('.detailzone').text()).toBe('__root__·done')
    w.unmount()
  })

  it('WbTree pick → WbDetail 收到新 nodeFull（state 查行数据）', async () => {
    wbData.tree = [{ ...ROW, state: 'doing' }]
    const w = mount(Workbench)
    await w.find('.stub-tree').trigger('click') // 桩点击 emit pick('工具模块')
    expect(w.find('.detailzone').text()).toBe('工具模块·doing')
    w.unmount()
  })
})
