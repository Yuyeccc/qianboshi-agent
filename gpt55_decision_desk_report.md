# gpt-5.5 架构设计报告
生成时间: 2026-08-04T22:55:55.622600
提示词: decision_desk_architecture_prompt.md

# 钱博士Agent「投研决策台」增量架构设计方案

## 0. 核心结论

现有系统已经完成了“内容采集→转写→结构化观点→日报/简报”的链路，但它目前的主要产物仍是“财经内容摘要”。  
本次升级不应重造采集、转写、RAG、日报系统，而是在现有四层之上增加三类能力：

1. **信息对照层**：围绕资产/板块生成“多空对照卡”，把多头、空头、分歧、共识、新变化摆清楚。
2. **推理框架层**：围绕资产生成“分析卡”，把驱动因素、因素状态、影响方向、历史有效性串成逻辑链。
3. **决策复盘层**：记录用户判断、分析师观点验证、分析卡版本演进，形成长期学习闭环。

系统仍然不输出买卖信号，不自动交易，只做：

> 信息对照、重点标注、推理辅助、长期复盘。

---

# 1. 总体架构

## 1.1 问题现状

现有架构：

```text
采集层 → 转写层 → 知识层 → 产出层
```

已经具备：

- 853篇结构化笔记；
- 9483个向量chunks；
- 1070条 structured_views；
- 观点库 view_store；
- latest_digest；
- 行情数据 market_data_sources；
- 日报/简报生成能力；
- validate.py 回测雏形。

但目前缺少三类中间决策资产：

1. **按资产聚合的多空结构**：现在是一条条观点，缺少“同一资产下的多空对照”。
2. **资产推理框架**：现在可以问“黄金有什么观点”，但系统不知道“黄金应该看哪些驱动因素”。
3. **复盘闭环**：现有 validate.py 只是雏形，尚未把“分析师正误、用户判断、分析卡修正”沉淀成长期资产。

---

## 1.2 根因

根因不是 LLM 不够强，也不是 embedding 不准，而是当前系统缺少以下三类结构化对象：

| 缺失对象 | 作用 |
|---|---|
| `DebateCard` 多空对照卡 | 把同资产、同周期的观点归并为多头/空头/共识/分歧 |
| `AssetAnalysisCard` 资产分析卡 | 定义某资产应该看哪些因素，以及每个因素如何影响资产 |
| `DecisionLog / ReviewReport` 决策与复盘数据 | 记录用户判断、后续结果、漏看因素、认知修正 |

所以升级重点不是“再做一个聊天机器人”，而是增加决策台的数据结构和确定性管线。

---

## 1.3 总体方案

在现有四层之上，新增三层：

```text
现有：
采集层 → 转写层 → 知识层 → 产出层

新增：
证据加工层 → 决策资产层 → 交互呈现层
```

### 新架构图

```text
┌────────────────────────────────────────────────────────────┐
│                         采集层                              │
│ monitor_bilibili.py  六源监控 / cron 22:00                  │
└───────────────────────┬────────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────────┐
│                         转写层                              │
│ batch_transcribe_gpu.py / ASR纠错 / transcribe_to_note.py    │
│ Obsidian结构化笔记                                           │
└───────────────────────┬────────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────────┐
│                         知识层                              │
│ structured_views.jsonl  观点库                               │
│ Chroma chunks           证据补充                              │
│ entity_aliases.yaml     实体归一                              │
│ latest_digest.py        近期观点摘要                          │
│ market_data_sources.py  行情事实层                            │
└───────────────────────┬────────────────────────────────────┘
                        │
                        │ 新增
┌───────────────────────▼────────────────────────────────────┐
│                     证据加工层 Evidence Layer                │
│ 1. view_clusterer.py        观点聚类                          │
│ 2. debate_detector.py       多空/分歧/共识检测                 │
│ 3. prediction_event_builder.py 观点事件化                     │
│ 4. outcome_updater.py       市场结果回填                       │
│ 5. analyst_score_builder.py 分析师准确率统计                  │
└───────────────────────┬────────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────────┐
│                     决策资产层 Decision Asset Layer           │
│ SQLite: qianboshi_decision.db                                │
│ - debate_cards                                                 │
│ - asset_cards / asset_card_versions                            │
│ - factor_configs / factor_states                               │
│ - user_decision_logs                                           │
│ - decision_reviews                                             │
│ - prediction_events / market_outcomes / analyst_scores         │
└───────────────────────┬────────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────────┐
│                     推理编排层 Reasoning Orchestrator         │
│ 1. factor_state_refresher.py                                  │
│ 2. asset_card_builder.py                                      │
│ 3. debate_card_builder.py                                     │
│ 4. decision_review_generator.py                               │
│ 5. evidence_pack_builder.py                                   │
└───────────────────────┬────────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────────┐
│                         产出/交互层                          │
│ 短期：brief_renderer.py 增加多空对照卡/资产分析卡 Markdown区块 │
│ 中期：Feishu/Studio Chat 工具调用                              │
│ 后期：Next.js/shadcn-admin 独立浏览界面                        │
└────────────────────────────────────────────────────────────┘
```

---

## 1.4 新增模块清单

| 模块 | 类型 | 作用 |
|---|---|---|
| `decision_db.py` | 新增 | SQLite建表、读写封装 |
| `view_clusterer.py` | 新增 | 同资产、同周期观点语义聚类 |
| `debate_card_builder.py` | 新增 | 生成多空对照卡 |
| `factor_config.yaml` | 新增 | 可编辑资产驱动因素配置 |
| `factor_state_refresher.py` | 新增 | 刷新因素状态 |
| `asset_card_builder.py` | 新增 | 生成资产分析卡 |
| `decision_logger.py` | 新增 | 用户决策日志记录 |
| `decision_reviewer.py` | 新增 | 用户决策结果回填与复盘 |
| `prediction_event_builder.py` | 新增/改造validate.py | 把观点事件化 |
| `outcome_updater.py` | 新增/改造validate.py | 回填1/3/5/10/20日收益 |
| `analyst_score_builder.py` | 新增 | 分析师历史准确率统计 |
| `evidence_pack_builder.py` | 新增 | 统一拼装观点、行情、回测、证据链 |
| `brief_renderer.py` | 改造 | 增加卡片Markdown渲染 |
| `tool_registry.py` | 改造 | 注册新工具 |

---

## 1.5 预期收益

| 能力 | 升级前 | 升级后 |
|---|---|---|
| 看观点 | 按时间摘要 | 按资产聚合多空对照 |
| 看分歧 | 靠人工读 | 自动标出强分歧、共识、新变化 |
| 看资产逻辑 | 临时问RAG | 固定资产分析卡，驱动因素可维护 |
| 看分析师可信度 | 没有体系 | 按分析师/实体/周期显示历史命中率 |
| 用户复盘 | 分散在笔记里 | 决策日志、结果回填、认知修正版本化 |
| 日报价值 | 信息摘要 | 决策辅助面板 |

---

## 1.6 工作量估算

| 阶段 | 工作量 |
|---|---|
| SQLite基础库 + 多空对照卡MVP | 1-2天 |
| 分析师回测库MVP | 3-5天 |
| 资产分析卡配置 + 因素刷新 | 3-5天 |
| 用户决策日志 + 复盘 | 3-5天 |
| EvidencePack统一证据包 | 2-4天 |
| Feishu/Studio Chat接入 | 3-7天 |
| 独立Web界面 | 2-4周 |

---

# 2. 数据模型设计

建议新增 SQLite：

```text
E:\qianboshi-agent\data\qianboshi_decision.db
```

保留：

```text
structured_views.jsonl
entity_aliases.yaml
market_cache/
```

SQLite 负责“决策资产和复盘闭环”；JSONL继续作为原始观点事实来源。

---

# 2.1 多空对照卡 DebateCard

## 问题现状

structured_views 中每条观点是独立的，字段已经很好，但缺少“同一资产下的观点聚合”。

## 根因

没有以 `entity + horizon + date_window` 为主键的中间聚合对象。

## 具体方案

新增两张表：

1. `debate_cards`：卡片主表；
2. `debate_card_items`：卡片中的观点条目。

### 表：`debate_cards`

```sql
CREATE TABLE IF NOT EXISTS debate_cards (
    card_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,          -- stock / sector / etf / theme / macro
    horizon TEXT NOT NULL,              -- intraday / short / medium / long
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,

    bullish_count INTEGER DEFAULT 0,
    bearish_count INTEGER DEFAULT 0,
    neutral_count INTEGER DEFAULT 0,
    risk_count INTEGER DEFAULT 0,
    watch_count INTEGER DEFAULT 0,

    consensus_direction TEXT,           -- bullish / bearish / neutral / mixed
    disagreement_level REAL,            -- 0-1
    confidence_level REAL,              -- 0-1
    novelty_level REAL,                 -- 0-1

    highlight_tags TEXT,                -- JSON array: ["高置信", "强分歧", "新变化"]
    summary TEXT,                       -- LLM生成或规则模板生成
    created_at TEXT,
    updated_at TEXT
);
```

### 表：`debate_card_items`

```sql
CREATE TABLE IF NOT EXISTS debate_card_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL,
    view_id TEXT NOT NULL,
    stance TEXT NOT NULL,
    analyst TEXT,
    date TEXT,
    claim TEXT,
    logic TEXT,
    risk TEXT,
    evidence TEXT,
    confidence REAL,
    cluster_id TEXT,
    cluster_label TEXT,
    analyst_score_snapshot REAL,
    source_file TEXT,
    FOREIGN KEY(card_id) REFERENCES debate_cards(card_id)
);
```

### 兼容 structured_views

`debate_card_items.view_id` 必须回指：

```json
{
  "view_id": "20260721_xxx_0001",
  "source_file": "xxx.md",
  "date": "2026-07-21",
  "analyst": "钱博士",
  "entities": {
    "sectors": ["黄金"],
    "stocks": [],
    "etfs": ["黄金ETF"],
    "themes": ["避险"]
  },
  "stance": "bullish",
  "horizon": "medium",
  "claim": "黄金中期仍有支撑",
  "logic": "美元走弱和央行购金支撑金价",
  "risk": "美元重新走强会压制黄金",
  "evidence": "原文引用..."
}
```

### JSON 输出示例

```json
{
  "card_id": "debate_黄金_medium_2026-07-20_2026-08-04",
  "entity_id": "黄金",
  "entity_name": "黄金",
  "entity_type": "sector",
  "horizon": "medium",
  "window": {
    "start": "2026-07-20",
    "end": "2026-08-04"
  },
  "highlights": ["强分歧", "新变化"],
  "bullish": [
    {
      "view_id": "v_001",
      "analyst": "钱博士",
      "claim": "美元见顶后黄金仍有上行空间",
      "logic": "美元走弱、实际利率回落、央行购金",
      "confidence": 0.82,
      "analyst_score": 0.61,
      "evidence": "原文引用..."
    }
  ],
  "bearish": [
    {
      "view_id": "v_002",
      "analyst": "趋势天哥",
      "claim": "黄金短期有回调压力",
      "logic": "避险情绪退潮，美元反弹",
      "confidence": 0.76,
      "analyst_score": 0.55,
      "evidence": "原文引用..."
    }
  ],
  "disagreements": [
    {
      "topic": "美元是否已见顶",
      "bullish_side": ["钱博士"],
      "bearish_side": ["趋势天哥"]
    }
  ],
  "consensus": [
    "多数观点都认为美元走势是黄金判断的核心变量"
  ],
  "new_changes": [
    "近7天新增观点开始强调实际利率回落"
  ]
}
```

## 预期收益

- 日报不再只是“谁说了什么”，而是“同一资产现在多空怎么打架”。
- 用户能快速看到高置信、强分歧、新变化。
- 后续可直接接入聊天问答和Web页面。

## 工作量

- SQLite表：0.5天；
- 从 structured_views 聚合生成卡片：1天；
- Markdown渲染：0.5天；
- 合计：1-2天可见效。

---

# 2.2 资产分析卡 AssetAnalysisCard

## 问题现状

系统不知道“黄金应该看美元、美债实际利率、地缘风险、央行购金”等驱动因素。  
每次问答都依赖临时检索，无法形成稳定的用户认知框架。

## 根因

缺少资产级别的、可编辑的“驱动因素配置”。

## 具体方案

使用“配置文件 + SQLite版本表”的双层结构。

- `configs/asset_cards/gold.yaml`：用户可编辑的资产分析卡配置；
- SQLite `asset_cards` 和 `asset_card_versions`：保存版本化记录；
- `factor_states`：保存每次刷新后的因素状态。

---

## 配置文件示例：`configs/asset_cards/gold.yaml`

```yaml
asset_id: GOLD
asset_name: 黄金
asset_type: commodity
default_horizon: medium
version: 1
description: 黄金中期趋势分析框架

factors:
  - factor_id: DXY
    factor_name: 美元指数
    category: macro
    data_binding:
      type: market
      symbol: "DX-Y.NYB"
      source: "yfinance"
      fields: ["close", "pct_change_5d", "pct_change_20d"]
    impact_rule:
      relation: negative
      description: 美元走强通常压制黄金，美元走弱通常利好黄金
      strength: high
      conditional_note: "在全球避险共振时，美元和黄金可能同涨"
    refresh_policy:
      mode: scheduled
      frequency: daily

  - factor_id: US_REAL_YIELD
    factor_name: 美债实际利率
    category: macro
    data_binding:
      type: market
      symbol: "DFII10"
      source: "fred_or_manual"
      fields: ["close", "change_5d", "change_20d"]
    impact_rule:
      relation: negative
      description: 实际利率上行压制无息资产黄金，实际利率下行利好黄金
      strength: high

  - factor_id: GEOPOLITICAL_RISK
    factor_name: 地缘风险
    category: event
    data_binding:
      type: view_query
      query_terms: ["地缘", "战争", "中东", "避险", "冲突"]
      view_types: ["risk", "event", "market"]
      lookback_days: 14
    impact_rule:
      relation: positive
      description: 地缘风险升温通常强化黄金避险需求
      strength: medium

  - factor_id: CENTRAL_BANK_BUYING
    factor_name: 央行购金
    category: fundamental
    data_binding:
      type: view_query
      query_terms: ["央行购金", "黄金储备", "去美元化"]
      view_types: ["framework", "market", "sector"]
      lookback_days: 60
    impact_rule:
      relation: positive
      description: 央行购金构成黄金中长期配置支撑
      strength: high
```

---

## 表：`asset_cards`

```sql
CREATE TABLE IF NOT EXISTS asset_cards (
    asset_id TEXT PRIMARY KEY,
    asset_name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    current_version INTEGER NOT NULL,
    default_horizon TEXT,
    description TEXT,
    config_path TEXT,
    created_at TEXT,
    updated_at TEXT
);
```

---

## 表：`asset_card_versions`

```sql
CREATE TABLE IF NOT EXISTS asset_card_versions (
    version_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    change_reason TEXT,
    changed_by TEXT,                    -- user / system
    linked_review_id TEXT,              -- 来自哪次复盘
    created_at TEXT,
    FOREIGN KEY(asset_id) REFERENCES asset_cards(asset_id)
);
```

---

## 表：`factor_states`

```sql
CREATE TABLE IF NOT EXISTS factor_states (
    state_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    card_version INTEGER NOT NULL,
    factor_id TEXT NOT NULL,
    factor_name TEXT NOT NULL,

    as_of_date TEXT NOT NULL,
    raw_value TEXT,                     -- JSON
    current_state TEXT,                 -- 强/弱/高位/低位/升温/降温/无明显变化
    change_direction TEXT,              -- up / down / flat / unknown
    impact_direction TEXT,              -- positive / negative / neutral / mixed
    impact_strength TEXT,               -- high / medium / low
    confidence REAL,

    evidence_refs TEXT,                 -- JSON array: view_id / source / market snapshot
    summary TEXT,
    created_at TEXT
);
```

---

## 因素状态输出示例

```json
{
  "asset_id": "GOLD",
  "asset_name": "黄金",
  "version": 1,
  "as_of_date": "2026-08-04",
  "factors": [
    {
      "factor_id": "DXY",
      "factor_name": "美元指数",
      "current_state": "近5日走弱",
      "change_direction": "down",
      "impact_direction": "positive",
      "impact_strength": "high",
      "raw_value": {
        "close": 101.2,
        "pct_change_5d": -1.1,
        "pct_change_20d": -2.4
      },
      "summary": "美元指数近5日走弱，对黄金构成正向影响。"
    },
    {
      "factor_id": "GEOPOLITICAL_RISK",
      "factor_name": "地缘风险",
      "current_state": "观点热度上升",
      "change_direction": "up",
      "impact_direction": "positive",
      "impact_strength": "medium",
      "evidence_refs": ["view_20260801_003", "view_20260803_008"],
      "summary": "近14天多位分析师提到避险和地缘冲突，地缘风险因素偏正向。"
    }
  ],
  "logic_chain_summary": "当前黄金的主要正向驱动来自美元走弱和地缘风险升温，负向因素暂不明显，但需关注美元反弹风险。"
}
```

## 预期收益

- 用户点名“黄金现在怎么看”时，系统不再只堆观点，而是按固定框架输出。
- 用户可以修改框架，形成自己的投研认知资产。
- 复盘后可以更新卡片版本，沉淀“我以前为什么错，现在怎么改”。

## 工作量

| 功能 | 工期 |
|---|---|
| YAML配置结构 | 0.5天 |
| SQLite版本表 | 0.5天 |
| 行情型因素刷新 | 1天 |
| 观点型因素刷新 | 1天 |
| 分析卡Markdown渲染 | 1天 |
| 合计 | 3-4天 |

---

# 2.3 用户决策日志 UserDecisionLog

## 问题现状

用户的真实判断没有结构化记录。  
即使用户事后知道自己看对/看错，也很难追溯当时依据是什么。

## 根因

没有“决策时点快照”。

## 具体方案

新增三张表：

1. `user_decision_logs`：用户当时判断；
2. `user_decision_evidence`：当时引用了哪些观点/行情/因素；
3. `decision_reviews`：事后复盘结果。

---

## 表：`user_decision_logs`

```sql
CREATE TABLE IF NOT EXISTS user_decision_logs (
    decision_id TEXT PRIMARY KEY,
    user_id TEXT DEFAULT 'default',
    asset_id TEXT NOT NULL,
    asset_name TEXT NOT NULL,
    asset_type TEXT,

    decision_date TEXT NOT NULL,
    horizon TEXT NOT NULL,               -- short / medium / long
    direction TEXT NOT NULL,             -- bullish / bearish / neutral / watch
    conviction REAL,                     -- 0-1 用户主观信心

    thesis TEXT NOT NULL,                -- 我看好黄金，因为...
    key_reasons TEXT,                    -- JSON array
    invalidation_conditions TEXT,         -- JSON array，什么情况说明我错了
    action_note TEXT,                    -- 可选：不是交易指令，只记录想法

    asset_card_version INTEGER,
    debate_card_id TEXT,
    market_snapshot TEXT,                -- JSON，当时价格、涨跌幅等

    status TEXT DEFAULT 'open',           -- open / reviewed / archived
    created_at TEXT,
    updated_at TEXT
);
```

---

## 表：`user_decision_evidence`

```sql
CREATE TABLE IF NOT EXISTS user_decision_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,          -- view / factor_state / market / note
    evidence_id TEXT,
    title TEXT,
    content TEXT,
    source_ref TEXT,
    created_at TEXT,
    FOREIGN KEY(decision_id) REFERENCES user_decision_logs(decision_id)
);
```

---

## 表：`decision_reviews`

```sql
CREATE TABLE IF NOT EXISTS decision_reviews (
    review_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,

    review_date TEXT NOT NULL,
    horizon_days INTEGER,
    outcome_return REAL,
    benchmark_return REAL,
    excess_return REAL,
    max_drawdown REAL,

    result_label TEXT,                    -- right / wrong / mixed / too_early
    what_went_right TEXT,
    what_went_wrong TEXT,
    missed_factors TEXT,                  -- JSON array
    over_weighted_factors TEXT,           -- JSON array
    new_rule_learned TEXT,

    suggest_asset_card_update INTEGER DEFAULT 0,
    linked_new_card_version TEXT,

    created_at TEXT,
    FOREIGN KEY(decision_id) REFERENCES user_decision_logs(decision_id)
);
```

---

## 决策日志 JSON 示例

```json
{
  "decision_id": "dec_20260804_GOLD_001",
  "asset_id": "GOLD",
  "asset_name": "黄金",
  "decision_date": "2026-08-04",
  "horizon": "medium",
  "direction": "bullish",
  "conviction": 0.72,
  "thesis": "我看好黄金，因为美元指数见顶回落，同时央行购金逻辑仍在。",
  "key_reasons": [
    "美元指数近20日走弱",
    "多位分析师继续强调央行购金",
    "地缘风险仍然存在"
  ],
  "invalidation_conditions": [
    "美元指数重新突破前高",
    "实际利率持续上行",
    "黄金跌破关键支撑且观点端转空"
  ],
  "asset_card_version": 1,
  "debate_card_id": "debate_黄金_medium_2026-07-20_2026-08-04",
  "evidence": [
    {
      "type": "factor_state",
      "id": "state_GOLD_DXY_20260804"
    },
    {
      "type": "view",
      "id": "view_20260803_008"
    }
  ]
}
```

## 预期收益

- 以后复盘不是凭感觉，而是能回看“当时为什么这么想”。
- 错误会变成可沉淀的规则，而不是情绪损失。
- 分析卡版本化有依据，不是拍脑袋改框架。

## 工作量

- 表设计和记录接口：1天；
- 命令行或Markdown输入模板：0.5天；
- 回填市场结果：1天；
- 复盘报告生成：1-2天；
- 合计：3-5天。

---

# 2.4 分析师历史准确率 AnalystScore

## 问题现状

现有观点有 analyst 字段，但没有系统化验证。

## 根因

缺少将 `view_id` 转换为可验证事件的结构，也缺少市场结果表。

## 具体方案

延续前次审计结论，新增三张表：

1. `prediction_events`
2. `market_outcomes`
3. `analyst_scores`

---

## 表：`prediction_events`

```sql
CREATE TABLE IF NOT EXISTS prediction_events (
    event_id TEXT PRIMARY KEY,
    view_id TEXT NOT NULL UNIQUE,

    analyst TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,

    view_date TEXT NOT NULL,
    stance TEXT NOT NULL,                -- bullish / bearish / neutral / risk / watch
    horizon TEXT NOT NULL,
    view_type TEXT,

    claim TEXT,
    logic TEXT,
    risk TEXT,
    confidence REAL,
    source_file TEXT,
    evidence TEXT,

    benchmark_id TEXT,                   -- 例如沪深300、纳指、黄金ETF等
    target_symbol TEXT,                  -- 可拉行情的symbol
    validation_status TEXT DEFAULT 'pending',
    created_at TEXT
);
```

---

## 表：`market_outcomes`

```sql
CREATE TABLE IF NOT EXISTS market_outcomes (
    outcome_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,

    horizon_days INTEGER NOT NULL,        -- 1 / 3 / 5 / 10 / 20
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,

    start_price REAL,
    end_price REAL,
    asset_return REAL,
    benchmark_return REAL,
    excess_return REAL,
    max_drawdown REAL,
    max_runup REAL,

    direction_hit INTEGER,                -- 1命中，0未命中，NULL不可判断
    outcome_label TEXT,                   -- hit / miss / neutral / no_data
    created_at TEXT,

    FOREIGN KEY(event_id) REFERENCES prediction_events(event_id)
);
```

---

## 表：`analyst_scores`

```sql
CREATE TABLE IF NOT EXISTS analyst_scores (
    score_id TEXT PRIMARY KEY,
    analyst TEXT NOT NULL,
    entity_id TEXT,
    entity_type TEXT,
    horizon TEXT,
    view_type TEXT,

    sample_size INTEGER,
    hit_rate REAL,
    avg_excess_return REAL,
    avg_max_drawdown REAL,
    bullish_hit_rate REAL,
    bearish_hit_rate REAL,

    score REAL,                           -- 综合可信度 0-1
    confidence_level TEXT,                -- low / medium / high，取决于样本量
    start_date TEXT,
    end_date TEXT,
    updated_at TEXT
);
```

---

## 命中规则建议

必须确定性，不交给 LLM。

```python
if stance == "bullish":
    direction_hit = asset_return > 0
elif stance == "bearish":
    direction_hit = asset_return < 0
elif stance == "risk":
    direction_hit = max_drawdown < -threshold
elif stance == "neutral":
    direction_hit = abs(asset_return) < neutral_threshold
else:
    direction_hit = None
```

超额收益：

```python
excess_return = asset_return - benchmark_return
```

综合分：

```python
score = 0.5 * hit_rate + 0.3 * normalized_avg_excess + 0.2 * drawdown_control
```

样本量不足时降权：

```python
if sample_size < 5:
    confidence_level = "low"
    display_note = "样本不足，仅供参考"
```

## 预期收益

- 对照卡中可以显示：“该分析师过去在黄金中期观点上样本12次，命中率58%，仅供参考。”
- 不是迷信分析师，而是把历史证据摆出来。
- 形成 EvidenceChain 的基础。

## 工作量

- 从 structured_views 生成 prediction_events：1天；
- 行情结果回填：1-2天；
- 分析师分组统计：1天；
- 渲染进对照卡：0.5天；
- 合计：3-5天。

---

# 3. 模块设计

---

# 3.1 观点聚类与分歧检测模块

## 模块名

```text
view_clusterer.py
debate_detector.py
debate_card_builder.py
```

## 问题现状

同一个资产下，可能有几十条观点。  
现在只能按时间或相关性列出来，不能判断：

- 哪些观点本质相同；
- 哪些观点互相冲突；
- 是否形成强共识；
- 是否出现方向翻转。

## 根因

缺少 `entity + horizon + stance + claim_cluster` 层面的聚合。

---

## 具体方案

### 输入

```python
build_debate_card(
    entity="黄金",
    horizon="medium",
    lookback_days=14,
    min_confidence=0.4
)
```

从 `view_store.query_views()` 获取观点：

```python
views = query_views(
    entity="黄金",
    horizon="medium",
    date_start="2026-07-21",
    date_end="2026-08-04"
)
```

---

## 处理流程

```text
1. 实体归一
2. 日期过滤
3. horizon过滤
4. stance分桶
5. claim语义聚类
6. 计算多空比例
7. 检测强分歧
8. 检测共识点
9. 检测新变化
10. 生成 DebateCard
```

---

## 关键算法

### 1）stance分桶，确定性

```python
bullish = [v for v in views if v["stance"] == "bullish"]
bearish = [v for v in views if v["stance"] == "bearish"]
risk = [v for v in views if v["stance"] == "risk"]
neutral = [v for v in views if v["stance"] == "neutral"]
watch = [v for v in views if v["stance"] == "watch"]
```

---

### 2）claim语义聚类

第一版不必引入复杂算法，可以用“LLM小批量标签 + 缓存”。

输入给 LLM 的不是全文，而是：

```json
[
  {
    "view_id": "v001",
    "stance": "bullish",
    "claim": "黄金受美元走弱支撑",
    "logic": "美元指数回落，实际利率下行"
  },
  {
    "view_id": "v002",
    "stance": "bullish",
    "claim": "黄金中期仍有支撑",
    "logic": "央行购金和美元走弱"
  }
]
```

输出：

```json
{
  "clusters": [
    {
      "cluster_id": "gold_usd_weakness",
      "cluster_label": "美元走弱支撑黄金",
      "view_ids": ["v001", "v002"],
      "stance": "bullish"
    }
  ]
}
```

为了节省成本，缓存到：

```sql
CREATE TABLE IF NOT EXISTS view_clusters (
    cluster_id TEXT,
    entity_id TEXT,
    horizon TEXT,
    view_id TEXT,
    cluster_label TEXT,
    stance TEXT,
    created_at TEXT,
    PRIMARY KEY(cluster_id, view_id)
);
```

---

### 3）分歧度计算

```python
total = len(views)
bull_ratio = len(bullish) / total
bear_ratio = len(bearish) / total

disagreement_level = min(bull_ratio, bear_ratio) * 2
```

例如：

| 多头 | 空头 | 分歧度 |
|---|---|---|
| 8 | 1 | 0.22 |
| 5 | 5 | 1.00 |
| 6 | 4 | 0.80 |

强分歧规则：

```python
strong_disagreement = (
    len(bullish) >= 2 and
    len(bearish) >= 2 and
    disagreement_level >= 0.6
)
```

---

### 4）高置信判断检测

```python
high_conf_views = [
    v for v in views
    if v["confidence"] >= 0.75
    and len(v.get("logic", "")) >= 30
    and len(v.get("evidence", "")) >= 40
]
```

也可以叠加分析师历史分：

```python
adjusted_confidence = (
    0.7 * view_confidence +
    0.3 * analyst_score
)
```

---

### 5）新变化检测

包括两种：

#### A. 方向翻转

比较最近窗口和前一窗口：

```text
当前窗口：最近7天
前一窗口：8-21天前
```

计算净方向：

```python
net_stance_score = (
    bullish_count - bearish_count - risk_count * 0.5
) / total
```

若符号翻转：

```python
if previous_score < -0.2 and current_score > 0.2:
    tag = "由空转多"
elif previous_score > 0.2 and current_score < -0.2:
    tag = "由多转空"
```

#### B. 新证据出现

最近N天出现过去30天没出现过的 cluster_label：

```python
new_clusters = current_clusters - previous_clusters
```

---

## 输出接口

```python
def build_debate_card(entity: str, horizon: str, lookback_days: int = 14) -> DebateCard:
    ...
```

返回：

```python
{
    "card_id": "...",
    "entity_name": "黄金",
    "highlights": ["强分歧", "新变化"],
    "bullish_arguments": [...],
    "bearish_arguments": [...],
    "disagreements": [...],
    "consensus": [...],
    "source_view_ids": [...]
}
```

## LLM参与边界

| 环节 | 是否LLM |
|---|---|
| 日期过滤 | 否 |
| 实体归一 | 否 |
| stance分桶 | 否 |
| 分歧度计算 | 否 |
| 新变化检测 | 否 |
| claim聚类标签 | 可用LLM |
| 自然语言摘要 | 可用LLM |
| 证据引用校验 | 否 |

## 预期收益

- 第一版就能把“观点打架”显性化。
- 便于日报中突出强分歧和新变化。
- 成本低，因为只对少量 claim 做聚类，不处理长文本。

## 工作量

2-3天完整，MVP 1天。

---

# 3.2 因素状态刷新模块

## 模块名

```text
factor_state_refresher.py
asset_card_builder.py
```

## 问题现状

系统无法回答“黄金应该参考哪些信息才能推理趋势”。

## 根因

缺少资产驱动因素配置和刷新器。

---

## 具体方案

### 输入

```python
refresh_asset_card(asset_id="GOLD", as_of_date="2026-08-04")
```

读取：

```text
configs/asset_cards/gold.yaml
```

---

## 数据源类型

### 1）行情型因素

配置：

```yaml
data_binding:
  type: market
  symbol: "DX-Y.NYB"
  source: "yfinance"
```

调用：

```python
market_data_sources.get_market_snapshot(symbol="DX-Y.NYB")
```

生成状态：

```python
if pct_change_5d > 1:
    change_direction = "up"
elif pct_change_5d < -1:
    change_direction = "down"
else:
    change_direction = "flat"
```

结合影响规则：

```python
if relation == "negative" and change_direction == "down":
    impact_direction = "positive"
elif relation == "negative" and change_direction == "up":
    impact_direction = "negative"
```

---

### 2）观点型因素

配置：

```yaml
data_binding:
  type: view_query
  query_terms: ["地缘", "避险", "冲突"]
  lookback_days: 14
```

调用：

```python
view_store.query_views(
    keywords=["地缘", "避险", "冲突"],
    date_start=...
)
```

计算热度：

```python
current_count = count_views(last_14_days)
previous_count = count_views(days_15_to_28)

if current_count > previous_count * 1.5:
    current_state = "热度上升"
    change_direction = "up"
elif current_count < previous_count * 0.7:
    current_state = "热度下降"
    change_direction = "down"
else:
    current_state = "热度持平"
```

---

### 3）手工型因素

有些数据源暂时拿不到，比如某些政策变量，可以允许用户手动维护：

```yaml
data_binding:
  type: manual
  update_hint: "每周手动更新央行购金数据"
```

状态记录：

```bash
python decision_logger.py update-factor GOLD CENTRAL_BANK_BUYING \
  --state "持续购金" \
  --direction "up" \
  --confidence 0.7
```

---

## 输出

```python
def refresh_factor_states(asset_id: str) -> list[FactorState]:
    ...
```

---

## 预期收益

- 分析卡可以自动刷新，不是静态模板。
- 用户能够看到“因素 → 状态 → 对资产影响”。
- 对黄金、半导体、AI、白酒、新能源等都可扩展。

## 工作量

3-5天。

---

# 3.3 决策日志记录与回填模块

## 模块名

```text
decision_logger.py
decision_outcome_updater.py
```

## 问题现状

用户判断没有被保存，也没有结果回填。

## 具体方案

### 记录接口

CLI 第一版即可：

```bash
python decision_logger.py add \
  --asset GOLD \
  --direction bullish \
  --horizon medium \
  --conviction 0.72 \
  --thesis "我看好黄金，因为美元见顶+央行购金" \
  --reasons "美元指数走弱;央行购金;地缘风险" \
  --invalidations "美元重新突破前高;实际利率持续上行"
```

自动附带：

- 当前资产分析卡版本；
- 最新多空对照卡；
- 当前因素状态；
- 当前行情快照；
- 用户引用的 view_id。

---

### 回填接口

```bash
python decision_outcome_updater.py update --days 5
python decision_outcome_updater.py update --days 20
```

逻辑：

```text
1. 找 status=open 的决策
2. 判断是否到达 horizon_days
3. 拉取资产行情
4. 计算收益、超额收益、最大回撤
5. 写入 decision_reviews
```

---

## 预期收益

- 用户能形成自己的“判断数据库”。
- 定期复盘能识别：哪些因素常被漏看，哪些因素被过度相信。
- 后续分析卡版本更新有来源。

## 工作量

3-5天。

---

# 3.4 复盘报告生成模块

## 模块名

```text
decision_review_generator.py
```

## 输入

```python
generate_review_report(
    period_start="2026-08-01",
    period_end="2026-08-31",
    asset_id="GOLD"
)
```

读取：

- `user_decision_logs`
- `decision_reviews`
- `factor_states`
- `asset_card_versions`
- `debate_cards`
- `market_outcomes`

---

## 输出Markdown

```markdown
# 黄金决策复盘：2026-08

## 1. 本月判断概览
- 决策次数：3
- 看多：2次
- 看空：0次
- 观望：1次
- 已完成复盘：2次

## 2. 结果
| 日期 | 判断 | 周期 | 结果 | 收益 | 最大回撤 |
|---|---|---|---|---|---|
| 08-04 | 看多 | 中期 | 正确 | +3.2% | -1.1% |

## 3. 当时主要依据
- 美元指数走弱
- 央行购金
- 地缘风险升温

## 4. 漏看因素
- 实际利率反弹速度低估
- 美元与黄金在避险环境下可能同涨

## 5. 本次认知修正
原规则：
> 美元走弱通常利好黄金。

修正为：
> 美元与黄金负相关在常规流动性环境下更有效；在全球避险阶段，美元和黄金可能同涨。

## 6. 建议更新分析卡
- 更新 DXY 因子的 conditional_note
- 增加“美元与黄金同涨场景”条件
```

LLM 可以参与“复盘总结表达”，但所有收益、方向、引用、版本关系必须由数据库确定性生成。

## 工作量

2-3天。

---

# 4. 与现有模块的关系

## 4.1 复用模块

| 现有模块 | 复用方式 |
|---|---|
| `structured_views.jsonl` | 作为观点事实源，不改字段 |
| `view_store.py` | 继续负责观点查询，新增按 entity/horizon/date 的接口 |
| `latest_digest.py` | 继续作为日报主观点来源之一 |
| `entity_normalizer.py` | 用于多空卡、分析卡实体归一 |
| `market_data_sources.py` | 用于因素状态、回测、决策结果回填 |
| `validate.py` | 改造成 prediction/outcome 管线 |
| `query_rag.py` | 继续作为证据补充器，不做主判断 |
| `brief_renderer.py` | 增加卡片渲染区块 |
| `tool_registry.py` | 注册新工具 |
| `post_check.py` | 增加卡片证据完整性校验 |

---

## 4.2 需要改造的模块

### 1）`view_store.py`

新增接口：

```python
def query_views_by_entity(
    entity: str,
    horizon: str | None = None,
    stance: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    view_type: str | None = None
) -> list[dict]:
    ...
```

新增接口：

```python
def query_views_by_keywords(
    keywords: list[str],
    date_start: str,
    date_end: str,
    view_types: list[str] | None = None
) -> list[dict]:
    ...
```

### 2）`market_data_sources.py`

新增统一快照接口：

```python
def get_asset_snapshot(asset_id: str, symbol: str, source: str) -> dict:
    return {
        "symbol": symbol,
        "as_of": "2026-08-04",
        "close": 101.2,
        "pct_change_1d": -0.2,
        "pct_change_5d": -1.1,
        "pct_change_20d": -2.4,
        "data_status": "cached_or_latest"
    }
```

### 3）`brief_renderer.py`

新增渲染函数：

```python
render_debate_card(card: dict) -> str
render_asset_analysis_card(card: dict) -> str
render_highlight_badges(tags: list[str]) -> str
```

Markdown示例：

```markdown
## 黄金｜多空对照卡  🔥强分歧 🆕新变化

### 多头论据
1. 钱博士：美元走弱支撑黄金  
   - 理由：美元指数回落，实际利率下行
   - 历史参考：该分析师黄金中期观点命中率 58%，样本12次
   - 证据：`view_20260803_008`

### 空头论据
1. 趋势天哥：黄金短期有回调压力  
   - 理由：避险情绪退潮，美元反弹

### 分歧点
- 分歧核心：美元是否已经见顶。
- 多头：钱博士
- 空头：趋势天哥

### 共识点
- 多数观点都承认美元走势是黄金判断的核心变量。
```

---

## 4.3 新增模块目录建议

```text
E:\qianboshi-agent
│
├─ decision/
│  ├─ decision_db.py
│  ├─ schemas.py
│  ├─ view_clusterer.py
│  ├─ debate_card_builder.py
│  ├─ factor_config_loader.py
│  ├─ factor_state_refresher.py
│  ├─ asset_card_builder.py
│  ├─ decision_logger.py
│  ├─ decision_outcome_updater.py
│  ├─ decision_review_generator.py
│  ├─ prediction_event_builder.py
│  ├─ outcome_updater.py
│  ├─ analyst_score_builder.py
│  └─ evidence_pack_builder.py
│
├─ configs/
│  └─ asset_cards/
│      ├─ gold.yaml
│      ├─ semiconductor.yaml
│      ├─ ai.yaml
│      └─ baijiu.yaml
│
├─ data/
│  ├─ qianboshi_decision.db
│  └─ decision_exports/
```

---

## 4.4 LLM参与边界

| 环节 | LLM参与 | 原因 |
|---|---:|---|
| 观点抽取 | 已有 | 现有结构化笔记流程 |
| claim聚类命名 | 可以 | 语义合并适合LLM |
| 多空卡摘要 | 可以 | 自然语言表达 |
| 因素状态计算 | 不应 | 必须确定性 |
| 行情涨跌计算 | 不应 | 必须确定性 |
| 分歧度计算 | 不应 | 必须确定性 |
| 分析师命中率 | 不应 | 必须确定性 |
| 决策结果回填 | 不应 | 必须确定性 |
| 复盘报告文字润色 | 可以 | 但数据和结论来源必须固定 |
| 是否买卖 | 禁止 | 系统不产生交易信号 |

---

# 5. 落地路线图

## 阶段一：1-2天见效，确定性改造

### 目标

让日报立刻出现“多空对照卡”。

### 做什么

1. 新建 SQLite：
   - `debate_cards`
   - `debate_card_items`
2. 新增：
   - `decision_db.py`
   - `debate_card_builder.py`
3. 改造：
   - `view_store.py` 增加按实体查询；
   - `brief_renderer.py` 增加多空卡渲染。
4. 第一版不用复杂聚类，先按 stance 分桶。
5. 高亮三类：
   - 高置信；
   - 强分歧；
   - 新变化。

### 第一版规则

```python
高置信 = confidence >= 0.75 and logic长度 >= 30
强分歧 = bullish>=2 and bearish>=2 and disagreement>=0.6
新变化 = 当前7天净方向与前14天净方向符号相反
```

### 预期效果

日报新增：

```markdown
## 今日重点资产多空对照

- 黄金：🔥强分歧 🆕新变化
- 半导体：✅高置信看多
- AI应用：⚠️风险观点增加
```

### 成本

LLM可不用。  
开发1-2天。

---

## 阶段二：3-5天，分析师正误追踪MVP

### 目标

把 validate.py 从“回测雏形”升级成表结构闭环。

### 做什么

1. 新增：
   - `prediction_events`
   - `market_outcomes`
   - `analyst_scores`
2. 从 structured_views 生成事件；
3. 拉行情计算 1/3/5/10/20日收益；
4. 对每个分析师、实体、周期统计命中率；
5. 在多空对照卡中显示 analyst_score。

### 预期效果

卡片中出现：

```markdown
钱博士｜黄金｜中期历史样本12次，命中率58%，平均超额+1.3%
趋势天哥｜黄金｜短期样本9次，命中率56%，样本较少
```

### 成本

少量行情接口，无LLM必要。  
开发3-5天。

---

## 阶段三：3-5天，资产分析卡MVP

### 目标

实现“黄金判断需要跟美元强挂钩”这种固定推理框架。

### 做什么

1. 建立 `configs/asset_cards/gold.yaml`；
2. 实现：
   - `factor_config_loader.py`
   - `factor_state_refresher.py`
   - `asset_card_builder.py`
3. 支持三类因素：
   - market；
   - view_query；
   - manual。
4. 日报增加资产分析卡。

### 预期效果

用户看到：

```markdown
## 黄金分析卡 v1

| 因素 | 当前状态 | 变化 | 对黄金影响 | 证据 |
|---|---|---|---|---|
| 美元指数 | 近5日走弱 | 向下 | 正向 | yfinance |
| 地缘风险 | 热度上升 | 向上 | 正向 | view_001/view_008 |
| 央行购金 | 中长期支撑仍在 | 持平 | 正向 | view_011 |
```

### 成本

观点型因素摘要可能调用LLM，但可先用模板。  
开发3-5天。

---

## 阶段四：3-5天，用户决策日志和复盘

### 目标

形成用户自己的判断数据库。

### 做什么

1. 建表：
   - `user_decision_logs`
   - `user_decision_evidence`
   - `decision_reviews`
2. CLI记录决策；
3. 自动附带当时分析卡、对照卡、行情快照；
4. 到期回填结果；
5. 生成复盘报告。

### 预期效果

```markdown
你在08-04看多黄金，核心理由是美元见顶+央行购金。
20日后黄金上涨3.2%，判断正确。
但期间最大回撤-2.4%，主要来自美元短线反弹。
建议在黄金分析卡中补充：美元反弹时的风险阈值。
```

### 成本

复盘文字总结可用LLM。  
开发3-5天。

---

## 阶段五：2-4天，EvidencePack统一证据包

### 目标

把 RAG 从 chunk 检索升级为 EvidencePack 检索。

### EvidencePack结构

```json
{
  "asset_id": "GOLD",
  "as_of_date": "2026-08-04",
  "asset_card": {},
  "factor_states": [],
  "debate_card": {},
  "latest_views": [],
  "analyst_scores": [],
  "market_snapshot": {},
  "user_decision_history": [],
  "rag_evidence": []
}
```

### 输出接口

```python
build_evidence_pack(asset_id="GOLD", horizon="medium")
```

Chat和日报都调用这个包。

### 成本

可少量LLM总结。  
开发2-4天。

---

## 阶段六：交互升级

### 短期：Markdown日报固定区块

成本最低，直接接现有 `brief_renderer.py`。

### 中期：Feishu/Studio聊天

工具：

```python
get_asset_analysis_card(asset_id)
get_debate_card(entity, horizon)
get_factor_states(asset_id)
log_user_decision(...)
get_decision_review(asset_id)
```

用户问：

```text
黄金现在怎么看？
```

系统返回：

```text
1. 黄金分析卡
2. 最新因素状态
3. 多空对照
4. 历史分析师准确率
5. 用户历史判断复盘
```

### 后期：独立浏览界面

建议技术栈：

```text
Next.js + shadcn/ui + Tailwind + SQLite API/FastAPI
```

页面：

1. 资产卡页面；
2. 多空对照页面；
3. 分析师准确率页面；
4. 用户决策日志页面；
5. 复盘时间线页面。

不建议 Streamlit。

---

# 6. 成本评估：DeepSeek v4 Flash调用量

## 6.1 哪些地方需要LLM

| 功能 | 是否必须 | 调用频率 |
|---|---:|---|
| 多空卡stance分桶 | 否 | 0 |
| 多空卡claim聚类命名 | 可选 | 每资产每天1次 |
| 多空卡摘要 | 可选 | 每资产每天1次 |
| 观点型因素摘要 | 可选 | 每资产每因素1次 |
| 复盘报告润色 | 可选 | 每次复盘1次 |
| EvidencePack最终表达 | 可选 | 每次问答1次 |

---

## 6.2 每日自动任务估算

假设每天重点资产10个，每个资产：

- 多空聚类1次；
- 多空摘要1次；
- 分析卡摘要1次。

约：

```text
10资产 × 3次 = 30次LLM调用/天
```

每次输入约：

```text
2k-5k tokens
```

每日总量：

```text
输入 60k-150k tokens
输出 15k-40k tokens
```

对于 deepseek-v4-flash 这类低价模型，通常是**每天几毛钱到几元人民币量级**，主要取决于官方实时价格和摘要长度。

如果只做确定性MVP：

```text
LLM调用 = 0
```

仍然可以实现多空卡、分析卡基础版、回测、决策日志。

---

## 6.3 成本控制方案

不是简单说“加缓存”，而是具体做：

### 1）聚类结果按 view_id 集合签名缓存

```python
signature = sha256("|".join(sorted(view_ids))).hexdigest()
```

若同一资产同一窗口 view_id 未变，不再调用LLM。

### 2）摘要按 EvidencePack hash 缓存

```python
pack_hash = sha256(json.dumps(evidence_pack, sort_keys=True)).hexdigest()
```

证据包没变，不重新生成。

### 3）只对重点资产生成

配置：

```yaml
daily_focus_assets:
  - GOLD
  - 半导体
  - AI应用
  - 白酒
  - 新能源
```

非重点资产按需生成。

### 4）批量聚类

把同一个资产的20条以内观点一次性给LLM，不逐条调用。

---

# 7. 每条需求的落地映射

## 需求1：多空对照卡

| 要求 | 落地方案 |
|---|---|
| 多头论据清单 | `debate_card_items` stance=bullish |
| 空头论据清单 | `debate_card_items` stance=bearish/risk |
| 分歧点 | `debate_detector.py` 根据多空cluster生成 |
| 共识点 | 同向cluster占比高生成 |
| 高置信判断 | confidence + logic/evidence长度 + analyst_score |
| 强分歧 | bullish/bearish比例计算 |
| 新变化 | 当前窗口和前一窗口净方向比较 |
| 视觉突出 | Markdown badge：🔥强分歧、✅高置信、🆕新变化 |

---

## 需求2：资产分析卡

| 要求 | 落地方案 |
|---|---|
| 因素清单可编辑 | `configs/asset_cards/*.yaml` |
| 因素绑定行情 | `data_binding.type=market` |
| 因素绑定观点 | `data_binding.type=view_query` |
| 自动刷新 | `factor_state_refresher.py` |
| 影响方向 | `impact_rule.relation`确定性计算 |
| 历史正误 | 关联 `decision_reviews` 和 `market_outcomes` |
| 版本号 | `asset_card_versions` |
| 用户认知演进 | 复盘后生成新version |

---

## 需求3：决策复盘层

| 进化回路 | 落地方案 |
|---|---|
| 分析师正误追踪 | `prediction_events → market_outcomes → analyst_scores` |
| 用户决策日志 | `user_decision_logs + user_decision_evidence` |
| 市场结果回填 | `decision_outcome_updater.py` |
| 定期复盘 | `decision_review_generator.py` |
| 分析卡版本化 | `asset_card_versions` |

---

## 需求4：交互形态

| 阶段 | 方案 |
|---|---|
| 最低成本 | Markdown日报固定区块 |
| 中期 | Feishu/Studio聊天工具调用 |
| 后期 | Next.js + shadcn-admin独立界面 |

---

# 8. 一句话总结 + 最高价值三步走，500字以内

一句话总结：  
钱博士Agent应从“把财经内容总结出来”升级为“围绕资产把多空观点、驱动因素、历史证据和用户复盘串起来的投研决策台”，但始终不产生买卖信号，只放大用户判断力。

最高价值三步走：

1. **第一刀，1-2天做多空对照卡**：基于 structured_views.jsonl 按 entity/horizon/date 聚合观点，确定性生成多头、空头、强分歧、高置信、新变化，并接入现有日报Markdown。
2. **第二刀，3-5天做分析师回测MVP**：把 view_id 事件化，回填1/3/5/10/20日收益，生成 analyst_scores，让每条当前观点旁边都有历史可信度参考。
3. **第三刀，3-5天做资产分析卡**：用 YAML 配置黄金、半导体等资产的驱动因素，自动刷新美元、利率、地缘、政策等因素状态，形成“因素→状态→影响→证据”的固定推理框架，并为后续用户决策日志和复盘版本化打地基。