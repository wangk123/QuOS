<script setup lang="ts">
import { computed, inject, ref } from 'vue'

// 澄清池 V2 预览版：用户画像流 + 选择题/补材料两类题型。
// 当前为纯前端 mock（开关在 AskDrawer），交互全部本地模拟，不调 API。
interface ClarItem {
  no: number
  q: string
  kind: 'choice' | 'open'
  opts: string[]
  hint?: string
  st: 'wait' | 'answered' | 'verified'
  answer: string | null
  ref: string | null
  from: string
}

const MOCK: ClarItem[] = [
  {
    no: 9, kind: 'choice', st: 'wait', answer: null, ref: null, from: '② 冲突裁决',
    q: '支付渠道异步通知与订单状态机不一致时的对账兜底策略怎么定？材料 A 处说「以渠道通知为准实时更新订单」，材料 B 处说「订单状态只能由本系统流转」，涉及掉单、重复通知与金额不符三类异常时，自动处理与人工介入的边界是什么？',
    opts: [
      '以渠道对账文件为准自动冲正，差异单挂起，次日人工复核',
      '实时双向核对，不一致即冻结订单，等待人工处理',
      '仅记录差异报表，不做任何自动处理',
    ],
  },
  {
    no: 10, kind: 'choice', st: 'wait', answer: null, ref: 'A12', from: '① 规则提取',
    q: '授信审批被拒绝后，客户重新提交申请的冷却期是多久？',
    opts: ['7 天', '30 天', '90 天', '无冷却期，可立即重提'],
  },
  {
    no: 11, kind: 'open', st: 'wait', answer: null, ref: null, from: '④ 查漏补缺',
    q: '退款流程的审批层级与金额阈值在现有需求材料中未说明。请补充：各金额区间对应的审批角色、审批时效（SLA）与超时升级规则。',
    opts: [],
    hint: '可直接粘贴制度文件原文，或分区间描述（例：1 万元以下客服主管审批，1 个工作日内……）',
  },
  {
    no: 12, kind: 'open', st: 'wait', answer: null, ref: null, from: '④ 查漏补缺',
    q: '开票需求只提到「支持开票」，未说明范围与规则。请补充：支持的发票类型（增值税专用发票 / 普通发票 / 电子发票）、税率适用场景、抬头修改规则、以及红冲流程。',
    opts: [],
    hint: '如有开票模块的 PRD 或税务合规说明，直接粘贴相关章节即可',
  },
  {
    no: 13, kind: 'choice', st: 'wait', answer: null, ref: 'A7', from: '① 规则提取',
    q: '风控实时拦截交易后，客户的申诉处理时限与误拦补偿标准是什么？',
    opts: ['24 小时内处理，误拦按手续费退还', '3 个工作日内处理，无误拦补偿', '仅有申诉入口，无时限承诺'],
  },
  {
    no: 5, kind: 'choice', st: 'answered', answer: '下单即扣（库存预占）', ref: 'A3', from: '① 规则提取',
    q: '库存扣减时机是下单、支付成功还是发货时？', opts: ['下单即扣（库存预占）', '支付成功后扣减', '发货时扣减'],
  },
  {
    no: 6, kind: 'open', st: 'answered', answer: '分三批：首批 5% 内部员工 → 第二批 20% 白名单客户 → 全量；每批观察 48 小时，错误率 > 0.5% 即回滚。', ref: null, from: '④ 查漏补缺',
    q: '新支付渠道上线的灰度发布批次与比例怎么安排？', opts: [],
    hint: '请补充灰度批次、比例、观察指标与回滚条件',
  },
  {
    no: 4, kind: 'choice', st: 'answered', answer: '自动重试 3 次，间隔递增', ref: 'A15', from: '② 冲突裁决',
    q: '支付失败后的重试策略是什么？', opts: ['自动重试 3 次，间隔递增', '仅支持手动重新支付', '不重试，直接提示失败'],
  },
  {
    no: 1, kind: 'choice', st: 'verified', answer: '放款流水号', ref: 'A1', from: '① 规则提取',
    q: '放款接口的幂等键用哪个字段？', opts: ['放款流水号', '商户订单号', '身份证号'],
  },
  {
    no: 2, kind: 'choice', st: 'verified', answer: '3 次', ref: 'A2', from: '① 规则提取',
    q: '绑卡失败后的重试上限是几次？', opts: ['3 次', '5 次', '不限制'],
  },
  {
    no: 3, kind: 'open', st: 'verified', answer: '清算文件为 CSV，UTF-8 编码，每日 05:00 生成，含流水号/金额/状态/手续费四列；文件落地后推送 MQ 通知。', ref: null, from: '④ 查漏补缺',
    q: '与银联的清算文件格式与生成时间是什么？', opts: [],
    hint: '请补充清算文件格式说明',
  },
]

defineProps<{ open: boolean }>()
defineEmits<{ close: []; toggle: [] }>()

const toast = inject<(msg: string, cls?: string) => void>('toast', () => {})

const items = ref<ClarItem[]>(MOCK.map(m => ({ ...m, opts: [...m.opts] })))
const tab = ref<'wait' | 'done' | 'all'>('wait')
const picks = ref<Record<number, number>>({})
const drafts = ref<Record<number, string>>({})
const expanded = ref<number[]>([])
const showExport = ref(false)

const stBadge: Record<string, [string, string]> = {
  wait: ['b-amber', '待问'],
  answered: ['b-blue', '已答·待实证'],
  verified: ['b-green', '已实证'],
}
const waiting = computed(() => items.value.filter(c => c.st === 'wait'))
const done = computed(() => items.value.filter(c => c.st !== 'wait'))
const shown = computed(() =>
  tab.value === 'wait' ? waiting.value : tab.value === 'done' ? done.value : items.value,
)

function toggleExpand(no: number) {
  expanded.value = expanded.value.includes(no)
    ? expanded.value.filter(n => n !== no)
    : [...expanded.value, no]
}

function answerChoice(c: ClarItem) {
  const idx = picks.value[c.no]
  if (idx === undefined) return
  c.answer = c.opts[idx]
  c.st = 'answered'
  toast(`${c.no} 已记录（口头答案=推测级）`)
}

function answerOpen(c: ClarItem) {
  const text = (drafts.value[c.no] ?? '').trim()
  if (!text) return
  c.answer = text
  c.st = 'answered'
  drafts.value[c.no] = ''
  toast(`${c.no} 材料已记录（材料答案=推测级）`)
}

function verify(c: ClarItem) {
  c.st = 'verified'
  toast(`${c.no} 已标记确认${c.ref ? ' · 关联规则已同步核过' : ''}`, 'ok')
}

const exportText = computed(() => {
  const w = waiting.value
  const choice = w.filter(c => c.kind === 'choice')
  const open = w.filter(c => c.kind === 'open')
  const lines: string[] = [`【需求确认 ×${w.length}】本批，麻烦一次性回我：`]
  if (choice.length) {
    lines.push('—— 选择题（回编号+选项字母）——')
    choice.forEach(c =>
      lines.push(`${c.no}. ${c.q}\n   ${c.opts.map((o, i) => String.fromCharCode(65 + i) + '. ' + o).join('  ')}`),
    )
  }
  if (open.length) {
    lines.push('—— 需补充材料（回编号+内容，可直接粘贴原文）——')
    open.forEach(c => lines.push(`${c.no}. ${c.q}`))
  }
  return lines.join('\n')
})
</script>

<template>
  <div class="dw2">
    <div class="dw2-hd">
      <h3>
        澄清池 <span class="src">{{ items.length }} 项 · 待问 {{ waiting.length }}</span>
        <span class="badge b-amber">示例数据</span>
      </h3>
      <div style="display: flex; align-items: center; gap: 8px">
        <button class="ghost btn-sm" type="button" @click="$emit('toggle')">⟲ 旧版</button>
        <button class="ghost" type="button" aria-label="关闭" @click="$emit('close')">✕</button>
      </div>
    </div>
    <p class="dw2-sub">
      攒一批一次问。选择题回字母，<b>补材料题</b>回文本或粘贴原文——①无依据规则、②冲突、④缺口的存疑项都汇到这里。
    </p>

    <div class="dw2-tabs">
      <button
        v-for="t in ([['wait', `待问 ${waiting.length}`], ['done', `已答 ${done.length}`], ['all', `全部 ${items.length}`]] as const)"
        :key="t[0]"
        class="tab"
        :class="{ on: tab === t[0] }"
        type="button"
        @click="tab = t[0]"
      >{{ t[1] }}</button>
      <span class="spacer" />
      <button class="btn btn-sm" type="button" :disabled="!waiting.length" @click="showExport = !showExport">
        导出提问文本（发 IM）
      </button>
    </div>

    <div class="dw2-list">
      <div v-for="c in shown" :key="c.no" class="q-card" :class="{ done: c.st !== 'wait' }">
        <template v-if="c.st === 'wait'">
          <div class="qc-hd">
            <span class="src">{{ c.no }}</span>
            <span class="badge" :class="c.kind === 'open' ? 'b-open' : 'b-gray'">
              {{ c.kind === 'open' ? '补材料' : '选择题' }}
            </span>
            <span class="badge" :class="stBadge[c.st][0]">{{ stBadge[c.st][1] }}</span>
            <span class="qc-from">{{ c.from }}<template v-if="c.ref"> · 关联 {{ c.ref }}</template></span>
          </div>
          <p class="qc-q">{{ c.q }}</p>

          <template v-if="c.kind === 'choice'">
            <div class="qc-opts" role="radiogroup" :aria-label="`问题 ${c.no} 选项`">
              <button
                v-for="(o, i) in c.opts"
                :key="i"
                class="opt"
                :class="{ on: picks[c.no] === i }"
                type="button"
                role="radio"
                :aria-checked="picks[c.no] === i"
                @click="picks[c.no] = i"
              >
                <b>{{ String.fromCharCode(65 + i) }}</b>{{ o }}
              </button>
            </div>
            <div class="qc-foot">
              <span class="qc-hint">点选项后记录，答案=推测级，需实证</span>
              <button class="btn btn-sm" type="button" :disabled="picks[c.no] === undefined" @click="answerChoice(c)">记录答案</button>
            </div>
          </template>

          <template v-else>
            <p v-if="c.hint" class="qc-hint-tip">{{ c.hint }}</p>
            <textarea
              v-model="drafts[c.no]"
              class="qc-input"
              :aria-label="`问题 ${c.no} 补充材料`"
              rows="4"
              placeholder="输入补充说明，或直接粘贴制度文件 / 会议记录原文……"
            />
            <div class="qc-foot">
              <span class="qc-hint">材料答案=推测级，需实证</span>
              <button class="btn btn-sm" type="button" :disabled="!(drafts[c.no] ?? '').trim()" @click="answerOpen(c)">提交补充</button>
            </div>
          </template>
        </template>

        <template v-else>
          <button class="qc-row" type="button" @click="toggleExpand(c.no)">
            <span class="tri" :class="{ open: expanded.includes(c.no) }">▸</span>
            <span class="src">{{ c.no }}</span>
            <span class="qc-row-q">{{ c.q }}</span>
            <span class="qc-row-a">答：{{ c.answer }}</span>
            <span class="badge" :class="stBadge[c.st][0]">{{ stBadge[c.st][1] }}</span>
          </button>
          <div v-if="expanded.includes(c.no)" class="qc-detail">
            <p class="qc-q">{{ c.q }}</p>
            <div class="qc-ans">
              <span class="badge" :class="c.kind === 'open' ? 'b-open' : 'b-gray'">
                {{ c.kind === 'open' ? '补材料' : '选择题' }}
              </span>
              <div class="qc-ans-text">{{ c.answer }}</div>
            </div>
            <div v-if="c.st === 'answered'" class="qc-foot">
              <span class="qc-hint">口头/材料答案仍是推测级，拿到书面依据后标记</span>
              <button class="btn-ok btn-sm" type="button" @click="verify(c)">标记已确认</button>
            </div>
            <p v-else class="qc-hint">{{ c.from }}<template v-if="c.ref"> · 关联规则 {{ c.ref }} 已同步核过</template></p>
          </div>
        </template>
      </div>

      <div v-if="!shown.length" class="dw2-empty">
        {{ tab === 'wait' ? '没有待问项——②冲突、④缺口、①无依据规则可转到这里' : '暂无记录' }}
      </div>
    </div>

    <div v-if="showExport" class="dw2-export">
      <div class="hd">导出预览（复制发 IM）</div>
      <div class="q-export">{{ exportText }}</div>
    </div>
  </div>
</template>

<style scoped>
.dw2 { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.dw2-hd { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.dw2-hd h3 { display: flex; align-items: center; gap: 8px; font-size: 15px; flex-wrap: wrap; }
.dw2-sub { font-size: 12px; color: var(--muted-fg); margin: 6px 0 12px; }
.dw2-tabs { display: flex; align-items: center; gap: 6px; padding-bottom: 12px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.tab { background: #fff; border: 1px solid var(--border2); color: var(--muted-fg); padding: 5px 12px; border-radius: 999px; font-size: 12px; }
.tab.on { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; }
.dw2-list { flex: 1; overflow-y: auto; padding: 12px 2px 12px 0; display: flex; flex-direction: column; gap: 10px; }

.q-card { background: #fff; border: 1px solid var(--border2); border-radius: var(--radius); padding: 12px 14px; }
.q-card.done { background: #fafbfd; }
.qc-hd { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.qc-from { font-size: 11px; color: var(--muted-fg); margin-left: auto; }
.qc-q { font-size: 13px; line-height: 1.65; margin-bottom: 10px; }
.qc-opts { display: flex; flex-direction: column; gap: 6px; }
.opt { display: flex; align-items: baseline; gap: 8px; text-align: left; background: #fff;
  border: 1px solid var(--border2); border-radius: 8px; padding: 8px 12px; font-size: 12.5px; line-height: 1.5;
  color: var(--fg); transition: border-color .15s, background .15s; }
.opt:hover { border-color: var(--secondary); background: #f8faff; }
.opt.on { border-color: var(--primary); background: var(--blue-bg); }
.opt b { flex-shrink: 0; font-family: var(--mono); font-size: 12px; color: var(--muted-fg); }
.opt.on b { color: var(--primary); }
.qc-hint-tip { font-size: 11.5px; color: var(--warn); background: var(--amber-bg); border-radius: 6px; padding: 7px 10px; margin-bottom: 8px; line-height: 1.5; }
.qc-input { width: 100%; border: 1px solid var(--border2); border-radius: 8px; padding: 9px 11px;
  font-family: inherit; font-size: 12.5px; line-height: 1.6; resize: vertical; min-height: 84px; }
.qc-input:focus { border-color: var(--secondary); }
.qc-foot { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.qc-foot .btn, .qc-foot .btn-ok { margin-left: auto; }
.qc-hint { font-size: 11.5px; color: var(--muted-fg); }

.qc-row { display: flex; align-items: center; gap: 8px; width: 100%; background: none; text-align: left;
  padding: 4px 2px; border-radius: 6px; font-size: 12.5px; min-width: 0; }
.qc-row:hover { background: var(--muted); }
.tri { color: var(--muted-fg); flex-shrink: 0; transition: transform .15s; display: inline-block; }
.tri.open { transform: rotate(90deg); }
.qc-row-q { flex: 1; min-width: 60px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--fg); }
.qc-row-a { flex-shrink: 1; max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--muted-fg); font-size: 12px; }
.qc-detail { border-top: 1px dashed var(--border); margin-top: 8px; padding-top: 10px; }
.qc-ans { display: flex; gap: 8px; align-items: flex-start; }
.qc-ans-text { font-size: 12.5px; line-height: 1.6; background: var(--muted); border-radius: 6px; padding: 8px 10px; white-space: pre-wrap; }

.b-open { background: #ffedd5; color: #c2410c; }
.dw2-empty { padding: 40px; text-align: center; color: var(--muted-fg); border: 1px dashed var(--border2); border-radius: var(--radius); }
.dw2-export { border-top: 1px solid var(--border); padding-top: 10px; }
.dw2-export .hd { font-weight: 600; font-size: 12.5px; margin-bottom: 4px; }
</style>
