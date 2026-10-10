// 受限 markdown 渲染器（spec：版本管理 §4）——只覆盖导出文档用到的语法子集：
// #~###### 标题 / - 列表 / | 表格（\| 转义）/ 空行分段（段内换行转 <br>）。
// 输入源自材料与用户输入：所有文本先 escape 再组标签，v-html 无注入面。
const esc = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')

const splitRow = (line: string): string[] =>
  line.replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map(c => c.replace(/\\\|/g, '|').trim())

export function renderMd(src: string): string {
  const lines = src.split('\n')
  const out: string[] = []
  let para: string[] = []
  let list: string[] = []
  let table: string[][] = []

  const isSepRow = (cells: string[]) =>
    cells.length > 0 && cells.every(c => /^:?-+:?$/.test(c))

  const flush = () => {
    if (para.length) out.push(`<p>${para.map(esc).join('<br>')}</p>`)
    if (list.length) out.push(`<ul>${list.map(i => `<li>${esc(i)}</li>`).join('')}</ul>`)
    if (table.length) {
      let [head, ...body] = table
      if (body.length && isSepRow(body[0])) body = body.slice(1)  // 剔除 |---|---| 分隔行
      const th = `<tr>${head.map(c => `<th>${esc(c)}</th>`).join('')}</tr>`
      const tb = body.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')
      out.push(`<table><thead>${th}</thead><tbody>${tb}</tbody></table>`)
    }
    para = []; list = []; table = []
  }

  for (const line of lines) {
    const h = line.match(/^(#{1,6}) (.*)$/u)
    const li = line.match(/^- (.*)$/u)
    if (h) { flush(); out.push(`<h${h[1].length}>${esc(h[2].trim())}</h${h[1].length}>`) }
    else if (li) {
      if (para.length || table.length) flush()  // 跨类型切换才成块
      list.push(li[1].trim())
    }
    else if (line.startsWith('|')) {
      if (para.length || list.length) flush()
      table.push(splitRow(line))
    }
    else if (!line.trim()) flush()
    else {
      if (list.length || table.length) flush()  // 列表/表格后接裸文本 → 各自成段
      para.push(line.trim())
    }
  }
  flush()
  return out.join('')
}
