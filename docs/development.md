# QuOS · 开发规范

> 本文为项目开发唯一权威文档（2026-10-12 汇总重写），含架构、环境、规范、铁律、测试与已知坑。需求内容见 `docs/requirements.md`。

## 1. 技术栈与目录

| 层 | 选型 |
|---|---|
| 前端 | Vue 3 + Vite + TypeScript + vitest（`web/`） |
| 后端 | Python FastAPI + pydantic v2 + pytest（asyncio_mode=auto，`server/`） |
| 存储 | 文件系统 + git 为真相源；MySQL 8 仅可重建元数据索引 |
| AI | LLM API 直连（OpenAI 兼容）+ dsh headless agent 引擎（可选） |

```
QuOS/
├── docs/                 # requirements.md（需求）+ development.md（本文）
├── server/
│   ├── app/
│   │   ├── api/          # router.py（需求域）/ projects.py / doubts.py / generate.py
│   │   ├── ai/           # runner.py（LLM 调用）/ tasks.py（任务编排）/ agent/（export/runner/ingest/rules）
│   │   ├── core/         # models.py（pydantic 对象，唯一数据契约）
│   │   └── storage/      # 文件读写 + gitops.py（基线）+ db.py（MySQL 索引）
│   ├── prompts/          # AI 任务 prompt 模板（git 版本化，改 prompt = 改流程）
│   ├── tests/            # pytest
│   └── data/<slug>/      # 项目数据（gitignore，文件为源）
├── web/src/              # 组件/视图/路由/api.ts
└── start.sh              # 依赖检查 → 前端构建 → 启动 8000
```

前端关键组件：Workbench.vue（布局壳）、WbTree（大纲树）、WbDetail（详情三 tab）、Landing、EvPoolModal / VerModal（head/body/foot 三段弹窗体系）。

## 2. 环境与配置

### 2.1 启动

```bash
./start.sh                    # 依赖检查 → 前端构建 → http://localhost:8000
QUOS_FAKE_AI=1 ./start.sh     # 假数据模式（无需 LLM key）
./start.sh --build            # 强制重建前端
```

### 2.2 环境变量（`.env`，不入 git）

| 变量 | 说明 |
|---|---|
| `QUOS_LLM_API_KEY / BASE_URL / MODEL` | LLM（OpenAI 兼容）；当前走本地网关 127.0.0.1:8090（deepseek-flash 多模态，网关文档 `~/Documents/Git/model-gateway/docs/对接文档.md`）；调用走 SSE 流式，`QUOS_LLM_TIMEOUT`（默认 600s）语义为 chunk 间隔超时——大材料 extract 实测 32KB 需 ~78s，勿改回整包超时 |
| `QUOS_FAKE_AI=1` | 假数据模式（`app/ai/fake.py` 固定假数据，测试/演示用） |
| `QUOS_DB_HOST/PORT/USER/PASSWORD/NAME` | MySQL 索引库；**未配置 = DB 禁用**（默认值由 start.sh 注入）；真库集成测试仅 `QUOS_DB_TEST=1` 时运行 |
| `QUOS_AGENT_ENGINE` | `dsh`（默认）\| `off`（回退 API 直连链路） |
| `QUOS_DSH_CMD` | dsh 启动命令；**未配置时引擎自动回落 off**。例：`cd ~/Documents/Git/deepseek-harness && pnpm dsh --profile headless --json` |
| `QUOS_AGENT_TIMEOUT` | 单次 agent 运行上限秒数（默认 1200），超时 kill 进程组；agent 任务目录用后清理、失败保留排障、仅留最近 20 个 |

MySQL：内网 192.168.17.216:3306，库 `quos`，账号 perftest/perftest（已建库建表，勿重复）。文件为源——库丢无损，扫目录 rebuild；不可达自动降级目录扫描。

dsh（DeepSeek Harness）：本地源码 `~/Documents/Git/deepseek-harness`，模型/认证走 dsh 自身 `$DSH_HOME` profile，与 `QUOS_LLM_*` 互不相干。

### 2.3 本机网络注意

- 系统有 HTTP 代理 `http://127.0.0.1:7897`：访问 localhost 须绕过（`--noproxy '*'` 或浏览器代理排除）；runner 对本机 base_url 已禁用系统代理（防 http_proxy 劫持）
- 端口：后端 8000；前端 dev 5173（可能被并行会话占用，冲突时注意）

## 3. 代码规范

- **行数上限**：前端组件 / 后端模块 500 行；工具函数 300 行。按职责拆不按行数拆；router.py 等历史大文件在功能改动时顺势拆分（doubts.py / generate.py / projects.py 即此产物）
- **数据模型**：`core/models.py` pydantic v2 为唯一契约；演进用默认值兜底 + 读侧归一（如旧 a/b 冲突 → parties），**零数据迁移写回**；退役字段靠 `extra=ignore` 兼容旧 json
- **API**：不破坏已有端点/请求响应结构/状态码（改动须同步评估前端与测试）；错误用 HTTP 语义（404 不存在 / 409 冲突 / 422 校验）；slug 含中文走 URL encode
- **AI 产物不信**：一切 AI 输出经服务端校验后才入库——node ∈ 树白名单、quote 必须在材料原文 substring 定位（图片豁免）、choice 必须命中选项；条目级失配降级不失败、任务级 schema 失败才失败
- **前端**：新组件中文注释；弹窗一律挂 App 顶层或 Teleport to body（见 §7 坑）；不新增依赖除非 spec 明确授权
- **注释**：只写「代码本身说不出的约束」，不写变更说明
- **UI 改动工作流**：先方案+效果图（现有产品 + mock + 开关）确认后再实现，不直接动真实组件

## 4. 产品铁律（改动前必读，回归即 bug）

1. **计数口径唯一**：总数 = 已核过 + 待处理（含冲突中参与规则 + open 冲突 + open 缺口）；树行 / tab / 标题 / chips / 行数五处同数；恒等式测试 `tests/test_badge_consistency.py` 钉死——wb ≡ doubts、Σ树+全局 ≡ stats、模块 ≡ Σ叶+自身
2. **徽章归属单一实现**：冲突 = 参与规则最深有效节点、缺口 = 绑定节点、孤儿归全局区；三端点（wb/doubts/conflicts）同源
3. **文件为源**：任何资产（材料/画像/树/基线）只存文件系统；DB/索引丢了必须可 rebuild
4. **闸门内建**：AI 产出 = 推测级，真伪由人定；自动裁决仅在 quote 校验通过时应用，否则 keep 不静默拍板
5. **需求文档面向人**：大纲树/规则等是过程产物，文档生成须净化重组；来源/置信度/验证措辞/计数等过程字段默认不进文档
6. **数据零迁移**：存量数据文件保留不读即可追溯，不做迁移写回

## 5. 测试规范

- **定向测试**：只跑与改动相关的模块测试（`python3 -m pytest tests/<file> -v` / `npx vitest run <file>`，均在 `server/`、`web/` 目录下执行）；全量仅限公共底层改动或最终验证
- **不依赖外部服务**：AI 走 `QUOS_FAKE_AI` fake 注入；agent 引擎走 fake dsh 脚本（固定产物+模拟事件流）；DB 集成测试无库自动 skip
- **恒等式/口径类改动**：必须先读懂 §4 铁律再动手，一致性测试全程绿
- **基线**（2026-10-12，commit cafcd1b）：后端 205 + 前端 87 全绿；上线前以全量回归为准
- 弹窗/滚动类测试：DOM 断言走 `document.querySelector`（Teleport to body 后组件容器内查不到）

## 6. Git 规范

- Commit 格式 `<type>：<描述>`（技术名词保留英文）；type = feat | fix | refactor | perf | style | test | docs | ci | build | chore | revert
- 大任务完成一条记录不拆细；feature 分支合并 main 用 `merge --squash`
- `.env`、`server/data/`、reports 类过程产物不入 git

## 7. 已知坑与教训（前人踩过，勿重蹈）

| # | 坑 | 规则 |
|---|---|---|
| 1 | sticky/fixed 祖先恒建层叠上下文，困住弹窗 mask 的 fixed+z-index（遮罩盖不住兄弟栏） | 弹窗一律挂 App 顶层或 Teleport to body |
| 2 | `scrollIntoView` 在 modal+body+nav 三层嵌套滚动容器不可靠（导航点击不跳） | 手动偏移计算 `scrollTo`（rect 口径，offsetTop 相对 offsetParent 会错位）；测试 mock rect 断言计算值 |
| 3 | `http_proxy` 环境变量劫持对本机 LLM 网关的请求 | runner 对本机 base_url 禁用系统代理 |
| 4 | 大材料文本 `t[:8000]` 截断 → 大纲树整域丢失（4 个功能域未进 LLM、61 条规则无归属） | 大输入聚合任务走 agent 引擎（自管上下文），不做分片截断 |
| 5 | 跳过无变更 commit → tag 挂旧 commit、时间线显示旧 message、版本说明丢失 | 存版恒建 commit（`--allow-empty`） |
| 6 | 变量复用把规则列表覆盖写进 gaps.json（load 即 ValidationError） | 存储写入前显式隔离变量，写后可 load 验证 |
| 7 | AI 归属标错/编造节点路径 | 服务端白名单校验，失配置空进未归类桶 |
| 8 | slug 含清洗字符的目录寻径落空，项目列表出「打不开也删不掉」幽灵项 | 列表扫描与端点寻径用同一 slug 合法化口径 |

## 8. 历史演进摘要（过程文档已删，脉络存档）

| 日期 | 演进 | 结果 |
|---|---|---|
| 2026-09-23 | M1 reqspec 六步流程 MVP（提事实→挑矛盾→找空白→成画像→问人→存档） | 首版闭环 + 8 项偏差清单 |
| 2026-09-24 | 项目管理：多项目首页 + MySQL 索引 + 归档/删除 | 文件为源 + 可重建索引定型 |
| 2026-09-28 | 流程重构：四字五步 + 规则挂节点（Rule.node）+ 澄清池顶栏化 | 关闭多节点 R# 污染；后被工作台范式取代 |
| 2026-09-29 | 澄清池材料级回答 P1：多模态（pypdf/Pillow）+ AI 代答人工采纳 | runner 多模态化；后被疑点直处退役 |
| 2026-10-01 | 工作台重构：文档生长范式（落地态+工作台态、generate 流水线、三弹窗、影响分析） | 五步导航删除，现交互范式定型 |
| 2026-10-08 | 存疑汇总视图 + 澄清问题类型化（confirm/choose/supply/custom） | 部分被疑点直处退役（supply/custom 落「＋新增规则」） |
| 2026-10-09 | agent 引擎化：dsh headless ATD 协议（understand/extract/verify/clar-review） | 去截断根因修复；冒烟 11 域全覆盖、quote 定位 100% |
| 2026-10-10 | 疑点直处体系：问人退役、冲突多方归组、重新生成收口 full\|smart | 当前疑点模型终态 |
| 2026-10-10 | 版本管理优化：手动 x.y.z + 回滚/废弃 + md 预览渲染；需求文档面向人重构 | v1.0.0 定稿（commit cafcd1b） |
