// 微型 hash 路由(不引 vue-router):#/projects | #/p/:pid/materials|review|versions
import { reactive } from 'vue'

export interface Route { view: string; pid: number }

export const route = reactive<Route>({ view: 'projects', pid: 0 })

function parse(): void {
  const h = location.hash
  const m = h.match(/^#\/p\/(\d+)\/(materials|review|versions)$/)
  if (m) {
    route.view = m[2]
    route.pid = Number(m[1])
  } else {
    route.view = 'projects'
    route.pid = 0
  }
}

export function go(hash: string): void {
  location.hash = hash
}

parse()
window.addEventListener('hashchange', parse)
