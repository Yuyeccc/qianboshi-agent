## 总判断

“独立灵魂”不是把 Hermes 换成另一个 Agent 框架，也不是给 qianboshi 加一个大 Prompt。它应当是一个**可版本化、可审计、可脱离任何通用运行时执行的财经领域认知内核**：

- Hermes 降级为可选的 `Scheduler / Notification / Tool Host Adapter`；
- qianboshi 自己拥有任务编排、领域工具注册、记忆读写策略、研究方法论、决策复盘规则；
- 即使 Hermes 停掉，qianboshi 的 `worker + FastAPI + SQLite/ChromaDB + 本地文件` 仍可完成采集、分析、记忆更新、日报和推送。

真正要独立的是**状态、规则、数据所有权和运行入口**，不是模型调用地址。

---

## A. “独立灵魂”的架构含义

建议把 qianboshi 划分为四个独立模块，放在工作台后端或同一 Python monorepo 中，而不是继续藏在 Hermes 的 prompt、tool registry、memory 中。

```text
qianboshi-core/
  domain/          市场规则、分析框架、实体标准化、领域枚举
  orchestration/   任务路由、Agent 编排、工具调用预算、失败降级
  memory/          记忆写入、检索、冲突、过期、版本、审批
  evaluation/      复盘、前提校验、模式有效性、离线回测
adapters/
  hermes/          旧调度/推送兼容适配器，可移除
  sources/         B站、行情、公告、新闻、宏观
  delivery/        飞书、SSE、Email 等
```

### 领域认知层不应只是 Prompt

领域认知层建议由四类资产组成：

| 资产 | 作用 | 存储建议 |
|---|---|---|
| 分析框架 `analysis_framework` | 各市场、资产类别的研究步骤和必查变量 | SQLite JSON + Markdown 版本库 |
| 交易模式 `reasoning_pattern` | 条件→推理→行动边界→证伪→适用域 | SQLite 结构化表 |
| 记忆 `memory_item` | 用户、分析师、市场、复盘沉淀 | SQLite 为真相源，ChromaDB 为语义索引 |
| 评估记录 `evaluation_run` | 模式/观点在何时何地有效、失败原因 | SQLite 时序化记录 |

LLM 的职责是：抽取、归纳、解释、提出候选模式、按框架推理。  
LLM 不应决定：哪些记忆成为长期事实、规则何时生效、模式是否被证明有效。

核心原则是：**Prompt 是运行时说明，数据库中的结构化认知资产才是“灵魂”。**

### 独立运行入口

至少提供以下本地可执行入口：

```text
qbs ingest              # 采集与ASR后处理
qbs process-events      # 新事件入库、实体识别、前提校验
qbs research <asset>    # 独立研究
qbs morning-brief       # 盘前工作台生成
qbs memory-review       # 候选记忆/模式人工审核
qbs notify              # 发送提醒，Hermes 只是其中一个 adapter
```

初期可由 APScheduler 调这些命令；Hermes 只负责触发 `qbs ...` 或调用 API。等 qianboshi 自己调度稳定后，再切换触发权。

---

## B. 独立记忆：分层、带生命周期，不做“全量向量库”

建议采用“**事件不可变、记忆可修订、结论可过期**”的模型。SQLite 是结构化真相源，ChromaDB 只保存可检索文本及 `memory_id`，不能成为唯一记忆库。

### 1. 记忆层次

| 层 | 例子 | 写入来源 | 读取场景 |
|---|---|---|---|
| 原始证据记忆 | ASR、公告原文、新闻、行情快照 | 管道自动写入 | 所有结论下钻 |
| 情景/市场状态 | “A股锂电处于供给出清未确认阶段” | 事件聚合+人工/LLM候选 | 盘前、独立研究 |
| 分析师画像 | 某分析师偏好产业趋势、常用库存验证 | reasoning_unit + 复盘 | 多分析师对照 |
| 用户交易画像 | 偏中期、回撤容忍、常做ETF轮动 | 决策+确认 | 持仓风险、建议边界 |
| 用户交易逻辑 | “政策催化仅在估值低位且成交放量时参与” | 已验证决策模式 | 决策辅助 |
| 方法/模式库 | “供给收缩是否扭转过剩”的判断模板 | 多次复盘归纳 | 独立研究、分析师逻辑复用 |
| 历史教训 | “只看期货反弹误判现货去库” | 失败复盘 | 风险提示、反偏差检查 |

### 2. 统一数据模型

不要为每一层造完全不同的记忆机制。使用通用 `memory_item`，并由类型约束 payload：

```sql
memory_item(
  id, workspace_id, scope, memory_type,
  subject_type, subject_id, market,
  content_json, source_refs_json,
  confidence, status,
  valid_from, valid_until,
  version, supersedes_id,
  write_reason, created_by, reviewed_by,
  created_at, updated_at
)
```

关键字段：

- `scope`：`shared / analyst / workspace / user`，避免把用户私有偏好污染公共研究；
- `market`：`CN_A / HK / US / CROSS_MARKET`；
- `source_refs_json`：必须连到 `reasoning_unit`、`claim`、`source_event`、`decision` 或 `review`；
- `status`：`candidate / active / challenged / expired / retired`；
- `valid_until`：市场状态和短期判断必须过期，不能永久注入上下文；
- `supersedes_id`：不覆盖旧认知，保留修正链。

### 3. 写入与读取机制

**写入不是自动永久化。**

- 自动写入：原始证据、市场事实、决策日志、行为事件；
- LLM 生成：候选画像、候选模式、候选教训；
- 人工确认：用户交易逻辑、长期偏好、高风险模式；
- 自动升级：只有满足明确门槛的候选模式才可转 `active`。

读取使用“分层检索配额”，而不是把所有相关向量拼进上下文：

1. 当前问题的原始事实和最新市场状态；
2. 当前用户已确认的交易逻辑；
3. 当前市场、资产、期限匹配的模式；
4. 分析师历史逻辑；
5. 相关教训和反例。

每层设 token 上限、时效衰减和置信度阈值。优先最新、可验证、与当前市场域匹配的记忆。

---

## C. 学习用户交易逻辑：先“镜像”，后“建议”，最后才谈学习

最大风险是把用户某次冲动交易、被套后的解释，学习成“稳定交易逻辑”。因此不能直接根据交易行为自动改画像。

### 应采集的信号

| 信号 | 可信度 | 含义 |
|---|---:|---|
| 决策记录 | 高 | 当时假设、时间框架、买卖理由、证伪条件、信心 |
| 复盘结果 | 高 | 逻辑是否被证伪，错在事实、推理、执行还是仓位 |
| 用户显式反馈 | 高 | “这符合/不符合我的方法”“以后不要这样提示” |
| 实际持仓变化 | 中 | 真实行为，但动机未知 |
| 对话中的表达 | 低-中 | 可作为候选，不可直接固化 |
| 点击、停留、忽略提醒 | 低 | 只能用于产品排序，不能推断交易哲学 |

### 学习机制

第一阶段不要做“自动聚类后自动生效”。采用：

```text
决策/复盘/反馈
  → flash 抽取标准标签
  → 生成 candidate_user_pattern
  → 跨多笔决策聚合和冲突检测
  → 用户确认/编辑
  → active_user_pattern
  → 后续决策建议引用
  → 复盘评估是否保留、降权或废弃
```

建议的模式字段：

```json
{
  "trigger": ["政策催化", "行业估值分位低"],
  "filters": ["成交量确认", "不追高于20日均线偏离阈值"],
  "holding_horizon": "2周-3月",
  "risk_budget": "单主题最大暴露",
  "exit_rule": ["核心政策不及预期", "产业数据连续两期恶化"],
  "evidence_count": 6,
  "confirmation_state": "user_confirmed"
}
```

初期产品表达应是：“我观察到你过去 6 次决策中有此倾向，是否将其设为规则？”  
不能表达成：“你的风格就是这样。”

要区分三件事：

- **偏好**：喜欢 ETF、偏好低频；
- **约束**：最大回撤、单标的暴露、不能隔夜；
- **有效逻辑**：在特定条件下有可验证价值的判断方法。

偏好可以快速确认，约束必须用户显式设定，有效逻辑必须经复盘验证。

---

## D. 分析师交易逻辑复用：模式库优先于规则引擎或 Prompt

建议将分析师逻辑沉淀为 `reasoning_pattern`，它是“受证据约束的可复用研究模板”，不是直接抄成买卖规则。

```sql
reasoning_pattern(
  id, owner_type, owner_id,
  market, asset_class, horizon,
  trigger_json, premise_graph_json,
  confirmation_signals_json,
  invalidation_json, action_boundary_json,
  source_reasoning_ids_json,
  sample_count, win_rate, calibration_score,
  regime_tags_json, status, version
)
```

例如：

```text
模式：锂盐价格反弹不等于供需反转
适用：A股锂电链 / 商品周期 / 1-3个月
触发：期货或现货短期反弹
必须确认：库存去化、减产规模、下游补库持续性
反例：政策刺激导致需求斜率非线性上升
行动边界：未同时满足两项确认信号，仅列为观察
```

### 三种形态的分工

- **模式库**：主资产。可检索、可审计、带适用条件，第一阶段就做。
- **Prompt 资产**：把市场框架、检查清单、输出约束以版本化 Markdown 注入 Agent；它是模式的“执行说明”，不是事实来源。
- **规则引擎**：只做确定性触发，如“库存连续两周下降且期货升水扩大时，提示该模式进入确认阶段”。不要把复杂投研逻辑过早硬编码成规则树。

### 如何验证复用有效

不能用“这位分析师历史准确率高”作为唯一标准。应做**条件化评估**：

1. 每个 pattern 记录样本数、适用市场状态、观察周期、实际后验结果；
2. 衡量前提预测是否正确、证伪是否及时、置信度是否校准，而非只看涨跌；
3. 与简单基线比较，例如“只按趋势”“不使用该模式”；
4. 训练期和验证期按时间切分，禁止拿同一轮周期既提炼又验证；
5. 样本不足时状态只能是 `hypothesis`，不能作为 Agent 的强结论依据。

分析师逻辑应保留署名和来源。Agent 可以说“参考了某分析师历史上常用的供给确认框架”，不能伪装为自身已验证的普适规律。

---

## E. A股、港股、美股分域

市场分域不应只是给股票加一个 `market` 标签。它意味着**实体、事实、框架、记忆、评估口径都可能不同**。

### 数据层

`instrument` 必须有稳定主键，不能只存代码：

```text
instrument_id / symbol / exchange / market / currency /
asset_class / trading_calendar / timezone / settlement_rule /
price_limit_rule / disclosure_regime / corporate_action_rule
```

- A股：涨跌停、北向/两融、公告与政策驱动、T+1；
- 港股：港股通资金、汇率、南向、AH 溢价、流动性差异；
- 美股：财报指引、期权隐波、回购、盘前盘后、SEC 披露。

`source_event`、行情快照、宏观指标、交易日历都须有 `market`、`exchange`、`timezone`。  
跨市场主题可建立 `theme_id`，例如“AI算力”关联 A 股服务器、港股互联网、美股半导体，但不能混成同一价格和估值序列。

### 分析层

不要使用一个“六因子模板”覆盖所有市场。应有：

```text
base_framework
  + market_framework(CN_A/HK/US)
  + asset_class_framework(股票/ETF/商品/期货)
  + strategy_framework(事件/趋势/基本面/轮动)
```

例如，美股独立研究必须默认检查财报预期差、估值、期权/流动性；A 股默认检查政策、产业数据、资金和涨跌停约束。Agent 在回答开头明确“当前采用 A 股中期产业框架”，防止框架偷换。

### 记忆层

所有 `claim`、`reasoning_pattern`、`market_state` 必填 `market` 和 `horizon`。  
`CROSS_MARKET` 仅用于明确写出传导链的记忆，例如：

```text
美股半导体 Capex 上修 → 港股互联网云资本开支预期 → A股光模块订单预期
```

且每条链都需要单独的传导前提，不允许“美股涨，所以 A 股必涨”。

---

## F. 渐进迁移路线

### 第 0 步：盘点并冻结 Hermes 依赖

列出 Hermes 当前提供的调度、工具、记忆、密钥、通知、会话和日志能力，形成 `HermesAdapter` 接口。先不切流。

验收：任何 Hermes 调用都能定位到 qianboshi 的一个显式接口；不存在只藏在 Hermes 对话历史里的关键状态。

### 第 1 步：数据和认知资产归位

完成五对象模型、`source_event`、`memory_item`、`reasoning_pattern` 的 SQLite 迁移；ChromaDB metadata 加 `market/scope/status/version`。ASR、直播、旧观点回填 evidence 链路。

验收：任一结论能下钻原文；任一长期记忆能看到来源、版本、有效期和责任主体。

### 第 2 步：qianboshi-core 脱离 Hermes 可运行

将现有 Python 管道包装为独立 CLI/worker；FastAPI 作为统一研究、记忆、任务 API；Hermes 改为调用 qianboshi API 或触发 CLI。

验收：关闭 Hermes 后，手动和 APScheduler 均可完成一次“采集→ASR→证据→事件→日报→飞书/本地输出”。

### 第 3 步：候选记忆与复盘闭环

先上线决策记录、复盘、用户确认页、分析师模式候选页；不让任何候选自动成为活跃规则。

验收：至少完成 20 条用户决策或模拟历史复盘，能区分“用户确认偏好”“待验证逻辑”“已失效教训”。

### 第 4 步：分市场研究与独立分析

先选 A 股为主域，港股/美股先完成 instrument、日历、行情、框架隔离，再逐个开放研究能力。跨市场研究只先做证据化观察，不做自动因果判断。

验收：同一主题在三市场的输出会显示不同框架、数据时点和限制条件；不会发生代码、币种、交易日误用。

---

## G. 需要正视的盲点

1. **独立记忆最容易变成垃圾堆。**  
   解决不是更强 embedding，而是写入门槛、来源强制绑定、有效期、状态机、定期淘汰。没有来源和适用期的“洞见”不应进入长期记忆。

2. **用户逻辑不等于用户过去行为。**  
   行为可能受现金流、情绪、朋友消息、临时避险影响。系统只能学习可解释、用户确认、跨样本稳定的部分。

3. **“正确复盘”存在结果偏差。**  
   一个判断赚钱不代表推理正确，可能只是 beta、流动性或时间窗口帮忙。复盘必须拆成：前提是否成立、推理是否合理、仓位和执行是否匹配、收益是否超越基线。

4. **分析师模式可能刻舟求剑。**  
   同一逻辑在 A 股政策市、港股流动性市、美股财报定价市中有效性不同。模式必须绑定市场域、资产类别、周期和 regime，且允许过期。

5. **“自我成长”不能等于自动改写自己。**  
   初期应是“自动提出候选认知，人确认或离线评估后发布”。否则系统会把近期噪声写成长期人格，且难以审计回滚。

6. **不要把独立性误解为重建所有基础设施。**  
   Hermes 可继续承担非核心运维能力一段时间；关键是它不再拥有唯一调度权、唯一记忆权或唯一工具定义权。先夺回认知和状态所有权，再替换运行依赖。