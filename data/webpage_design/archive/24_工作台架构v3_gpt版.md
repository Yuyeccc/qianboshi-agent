# 钱博士投研工作台：独立财经 Agent 终版架构 v3

## 0. 总体判断

钱博士不应继续作为 Hermes 上的一组 Prompt、工具和记忆，而应成为一个**独立拥有数据、状态、研究方法、计算规则和成长机制的财经领域系统**。

Hermes 降级为可选适配器，只负责：

- 触发任务；
- 托管部分工具；
- 转发通知；
- 提供兼容运行环境。

即使 Hermes 完全停止，钱博士仍应能够独立完成：

```text
采集 → 证据入库 → 事件识别 → 观点校验
→ 研究编排 → 确定性计算 → 报告生成
→ 决策记录 → 复盘 → 通知
```

v3 的核心变化有三点：

1. 从“观点摘要系统”升级为“证据与推理保真系统”；
2. 从“LLM 自由发挥”升级为“编排器 + Validator + Calc + Compliance Gate”强约束；
3. 从“分析师观点问答”升级为“分析师逻辑复用 + 多源事件校验 + 独立研究”。

---

# 1. 终版分层架构

```text
┌──────────────────────────────────────────────────────────────┐
│                       React 投研工作台                       │
│  今日工作台 │ 资产卡 │ 多空卡 │ 证据抽屉 │ 对话 │ 持仓 │ 决策 │
│  研究进度/工具轨迹/来源标注/复盘结果/飞书及导出                │
└─────────────────────────────┬────────────────────────────────┘
                              │ REST / SSE
┌─────────────────────────────▼────────────────────────────────┐
│                    FastAPI Application Layer                  │
│  Auth / Workspace / Research API / Portfolio API / Review API │
│  SSE Streaming / Quota / Audit / Export                       │
└─────────────────────────────┬────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────┐
│                 Qianboshi Orchestrator                        │
│                                                               │
│  意图分类 → 研究计划 → 阶段编排 → 工具预算 → Validator → Gate   │
│                                                               │
│  Analyst RAG Agent       Independent Analysis Agent            │
│  还原分析师推理链         多源事实与框架独立分析                │
│                                                               │
│  Portfolio Risk Agent    Decision Review Agent                 │
│  持仓暴露与风险           决策结果、前提和认知复盘               │
└──────┬──────────────────┬──────────────────┬──────────────────┘
       │                  │                  │
┌──────▼─────┐    ┌───────▼──────┐   ┌───────▼─────────────────┐
│ 领域认知内核 │    │  数据与证据层 │   │  计算与合规执行层         │
│             │    │              │   │                         │
│ analysis_   │    │ raw_asset    │   │ calc/确定性计算库         │
│ framework   │    │ transcript   │   │ calculations DAG          │
│ reasoning_  │    │ reasoning_   │   │ validator 阶段校验        │
│ pattern     │    │ unit         │   │ compliance gate            │
│ memory      │    │ claim        │   │ sandbox / hooks            │
│ market_state│    │ source_event │   │ 不合规结果拒绝交付         │
│ evaluation  │    │ evidence     │   │                         │
└──────┬──────┘    └───────┬──────┘   └──────────┬──────────────┘
       │                    │                    │
       └────────────────────▼────────────────────▼
                    SQLite + ChromaDB
       SQLite 是结构化真相源；ChromaDB 只是检索索引
       音视频、原文、运行产物存本地对象目录，后续可迁移对象存储
                              │
┌─────────────────────────────▼────────────────────────────────┐
│                       Source Adapters                         │
│ B站直播/ASR │ 行情 │ 期货 │ 新闻 │ 公告 │ 宏观 │ 财报 │ 用户输入 │
└─────────────────────────────┬────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────┐
│              Hermes Adapter / Scheduler / Delivery             │
│  可选：Hermes、APScheduler、CLI、飞书、邮件、Webhook            │
└──────────────────────────────────────────────────────────────┘
```

## 1.1 领域认知内核

领域认知内核由以下资产组成：

```text
analysis_framework   研究框架和阶段清单
reasoning_pattern    可复用的条件化推理模式
memory_item          分层记忆及生命周期
market_state         当前市场状态
evaluation_run       模式、观点和决策的评估结果
```

它们必须版本化、可审计、可过期，不能藏在 Prompt 或 Hermes 对话历史中。

LLM 的职责是：

- 抽取候选事实、观点和推理；
- 根据框架组织研究；
- 解释证据之间的关系；
- 提出候选模式和复盘结论。

LLM 不负责：

- 凭记忆生成行情、财务和估值数据；
- 直接修改事实库；
- 自动把一次判断写成长期记忆；
- 绕过计算库；
- 输出未经合规检查的交易建议。

## 1.2 数据保真层

采用五层对象模型：

```text
raw_asset
  → transcript_segment
    → reasoning_unit
      → claim
        → research_output
```

其中：

- `raw_asset`：视频、音频、新闻原文、公告原文，不可改写；
- `transcript_segment`：ASR 片段，包含时间戳、置信度和版本；
- `reasoning_unit`：完整论证单元，保留结论、前提、条件、反例和上下文；
- `claim`：原子观点，包含立场、置信度、有效期和证伪条件；
- `research_output`：日报、回答、资产卡、决策复盘等派生结果。

任何卡片结论必须可以下钻：

```text
结论 → claim → reasoning_unit → transcript_segment → 视频时间点/原始文件
```

信息压缩只能生成新版本，不能覆盖上游原文。

## 1.3 计算层

所有估值、收益率、增长率、回撤、仓位暴露和情景结果必须由确定性函数计算：

```text
LLM 选择输入和解释结果
        ↓
calc/ 执行公式
        ↓
calculations.json 保存计算 DAG
```

每个派生数字都要能回答：

```text
输入是什么？
来自哪个证据？
使用哪个函数和版本？
计算时间是什么？
输出被哪个结论引用？
```

初期至少实现：

- PE/PB/PS；
- 前瞻估值；
- CAGR；
- PE 消化年数；
- 收益率和回撤；
- 持仓市值、行业和主题暴露；
- 情景区间计算。

## 1.4 研究编排与阶段 Validator

对于“资产深研”和“独立分析”，采用强制阶段流程：

```text
profile
  → financials / operating_data
    → estimates
      → valuation
        → risk
          → report
```

每阶段产出结构化 artifact，并由 Validator 校验：

- 必填字段是否齐全；
- 证据是否存在；
- 时间点是否明确；
- 数据是否属于当前市场和标的；
- 计算是否来自 `calc/`；
- 是否有反证和证伪条件；
- 是否仍存在 `pending` 的关键事实。

阶段未通过时：

- 不能进入下一阶段；
- 研究状态标记为 `incomplete`；
- 报告只能说明“资料不足”，不能宣称完成。

这套机制借鉴 Vibe-Research，属于 v3 的执行层，而不是 Prompt 中的软性要求。

## 1.5 合规层

报告生成后必须经过独立的 `compliance_gate`。

默认禁止直接交付的内容包括：

- 建仓；
- 加仓；
- 买入/卖出；
- 目标价；
- 止损价；
- 明确的交易指令。

Gate 应处理：

- 繁简体归一；
- 零宽字符清理；
- 标点和插空格变体；
- 同义表达；
- 中英文混写；
- 硬测试探针。

系统定位为：

```text
研究、风险识别、事实核验、决策记录和复盘
```

而不是自动交易或个性化买卖建议。

## 1.6 市场分域

市场分域必须进入数据、框架、记忆和评估，而不仅是一个标签。

`instrument` 至少包含：

```text
instrument_id
symbol / exchange
market: CN_A | HK | US
asset_class
currency
trading_calendar
timezone
settlement_rule
price_limit_rule
disclosure_regime
```

不同市场使用不同研究框架：

- A 股：政策、产业链、资金、涨跌停、T+1、公告；
- 港股：港股通、南向资金、汇率、流动性、AH 溢价；
- 美股：财报、指引、预期差、估值、期权隐波、盘前盘后。

跨市场主题必须显式描述传导链，例如：

```text
美股半导体 Capex 上修
→ 港股云厂商资本开支预期
→ A 股光模块订单预期
```

每一段传导都需要独立证据和前提，禁止“美股上涨，所以 A 股相关标的必然上涨”。

## 1.7 多用户隔离

```text
User
 └── Workspace
      ├── Shared Research：公共观点、证据、消息、市场状态
      └── Private Data：持仓、决策、会话、用户记忆、复盘
```

所有私有数据必须包含：

```text
workspace_id
created_by
visibility
```

API 从 JWT 获取当前用户和工作区，Repository 层强制注入过滤条件，禁止前端传任意 `user_id` 查询。

权限初期支持：

```text
admin / beta_user / viewer
```

管理员可以管理用户和公共研究，但默认不能查看用户私有持仓和决策。

---

# 2. 与 Vibe-Research 的取舍

## 2.1 直接借鉴

以下设计已被 Vibe-Research 证明具备较强落地价值：

| 设计 | 钱博士 v3 的采用方式 |
|---|---|
| `AGENTS.md` 金融研究宪法 | 作为版本化的领域约束文档，定义数据纪律、反证要求和禁止事项 |
| 六阶段研究 SOP | 作为 Orchestrator 的真实状态机，由 Validator 强制推进 |
| 确定性 `calc/` | 所有估值和派生数据必须走函数，保存计算 DAG |
| `compliance_gate` | 作为报告交付前的独立阻断层 |
| 数据端点注册表 | 每个数据源登记市场、字段、合规等级、阶段、鉴权和更新时间 |
| 运行目录契约 | 每次研究运行产生唯一目录和 `manifest.json`、`evidence.json`、`calculations.json`、`events.jsonl`、`report.md` |
| 完整状态机 | `queued/running/incomplete/complete/failed/stale`，产物不足不得伪装完成 |
| 三层约束 | 提示层 + 执行层 + 编排层共同约束 Agent |

运行目录示例：

```text
runs/{workspace_id}/{run_id}/
  manifest.json
  raw/
  evidence.json
  calculations.json
  events.jsonl
  artifacts/
  report.md
```

## 2.2 坚持钱博士的差异化

Vibe-Research 更接近“结构化 A 股深研工作台”，钱博士必须额外保留以下能力：

1. **分析师直播观点输入**  
   B站直播、ASR、说话人、时间点、原始推理链是核心资产。

2. **五层保真模型**  
   不仅保存证据，还要保存 `reasoning_unit`，避免摘要把分析师的条件和反例抹掉。

3. **前提校验机制**  
   新行情、新闻、公告和宏观数据对旧观点输出：
   `supported / challenged / unrelated / pending`，而不是简单情绪分类。

4. **分析师逻辑模式库**  
   将分析师的条件化推理沉淀为 `reasoning_pattern`，保留署名、适用市场、适用周期和来源。

5. **独立分析 Agent**  
   对工作台没有覆盖的股票和板块，根据多源事实、市场框架和模式库完成独立研究。

6. **用户交易逻辑学习**  
   从决策和复盘中提出候选用户模式，但必须用户确认，不能根据单次行为自动固化。

7. **持仓和决策隔离**  
   Vibe-Research 没有钱博士的多用户持仓、决策记录和复盘闭环。

因此，Vibe-Research 提供的是“如何把 Agent 约束到可施工”的方法，钱博士的核心竞争力仍是：

```text
分析师推理保真
+ 多源前提校验
+ 分析师逻辑复用
+ 用户决策成长
```

---

# 3. 数据模型定稿

SQLite 作为初期唯一结构化真相源；ChromaDB 仅保存文本向量和 `record_id`，不能作为唯一数据库。

## 3.1 身份与权限

### `user`

```text
id, email, password_hash, role, status, created_at
```

### `workspace`

```text
id, owner_user_id, name, plan, status, created_at
```

### `workspace_member`

```text
workspace_id, user_id, role, joined_at
```

### `audit_log`

```text
id, workspace_id, user_id, action, resource_type, resource_id,
metadata_json, created_at
```

## 3.2 市场与数据源

### `instrument`

```text
id, symbol, name, exchange, market, asset_class,
currency, calendar, timezone, metadata_json
```

### `source_endpoint`

```text
id, source_type, provider, market, compliance_level,
stage, auth_required, rate_limit, enabled
```

### `raw_asset`

```text
id, source_type, uri, content_hash, title,
published_at, fetched_at, storage_path, metadata_json
```

### `source_event`

```text
id, raw_asset_id, event_type, market, entity_ids_json,
content, published_at, fetched_at, reliability,
dedup_key, status
```

### `market_snapshot`

```text
id, instrument_id, field, value, unit, currency,
as_of, fetched_at, source_endpoint_id, raw_ref
```

## 3.3 直播和研究证据

### `transcript_segment`

```text
id, raw_asset_id, version, speaker, start_ms, end_ms,
text, asr_confidence, correction_status
```

### `reasoning_unit`

```text
id, source_segment_ids_json, thesis, premises_json,
conditions_json, counter_arguments_json, asset_ids_json,
source_time_range_json, extraction_model, confidence
```

### `claim`

```text
id, reasoning_unit_id, subject_id, author_type, author_id,
stance, claim_type, horizon, confidence,
valid_from, valid_until, falsification_json,
status, evidence_ids_json
```

### `evidence`

```text
id, symbol, market, field, value, unit, currency,
period, as_of, source, endpoint, fetched_at, raw_ref
```

### `claim_event_check`

```text
id, claim_id, source_event_id,
relation: supported|challenged|unrelated|pending,
reason, watch_indicators_json, checked_at
```

## 3.4 认知内核与成长

### `analysis_framework`

```text
id, market, asset_class, strategy_type, version,
stages_json, required_fields_json, prompt_path, status
```

### `reasoning_pattern`

```text
id, owner_type, owner_id, market, asset_class, horizon,
trigger_json, premise_graph_json, confirmation_signals_json,
invalidation_json, action_boundary_json,
source_reasoning_ids_json, sample_count,
calibration_score, status, version
```

### `memory_item`

```text
id, workspace_id, scope, memory_type,
subject_type, subject_id, market,
content_json, source_refs_json,
confidence, status,
valid_from, valid_until, version,
supersedes_id, write_reason,
created_by, reviewed_by, created_at, updated_at
```

典型 `memory_type`：

```text
market_state
analyst_profile
user_preference
user_constraint
user_pattern
lesson
research_method
```

### `evaluation_run`

```text
id, target_type, target_id, market, horizon,
evaluation_period, baseline,
premise_score, reasoning_score, outcome_score,
calibration_score, findings_json, created_at
```

## 3.5 用户决策和输出

### `holding`

```text
id, workspace_id, instrument_id,
quantity, avg_cost, currency, as_of, source, status
```

### `decision`

```text
id, workspace_id, user_id, instrument_ids_json,
thesis, premises_json, horizon, confidence,
invalidation_json, position_context_json,
status, created_at
```

### `decision_review`

```text
id, decision_id, review_at,
premise_result, reasoning_result,
execution_result, outcome_result,
baseline_result, lessons_json, created_at
```

### `research_run`

```text
id, workspace_id, user_id, intent, market,
instrument_ids_json, framework_id,
status, started_at, completed_at,
manifest_path, error_json
```

### `research_output`

```text
id, run_id, output_type, content_json,
claim_ids_json, evidence_ids_json,
calculation_ids_json, compliance_status,
version, created_at
```

### `tool_event`

```text
id, run_id, tool_name, input_hash,
started_at, finished_at, status,
source_refs_json, output_ref, error
```

### `calculation`

```text
id, run_id, function_name, function_version,
inputs_json, outputs_json, dag_json, created_at
```

---

# 4. 施工顺序：Phase 0-3

## Phase 0：数据保真和 Hermes 依赖盘点，1-2 周

### 施工内容

- 盘点 Hermes 当前提供的调度、工具、记忆、密钥、通知、会话和日志能力；
- 保留完整 ASR JSON、时间戳和原始音视频引用；
- 新增 `reasoning_unit`、`evidence`；
- 增加 `evidence_ids` 和来源引用；
- 为每次处理生成运行目录和 `manifest.json`；
- 增加 `AGENTS.md` 金融研究宪法初版；
- 建立 `qbs` CLI：
  - `qbs ingest`
  - `qbs process-events`
  - `qbs research`
  - `qbs morning-brief`
  - `qbs notify`

### 验收标准

- 任意日报观点可定位到 `claim → reasoning_unit → ASR 时间点`；
- evidence 提取失败不阻塞既有日报链路；
- 所有 Hermes 调用均能映射到显式的 qianboshi 接口；
- 关闭 Hermes 后，能够手动执行一次核心处理流程。

**Vibe-Research 借鉴：**运行目录契约、manifest、events 审计、金融研究宪法。

## Phase 1：独立研究内核和单人工作台，2-3 周

### 施工内容

- FastAPI + React + TanStack Query；
- JWT 登录和单工作区模型；
- 今日工作台；
- 资产分析卡、多空卡、证据抽屉；
- 对话接口和 SSE 流式输出；
- `Analyst RAG Agent`；
- `Independent Analysis Agent` 初版；
- 接入行情、新闻、公告三类源；
- 建立 `source_endpoint` 注册表；
- 实现 `supported/challenged/unrelated/pending` 前提校验；
- 实现第一批 `calc/` 函数；
- 实现研究阶段 Validator；
- 实现 compliance gate。

### 验收标准

- 输入一个已有观点资产，系统可以还原分析师的结论、前提、反例和原文；
- 输入工作台未覆盖的股票，系统能够输出事实层、推理层、结论层；
- 每个数字都有证据或计算引用；
- 缺少关键数据时输出 `incomplete`，而不是补写数据；
- 报告出现禁止交易措辞时无法交付；
- 前端能查看工具轨迹，但不展示隐藏 CoT。

**Vibe-Research 借鉴：**六阶段 SOP、Validator、确定性计算库、合规 Gate、端点注册表。

## Phase 2：内测多用户、持仓和决策成长，2-3 周

### 施工内容

- 邀请码、角色和配额；
- workspace 级数据隔离；
- 持仓录入和持仓联动研究；
- `Portfolio Risk Agent`；
- 决策记录：判断、理由、信心度、时间周期、证伪条件；
- `Decision Review Agent`；
- 观点被挑战和证伪条件触发提醒；
- 分析师 `reasoning_pattern` 候选生成；
- 用户 `candidate_user_pattern` 生成和确认；
- 飞书通知适配器独立化；
- 登录、导出、私有数据访问、Agent 调用审计。

### 验收标准

- 用户只能看到自己的持仓、决策、会话和私有记忆；
- 公共研究可以复用，但不会污染用户私有认知；
- 用户逻辑必须经过确认才能进入 `active`；
- 一次复盘能够区分事实错误、推理错误、执行错误和运气因素；
- Hermes 停止时，内测用户仍能完成研究、记录和复盘。

## Phase 3：分市场、模式评估和商业化接口

### 施工内容

- 完成 A 股、港股、美股的 instrument、交易日历、币种和数据源隔离；
- 为不同市场绑定独立框架；
- `reasoning_pattern` 条件化评估和时间切分验证；
- 市场状态 `market_state`；
- 报告 Markdown/PDF 导出；
- 历史观点和决策评估；
- 工作区配额、模型额度和数据源权限；
- OpenAPI / MCP Server；
- SQLite → PostgreSQL、ChromaDB → pgvector 的可选迁移。

### 验收标准

- 同一主题在 A 股、港股、美股使用不同框架和数据口径；
- 模式能显示适用市场、周期、样本数、基线和校准结果；
- 样本不足的模式只能标记为 `hypothesis`；
- 迁移 Repository 接口不改变上层业务代码；
- Hermes 完全可替换，不拥有唯一调度、记忆和工具定义权。

---

# 5. 架构的“灵魂”

**钱博士的灵魂，是一套拥有原始证据、条件化推理、确定性计算、可验证前提和可复盘记忆的财经认知内核；Hermes 可以替换，模型可以替换，但这套认知资产和成长闭环不能被替换。**