// toast 提示:右上角堆叠,2.6s 自动消失
import { createApp, defineComponent, h, ref } from 'vue'

interface Item { id: number; msg: string; type: string }

const items = ref<Item[]>([])
let seq = 0

export function toast(msg: string, type: 'success' | 'warn' = 'success'): void {
  const id = ++seq
  items.value.push({ id, msg, type })
  setTimeout(() => {
    items.value = items.value.filter((i) => i.id !== id)
  }, 2600)
}

const ToastHost = defineComponent({
  setup() {
    return () =>
      h('div', { class: 'toasts' },
        items.value.map((i) =>
          h('div', { class: `toast ${i.type}`, key: i.id }, [
            h('span', { class: 't-i' }, [h('b', i.type === 'success' ? '✓' : '!')]),
            i.msg,
          ])))
  },
})

export function mountToasts(parent: HTMLElement): void {
  createApp(ToastHost).mount(parent)
}
