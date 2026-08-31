# gpt-5.5 深度审计报告
生成时间: 2026-08-04T21:33:30.732540

下面按“真实业务需求”重构视角分析：钱博士Agent现在已经具备采集、转写、RAG、观点抽取、日报生成的雏形，但核心问题是：**系统目前更像一个“财经内容摘要系统”，还不是一个“可追溯、可验证、可用于实盘辅助的投研证据系统”**。

要满足用户实盘决策，系统必须从“生成观点”升级为：

> **观点 → 证据链 → 历史表现 → 当前可信度 → 风险条件 → 可追溯来源** 的完整闭环。

---

# 1. 日报生成架构优化：支撑“长日报 + 完整例证链 + 历史回测引用”

## 1.1 当前问题

### 问题现状

现有日报/简报链路大概率是：

```text
用户问题/日期范围
→ RAG 检索相关 chunk
→ LLM 总结
→ brief_renderer 渲染
→ post_check 简单质检
```

这适合生成“财经摘要”，但不适合生成“实盘辅助日报”。

主要问题：

1. **观点链不完整**
   - 日报可能只输出“看好AI、看空新能源”。
   - 但没有把：
     - 谁说的？
     - 什么时候说的？
     - 原话是什么？
     - 支撑理由有哪些？
     - 举了哪些例子？
     - 该观点是否与其过去判断一致？
     - 过去类似判断有没有验证？
     - 如果错了，错在哪里？
   - 这些信息完整展开。

2. **证据粒度不够**
   - Chroma chunk 只能作为语义片段，不等于“观点证据”。
   - 当前 structured_views.jsonl 可能有观点类型、方向、时间跨度、质量分，但未必保留完整证据链。

3. **日报生成是一次性 LLM 汇总**
   - 一次 prompt 里塞 RAG 结果，然后生成日报。
   - 这会导致：
     - 长内容丢信息。
     - 强观点被弱化。
     - 例证被省略。
     - 观点之间缺乏对照。
     - 历史回测结果很难自然融合。

4. **没有“证据优先”的生成结构**
   - 现在像“先生成结论，再找资料支持”。
   - 实盘系统应是“先收集证据，再生成结论”。

---

## 1.2 根因

根因不是单纯提示词问题，而是数据模型和生成流程不匹配。

目前系统核心数据单位是：

```text
笔记 / chunk / 向量 / 简单观点
```

但实盘决策需要的数据单位是：

```text
观点 Statement
→ 证据 Evidence
→ 标的 Entity
→ 时间 Horizon
→ 预测方向 Direction
→ 置信度 Confidence
→ 事后验证 Outcome
→ 分析师历史能力 Analyst Skill
```

也就是说，需要从“文档检索系统”升级为“观点事件数据库 + 证据图谱 + 回测系统”。

---

## 1.3 具体方案

### 方案 A：日报改为多阶段流水线，而不是单次 RAG 总结

新增模块：

```text
daily_report_pipeline.py
```

日报生成流程改为：

```text
Step 1：确定日报主题池
Step 2：检索当日/近期观点候选
Step 3：观点聚类和去重
Step 4：为每个核心观点构建证据链
Step 5：调用历史回测系统，取该分析师/主题/标的历史表现
Step 6：生成单观点卡片
Step 7：组合成长日报
Step 8：自动质检：每个观点是否有证据、有原文、有历史记录、有风险条件
```

#### 具体流程

```python
class DailyReportPipeline:
    def run(self, report_date):
        topics = self.discover_topics(report_date)
        view_clusters = self.collect_and_cluster_views(topics, report_date)
        sections = []

        for cluster in view_clusters:
            evidence_chain = self.build_evidence_chain(cluster)
            history = self.fetch_historical_performance(cluster)
            section = self.generate_view_section(cluster, evidence_chain, history)
            sections.append(section)

        report = self.render_long_report(sections)
        qc_result = self.post_check(report, sections)

        if not qc_result.passed:
            report = self.repair_report(report, qc_result)

        return report
```

---

### 方案 B：日报中的每个观点使用“观点卡片 ViewCard”

定义统一输出对象，不让 LLM 自由发挥。

```python
@dataclass
class ViewCard:
    view_id: str
    report_date: str

    analyst: str
    source_program: str
    source_date: str
    source_url: str | None

    entity_type: str       # stock / sector / macro / index / theme
    entity_name: str
    entity_code: str | None

    direction: str         # bullish / bearish / neutral / conditional
    horizon: str           # intraday / short / medium / long
    confidence: float

    core_claim: str
    reasoning_chain: list[str]
    supporting_examples: list["EvidenceItem"]
    counter_evidence: list["EvidenceItem"]

    historical_records: list["HistoricalOutcome"]
    analyst_accuracy_summary: dict

    trigger_conditions: list[str]
    invalidation_conditions: list[str]
    risk_notes: list[str]

    final_interpretation: str
```

日报不要直接让 LLM 写，而是先由程序填 ViewCard，再让 LLM 只负责润色。

---

### 方案 C：每个观点必须绑定 EvidenceItem

新增证据对象：

```python
@dataclass
class EvidenceItem:
    evidence_id: str
    source_type: str        # asr_raw / note_summary / structured_view / market_data
    source_file: str
    source_date: str
    analyst: str | None

    start_ts: float | None
    end_ts: float | None
    original_text: str
    normalized_text: str

    evidence_role: str      # claim / reason / example / risk / condition / counterexample
    related_entity: str | None
    quote_importance: int   # 1-5
```

日报中每个观点至少要求：

```text
1 条核心原文证据
2 条支撑理由或案例
1 条风险/条件证据
若有历史验证，则至少 1 条历史观点证据 + 1 条市场走势证据
```

否则该观点降级为“信息不足，不作为强信号”。

---

### 方案 D：生成“长日报”时采用分块生成 + 汇总索引

长日报不要怕长，但要有结构，否则用户无法使用。

建议日报结构：

```markdown
# 钱博士实盘辅助日报 YYYY-MM-DD

## 0. 今日结论总览
- 高可信方向
- 中可信方向
- 仅供观察方向
- 明确回避方向

## 1. 今日核心观点矩阵
| 主题 | 标的/板块 | 方向 | 分析师 | 历史准确率 | 证据数量 | 可信度 | 操作含义 |

## 2. 核心观点详解

### 2.1 AI算力链：短期继续强势，但追高风险上升
#### 观点结论
#### 原始证据链
- 原文1
- 原文2
- 二次理解证据
#### 支撑逻辑拆解
#### 历史回测
- 该分析师过去3次类似判断
- 后续涨跌表现
- 正误评估
#### 当前可信度
#### 风险触发条件
#### 实盘参考

## 3. 分析师历史表现排行

## 4. 今日冲突观点
## 5. 需要跟踪的验证信号
## 6. 附录：完整引用来源
```

---

## 1.4 预期收益

1. 日报从“摘要”升级为“可追溯投研报告”。
2. 每个观点都有原始出处，减少幻觉。
3. 用户可判断“这个观点为什么成立”。
4. 分析师历史正确率进入决策链。
5. 支持长日报，不再受单次 RAG 上下文限制。

---

## 1.5 工作量/成本估算

| 项目 | 工作量 |
|---|---:|
| ViewCard / EvidenceItem 数据模型 | 1-2 天 |
| 日报多阶段 Pipeline | 3-5 天 |
| 观点证据链构建器 | 3-5 天 |
| 长日报 renderer | 2-3 天 |
| 质检规则升级 | 2 天 |
| 总计 | 2-3 周 |

---

# 2. 分析师历史判断回测体系优化

这是整个系统最关键的升级。

---

## 2.1 当前问题

### 问题现状

现有 `validate.py` 是“10位分析师观点 vs 市场实际走势”的雏形，但距离可用于实盘还有差距。

可能问题：

1. 回测对象太少。
2. 观点结构不标准。
3. 没有区分：
   - 标的类型：个股、板块、指数、主题。
   - 方向：看多、看空、震荡、条件看多。
   - 时间跨度：当天、一周、一月、季度。
   - 价格基准：说出观点时的价格。
   - 目标验证窗口。
4. 缺少“观点有效期”。
5. 没有处理“模糊观点”。
6. 没有把回测结果反哺日报。

---

## 2.2 根因

现在观点库更像 NLP 抽取结果，不是“可回测预测事件”。

要做回测，必须把分析师的话转为一个标准对象：

```text
某人在某时对某标的做出了一个方向性预测，
预测的时间范围是多久，
预测成立条件是什么，
事后用什么市场指标验证。
```

---

## 2.3 具体方案

### 方案 A：新增 PredictionEvent 标准表

建议不要继续只用 jsonl，升级为 SQLite 或 DuckDB。

原因：

- 观点数量不会特别巨大，但需要复杂查询。
- DuckDB 对 parquet/json/csv 支持好，适合投研数据分析。
- SQLite 更简单，部署容易。

推荐第一阶段用 SQLite，后续可迁移 DuckDB。

表结构：

```sql
CREATE TABLE prediction_events (
    prediction_id TEXT PRIMARY KEY,

    analyst TEXT NOT NULL,
    source_date TEXT NOT NULL,
    source_file TEXT,
    source_url TEXT,

    entity_name TEXT NOT NULL,
    entity_code TEXT,
    entity_type TEXT, -- stock, sector, index, theme, macro

    direction TEXT NOT NULL, -- bullish, bearish, neutral, volatile, conditional
    horizon TEXT,            -- intraday, 1w, 1m, 3m, 6m
    horizon_days INTEGER,

    confidence REAL,
    claim_text TEXT NOT NULL,
    normalized_claim TEXT,

    reasoning_summary TEXT,
    conditions TEXT,
    invalidation TEXT,

    evidence_ids TEXT,       -- JSON list

    extraction_model TEXT,
    extraction_version TEXT,
    created_at TEXT
);
```

---

### 方案 B：新增 MarketOutcome 表

记录每个预测事件对应的事后市场表现。

```sql
CREATE TABLE market_outcomes (
    outcome_id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL,

    start_date TEXT,
    end_date TEXT,

    start_price REAL,
    end_price REAL,
    max_return REAL,
    min_return REAL,
    final_return REAL,

    benchmark_name TEXT,
    benchmark_return REAL,
    excess_return REAL,

    volatility REAL,
    max_drawdown REAL,

    hit_result TEXT,      -- correct, wrong, neutral, unverified, ambiguous
    hit_score REAL,       -- -1 到 1
    evaluation_reason TEXT,

    evaluated_at TEXT
);
```

---

### 方案 C：新增 AnalystScore 表

不是简单准确率，而是分维度能力。

```sql
CREATE TABLE analyst_scores (
    analyst TEXT,
    entity_type TEXT,
    sector TEXT,
    horizon TEXT,

    total_predictions INTEGER,
    valid_predictions INTEGER,

    accuracy REAL,
    avg_excess_return REAL,
    avg_hit_score REAL,
    avg_max_drawdown REAL,

    bullish_accuracy REAL,
    bearish_accuracy REAL,

    recent_30d_accuracy REAL,
    recent_90d_accuracy REAL,

    confidence_calibration REAL,

    updated_at TEXT,

    PRIMARY KEY (analyst, entity_type, sector, horizon)
);
```

---

## 2.4 观点如何从 ASR/笔记中结构化抽取

新增模块：

```text
prediction_extractor.py
```

处理流程：

```text
ASR原文/笔记
→ LLM抽取候选预测
→ 规则校验
→ 实体标准化
→ 时间跨度解析
→ 方向归一化
→ 置信度估计
→ 写入 prediction_events
```

LLM 输出强制 JSON：

```json
{
  "analyst": "钱博士",
  "source_date": "2025-01-08",
  "predictions": [
    {
      "entity_name": "半导体",
      "entity_type": "sector",
      "direction": "bullish",
      "horizon": "1m",
      "claim_text": "半导体这个方向后面还有反复机会，不能太悲观。",
      "reasoning": [
        "国产替代逻辑仍在",
        "调整后筹码压力释放",
        "政策端有持续催化"
      ],
      "conditions": [
        "指数不能放量破位",
        "龙头股需要维持趋势"
      ],
      "invalidation": [
        "若板块跌破前低且无资金回流，则观点失效"
      ],
      "confidence": 0.72
    }
  ]
}
```

---

## 2.5 如何判定正误

不同观点要用不同验证标准。

### 个股看多

```text
预测日收盘价 = P0
验证窗口 = horizon_days
未来窗口收益 = R_stock
同期基准收益 = R_benchmark
超额收益 = R_stock - R_benchmark

若：
- R_stock > 0 且 R_stock > R_benchmark + 2%
则 correct
- R_stock < 0 且 R_stock < R_benchmark - 2%
则 wrong
否则 neutral
```

### 个股看空

```text
若未来窗口 R_stock < R_benchmark - 2% → correct
若 R_stock > R_benchmark + 2% → wrong
否则 neutral
```

### 板块看多

板块没有统一行情时，建议映射：

```yaml
AI算力:
  benchmark:
    - 中证人工智能指数
    - 云计算ETF
    - 通信ETF
  representative_stocks:
    - 工业富联
    - 中际旭创
    - 新易盛
```

验证时用：

```text
板块指数收益 或 代表股票等权收益
```

### 条件观点

例如：

> 如果放量突破，则看多。

这种不能直接回测，应拆成两个事件：

```text
condition_event：是否放量突破
prediction_event：条件满足后看多
```

如果条件没有发生，标记：

```text
untriggered
```

不计入准确率，但可计入“条件描述质量”。

---

## 2.6 准确率不要只算一个数

日报中应该展示：

```text
钱博士过去对“半导体/1个月周期/看多”共有 12 次可验证观点：
- 正确 7 次
- 错误 3 次
- 中性 2 次
- 准确率 70.0%
- 平均超额收益 +3.8%
- 最近90天准确率 60.0%
- 最大单次错误：2024-xx-xx 看多半导体，后续20日超额 -8.2%
```

可信度建议公式：

```python
current_view_trust = (
    0.35 * analyst_topic_accuracy
    + 0.25 * recent_accuracy
    + 0.20 * evidence_quality
    + 0.10 * market_confirmation
    + 0.10 * consistency_with_other_analysts
)
```

---

## 2.7 日报中如何呈现历史回测

每个核心观点附一个历史块：

```markdown
#### 该分析师历史表现

钱博士过去 180 天对“AI算力链”做出 9 次可验证判断：

| 日期 | 当时观点 | 方向 | 周期 | 后续表现 | 评估 |
|---|---|---|---|---|---|
| 2024-11-03 | 算力仍是主线，不宜轻易看空 | 看多 | 1月 | 板块 +12.4%，跑赢沪深300 +9.1% | 正确 |
| 2024-12-15 | 高位震荡，追高性价比下降 | 谨慎 | 2周 | 板块 -4.3% | 正确 |
| 2025-01-10 | 还会继续冲一波 | 看多 | 1周 | 板块 -3.1% | 错误 |

综合评价：该分析师在该主题上的中期方向判断较强，但短线节奏有波动。
```

---

## 2.8 工作量/成本估算

| 项目 | 工作量 |
|---|---:|
| SQLite/DuckDB 回测库设计 | 1-2 天 |
| PredictionEvent 抽取器 | 4-7 天 |
| 行情验证器 | 4-6 天 |
| 板块映射表建设 | 2-4 天 |
| 分析师分维度评分 | 2-3 天 |
| 日报集成 | 2-3 天 |
| 总计 | 3-4 周 |

---

# 3. RAG / 检索层优化

## 3.1 当前问题

### 问题现状

现有：

- Chroma 向量库 9483 chunks。
- `query_rag.py` 有 banned source 过滤、keyword overlap。
- `latest_digest.py` 绕开 embedding 做最近观点 digest。
- `view_store.py` 查询观点库。

问题：

1. 检索对象还是 chunk，不是“观点”和“证据”。
2. 向量检索容易召回语义相似但不适合回测的文本。
3. 对时间敏感性支持不足。
4. 对分析师、标的、板块、时间跨度的过滤能力不足。
5. ASR 原文和二次理解内容没有统一证据索引。
6. 检索结果缺少出处定位，例如音频时间戳、原始文件段落。

---

## 3.2 根因

RAG 系统目标不清：

- 问答型 RAG：找相似内容回答。
- 投研型 RAG：找“与当前决策相关的可验证观点证据”。

现在更接近前者。

---

## 3.3 具体方案

### 方案 A：建立三层检索索引

不要只用一个 Chroma。

建议建立：

```text
1. Evidence Index：原文证据索引
2. View Index：结构化观点索引
3. Prediction Index：可回测观点索引
```

#### Evidence Index

存储 ASR 原文片段、笔记片段。

字段：

```json
{
  "evidence_id": "ev_...",
  "source_type": "asr_raw",
  "source_date": "2025-01-08",
  "analyst": "钱博士",
  "entity_names": ["半导体", "寒武纪"],
  "start_ts": 1234.5,
  "end_ts": 1260.2,
  "text": "原文..."
}
```

#### View Index

存结构化观点：

```json
{
  "view_id": "view_...",
  "analyst": "钱博士",
  "entity": "半导体",
  "direction": "bullish",
  "horizon": "1m",
  "claim": "...",
  "evidence_ids": [...]
}
```

#### Prediction Index

存可回测事件：

```json
{
  "prediction_id": "pred_...",
  "analyst": "钱博士",
  "entity": "半导体",
  "direction": "bullish",
  "horizon_days": 20,
  "hit_result": "correct",
  "hit_score": 0.73
}
```

---

### 方案 B：采用 Hybrid Retrieval

检索流程改为：

```text
用户/日报主题
→ 实体标准化
→ 时间过滤
→ BM25关键词召回
→ 向量召回
→ 结构化观点召回
→ 历史预测召回
→ rerank
→ 输出证据包
```

可以用：

- BM25：`rank_bm25` 或 `tantivy`
- 向量：Chroma 保留
- Reranker：轻量 cross-encoder，或者 LLM rerank 小批量

评分公式：

```python
score = (
    0.30 * vector_score
    + 0.25 * bm25_score
    + 0.20 * entity_match_score
    + 0.15 * recency_score
    + 0.10 * evidence_quality_score
)
```

对“历史回测”检索另设评分：

```python
history_score = (
    0.35 * same_analyst
    + 0.30 * same_entity_or_sector
    + 0.20 * same_horizon
    + 0.15 * recency
)
```

---

### 方案 C：chunk 切分改为“时间戳 + 语义段落 + 观点边界”

当前笔记 chunk 可能是固定长度切分。需要改为：

```text
ASR 时间戳段
→ 句子合并
→ 主题变化检测
→ 观点边界识别
→ chunk
```

每个 chunk 包含：

```json
{
  "chunk_id": "...",
  "source_file": "...",
  "start_ts": 123.0,
  "end_ts": 185.0,
  "text": "...",
  "entities": ["AI", "算力"],
  "analyst": "钱博士",
  "contains_prediction": true,
  "contains_example": true,
  "contains_risk": false
}
```

---

### 方案 D：检索结果返回“证据包”，不是文本列表

新增：

```python
@dataclass
class EvidencePack:
    query: str
    entity: str
    current_views: list[ViewCard]
    raw_quotes: list[EvidenceItem]
    historical_predictions: list[HistoricalOutcome]
    market_data: dict
    conflicts: list[ViewCard]
```

日报生成只接受 EvidencePack，避免 LLM 临场拼材料。

---

## 3.4 预期收益

1. 检索结果更适合投研决策。
2. 每个观点能追溯到 ASR 原文。
3. 历史观点可被精确召回。
4. 支撑长日报完整证据链。
5. 减少 hallucination。

---

## 3.5 工作量/成本估算

| 项目 | 工作量 |
|---|---:|
| Evidence Index 元数据扩展 | 3-5 天 |
| BM25 + Vector 混合检索 | 2-4 天 |
| 观点/预测专用检索接口 | 3-5 天 |
| EvidencePack 数据结构 | 1-2 天 |
| Rerank 策略 | 2-3 天 |
| 总计 | 2-3 周 |

---

# 4. 数据管线优化：采集 / 转写 / 纠错 / 结构化

---

## 4.1 采集层优化

### 问题现状

- `monitor_bilibili.py` 监控 B站频道。
- 已知未覆盖钱博士自己频道。
- `audio/` 占 326GB，无清理策略。
- 依赖 `monitor_state.json` 做断点续传。

### 根因

采集层缺少：

1. 多频道订阅配置。
2. 媒体文件生命周期管理。
3. 采集状态数据库。
4. 下载失败重试/质量标记。
5. 原始来源元数据标准化。

### 具体方案

#### 方案 A：采集源配置化

新增：

```yaml
sources:
  bilibili:
    - name: 钱博士
      channel_id: "xxx"
      enabled: true
      priority: 10
      tags: ["primary", "analyst"]
    - name: 其他财经频道
      channel_id: "yyy"
      enabled: true
      priority: 5
```

`monitor_bilibili.py` 改为读取 `sources.yaml`，循环监控。

---

#### 方案 B：用 SQLite 替代 monitor_state.json

表结构：

```sql
CREATE TABLE media_assets (
    asset_id TEXT PRIMARY KEY,
    platform TEXT,
    channel_name TEXT,
    channel_id TEXT,
    bvid TEXT,
    title TEXT,
    publish_time TEXT,
    url TEXT,

    download_status TEXT,
    audio_path TEXT,
    audio_size_mb REAL,
    duration_sec REAL,

    asr_status TEXT,
    note_status TEXT,
    extraction_status TEXT,

    created_at TEXT,
    updated_at TEXT
);
```

优点：

- 可查哪些没转写。
- 可查哪些失败。
- 可清理已处理音频。
- 可按优先级补任务。

---

#### 方案 C：音频生命周期清理策略

业务上，ASR 后原始音频未必需要永久保留。建议分层：

```text
原始音频 audio_raw：
- 转写成功 + ASR文本通过质检 + 30天后删除
- 若是高价值直播，转为低码率 mp3 后保留
- 若ASR失败，保留等待重试

ASR文本：
- 永久保留
- 保留时间戳

笔记/结构化观点：
- 永久保留

高价值音频：
- 标记 archive=true，不自动删除
```

清理脚本：

```python
cleanup_audio.py --older-than 30 --only-asr-success --dry-run
cleanup_audio.py --older-than 30 --only-asr-success --execute
```

预计 326GB 可降到 50GB 以下。

---

## 4.2 转写层优化

### 问题现状

- faster-whisper base，RTX4060 8GB。
- 有正则纠错表 109 条。
- 二次纠错笔记。

问题：

1. base 模型对财经术语、公司名识别仍可能不够。
2. 正则纠错维护成本高。
3. ASR 错误会污染后续观点抽取。
4. 缺少 ASR 质量评分。
5. 可能没有保留词级/段级时间戳。

### 根因

ASR 纠错和业务实体库没有深度结合。

### 具体方案

#### 方案 A：ASR 输出标准化为 segment JSONL

不要只保存 txt。

```json
{
  "asset_id": "...",
  "segment_id": "...",
  "start": 123.4,
  "end": 138.2,
  "text_raw": "寒武记今天...",
  "text_fixed": "寒武纪今天...",
  "confidence": 0.82,
  "entities_detected": ["寒武纪"]
}
```

这样日报引用原文时可定位。

---

#### 方案 B：实体驱动纠错

把 `entity_aliases.yaml`、股票代码、板块词库纳入纠错。

建立：

```text
asr_correction_rules.yaml
entity_aliases.yaml
stock_names.csv
sector_terms.yaml
```

纠错流程：

```text
ASR segment
→ 正则纠错
→ 实体候选匹配
→ 拼音/同音近似匹配
→ 上下文确认
→ 输出 text_fixed
```

例如：

```python
if fuzzy_pinyin_match("寒武记", "寒武纪") and context_contains(["芯片", "AI", "算力"]):
    replace("寒武记", "寒武纪")
```

---

#### 方案 C：ASR 质量评分

每段计算：

```python
quality_score = (
    0.4 * whisper_avg_logprob
    + 0.2 * no_speech_prob_inverse
    + 0.2 * entity_match_confidence
    + 0.2 * punctuation_readability
)
```

低质量段标记：

```json
"needs_review": true
```

观点抽取时，如果核心证据来自低质量 ASR，要在日报中提示：

```text
该段 ASR 置信度较低，需谨慎解读。
```

---

## 4.3 结构化层优化

### 问题现状

`view_extractor.py` 已经抽结构化观点，但可能没有强制抽取：

- 观点原文
- 支撑例证
- 风险条件
- 可回测字段
- 时间跨度
- 失效条件

### 具体方案

升级为两类抽取：

```text
ViewExtractor：抽取普通观点
PredictionExtractor：抽取可回测预测
EvidenceExtractor：抽取例证/理由/风险
```

每篇笔记处理后生成：

```text
views.jsonl
predictions.jsonl
evidences.jsonl
entities.jsonl
```

而不是只生成 `structured_views.jsonl`。

---

## 4.4 预期收益

1. 钱博士自己频道纳入系统。
2. 大幅降低磁盘占用。
3. ASR 可追溯到时间戳。
4. 纠错不再仅靠硬编码正则。
5. 观点抽取结果可直接进入回测系统。

---

## 4.5 工作量/成本估算

| 项目 | 工作量 |
|---|---:|
| 多频道配置化 | 1-2 天 |
| media_assets SQLite | 2-3 天 |
| 音频清理策略 | 1 天 |
| ASR segment JSONL | 2-3 天 |
| 实体驱动纠错 | 3-5 天 |
| 抽取器升级 | 5-8 天 |
| 总计 | 3 周左右 |

---

# 5. 代码工程优化：测试 / 配置 / 错误处理 / 监控

---

## 5.1 当前问题

### 问题现状

- 测试覆盖很薄，只有 2 个测试文件 276 行。
- LLM API 故障切换手动。
- 配置虽有 `config_loader.py`，但可能模块间仍有隐式配置。
- monitor、ASR、RAG、日报生成之间缺少统一任务状态。
- 失败恢复和告警不足。

---

## 5.2 根因

系统从脚本集合演进而来，没有形成“任务化数据管线”。

---

## 5.3 具体方案

### 方案 A：建立统一任务状态机

新增：

```sql
CREATE TABLE pipeline_jobs (
    job_id TEXT PRIMARY KEY,
    asset_id TEXT,
    job_type TEXT, -- download, asr, fix_asr, note, extract_view, build_vector, validate
    status TEXT,   -- pending, running, success, failed, skipped
    retry_count INTEGER,
    error_message TEXT,
    started_at TEXT,
    finished_at TEXT
);
```

每个脚本改为：

```text
读取 pending jobs
→ 执行
→ 写 success/failed
→ 失败记录 error_message
```

这样可以随时恢复。

---

### 方案 B：LLM API 自动故障切换

新增：

```text
llm_client.py
```

支持：

```yaml
llm_providers:
  - name: deepseek_v4_flash
    api_key_env: DEEPSEEK_API_KEY
    priority: 1
    timeout: 60
    max_retries: 3
  - name: qwen_plus
    api_key_env: DASHSCOPE_API_KEY
    priority: 2
    timeout: 60
    max_retries: 2
  - name: local_ollama
    priority: 3
```

故障切换逻辑：

```python
for provider in providers:
    try:
        return provider.chat(prompt)
    except RateLimitError:
        sleep(backoff)
    except ProviderDownError:
        continue
```

每次调用记录：

```sql
CREATE TABLE llm_calls (
    call_id TEXT PRIMARY KEY,
    provider TEXT,
    model TEXT,
    task_type TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost REAL,
    latency_ms INTEGER,
    status TEXT,
    error TEXT,
    created_at TEXT
);
```

---

### 方案 C：关键测试用例补齐

优先不是追求 100% 覆盖，而是覆盖业务关键链路。

#### 必测 1：观点抽取

输入一段模拟 ASR：

```text
我觉得半导体后面一个月还有机会，但如果指数跌破前低，就要谨慎。
```

断言：

```python
direction == "bullish"
horizon_days == 20
entity == "半导体"
invalidation contains "跌破前低"
```

#### 必测 2：历史回测

输入：

```text
看多某股，预测日价格 10，20日后 11，基准涨 2%
```

断言：

```python
hit_result == "correct"
excess_return == 8%
```

#### 必测 3：日报质检

如果某观点没有 evidence_id，必须失败。

```python
assert post_check(report).missing_evidence_count == 0
```

---

### 方案 D：监控面板

不需要一开始做复杂前端，用 CLI/Markdown 日报即可。

新增：

```bash
python system_status.py
```

输出：

```text
采集：今日新增 3 条，失败 1 条
ASR：待处理 5 条，失败 2 条
观点抽取：成功 860 篇，失败 4 篇
向量库：9483 chunks，最近更新 2025-xx-xx
回测：可验证预测 1280 条，已验证 960 条
LLM：今日调用 132 次，失败率 3.1%，成本 $x
磁盘：audio 326GB，建议清理 240GB
```

---

## 5.4 预期收益

1. 系统可恢复、可观测。
2. LLM 故障不再中断日报。
3. 回测和日报质量可自动检查。
4. 新功能迭代风险下降。

---

## 5.5 工作量/成本估算

| 项目 | 工作量 |
|---|---:|
| pipeline_jobs 状态机 | 2-4 天 |
| llm_client 故障切换 | 2-3 天 |
| 关键单测 30-50 个 | 4-6 天 |
| system_status CLI | 1-2 天 |
| 日志结构化 | 1-2 天 |
| 总计 | 2 周左右 |

---

# 6. 成本优化

---

## 6.1 当前问题

### 问题现状

1. `audio/` 326GB，占用过高。
2. LLM 长日报、结构化抽取、RAG rerank 会增加 API 成本。
3. Chroma 重建和增量处理可能重复计算。
4. LLM API 故障切换手动，失败重试可能浪费 token。
5. ASR 模型 base 成本低，但如果升级模型，需要控制 GPU 时间。

---

## 6.2 根因

缺少“按任务价值分级”的成本策略。

---

## 6.3 具体方案

### 方案 A：音频降本

执行生命周期策略：

```text
ASR成功 + 30天后删除原始音频
高价值直播转低码率保存
失败音频保留
```

预期：

```text
326GB → 50GB 以下
```

---

### 方案 B：LLM 任务分级

不同任务用不同模型。

```yaml
llm_task_policy:
  asr_note_structuring:
    model: deepseek-v4-flash
    temperature: 0.1

  prediction_extraction:
    model: deepseek-v4-flash
    temperature: 0.0

  evidence_classification:
    model: cheap_model_or_local
    temperature: 0.0

  final_report_writing:
    model: stronger_model
    temperature: 0.2

  rerank:
    model: local_cross_encoder
```

原则：

- 抽取任务用低温便宜模型。
- 最终日报润色用较强模型。
- rerank 尽量本地模型。
- 已处理文档不重复调用 LLM。

---

### 方案 C：内容指纹缓存

每个输入段落计算 hash：

```python
content_hash = sha256(text_fixed + prompt_version + schema_version)
```

如果 hash 不变，则复用：

```text
观点抽取结果
证据分类结果
embedding
摘要结果
```

表：

```sql
CREATE TABLE task_cache (
    cache_key TEXT PRIMARY KEY,
    task_type TEXT,
    input_hash TEXT,
    prompt_version TEXT,
    model TEXT,
    output_json TEXT,
    created_at TEXT
);
```

这不是泛泛“加强缓存”，而是明确缓存粒度：

```text
ASR segment级
note section级
view extraction级
prediction extraction级
embedding chunk级
```

---

### 方案 D：长日报生成使用“材料包压缩”

长日报允许长，但给 LLM 的中间材料仍要控制。

不要把所有 ASR 全塞给最终生成模型，而是：

```text
原始证据完整保存
→ 每个 ViewCard 内部做局部摘要
→ 最终报告引用摘要 + 关键原文
→ 附录再展开完整原文
```

这样既保留追溯性，又控制 token。

---

## 6.4 预期收益

1. 磁盘成本明显下降。
2. LLM 成本可控。
3. 失败重试减少浪费。
4. 日报仍能保持完整证据链。

---

## 6.5 工作量/成本估算

| 项目 | 工作量 |
|---|---:|
| 音频清理 | 1 天 |
| task_cache | 2-3 天 |
| LLM 任务策略 | 1-2 天 |
| 本地 rerank | 2-4 天 |
| 成本统计表 | 1-2 天 |
| 总计 | 1-2 周 |

---

# 7. 最高价值优先落地路线图

下面按“先解决实盘最痛点”的顺序安排。

---

## 第一阶段：建立“观点证据链”基础

### 目标

让日报不再只有结论，而是每个观点都有来源、原文、理由、例证。

### 要做

1. 新增 `EvidenceItem` 数据结构。
2. ASR 输出改为 segment JSONL，保留时间戳。
3. 升级 `view_extractor.py`：
   - 抽取观点。
   - 抽取支撑理由。
   - 抽取例证。
   - 抽取风险条件。
4. 日报改为 ViewCard 渲染。
5. post_check 增加硬规则：
   - 无证据不输出强观点。
   - 无原文引用降级。
   - 无风险条件标记为不完整。

### 预期效果

日报质量立刻提升，从“摘要”变为“证据型日报”。

### 工作量

约 2 周。

---

## 第二阶段：分析师历史回测 MVP

### 目标

让日报能回答：

> 这个人过去这么说过几次？后来对了还是错了？

### 要做

1. 建 `prediction_events`、`market_outcomes`、`analyst_scores` 三张表。
2. 从现有 `structured_views.jsonl` 回填预测事件。
3. 用行情数据验证：
   - 个股。
   - 指数。
   - 已有映射的核心板块。
4. 先支持：
   - 看多 / 看空。
   - 1周 / 1月。
   - correct / wrong / neutral。
5. 日报中加入历史表现表格。

### 预期效果

用户可以把分析师观点和历史准确率结合起来看，实盘价值大幅提高。

### 工作量

约 3 周。

---

## 第三阶段：RAG 升级为投研证据检索

### 目标

让系统不再只检索相似文本，而是检索：

```text
当前观点 + 原始证据 + 历史预测 + 市场验证
```

### 要做

1. 建 Evidence Index / View Index / Prediction Index。
2. 实现 hybrid retrieval：
   - BM25。
   - 向量。
   - 实体过滤。
   - 时间过滤。
   - 历史预测召回。
3. 输出 EvidencePack。
4. 日报 pipeline 只消费 EvidencePack。

### 预期效果

长日报生成稳定性提升，证据更全，幻觉更少。

### 工作量

约 2-3 周。

---

## 第四阶段：数据管线工程化

### 目标

让系统稳定运行，不靠人工盯脚本。

### 要做

1. 用 SQLite 替代 `monitor_state.json`。
2. 多频道配置化，覆盖钱博士自己频道。
3. `pipeline_jobs` 状态机。
4. LLM 自动故障切换。
5. `system_status.py` 监控脚本。
6. 音频清理策略。

### 预期效果

系统可靠性提升，磁盘占用下降，人工维护成本下降。

### 工作量

约 2 周。

---

## 第五阶段：完整回测体系增强

### 目标

从 MVP 回测升级为可长期积累的分析师能力评价系统。

### 要做

1. 支持条件观点。
2. 支持板块指数/代表股组合映射。
3. 支持多周期评分。
4. 支持近 30/90/180 天动态能力。
5. 支持分析师风格标签：
   - 短线强。
   - 中线强。
   - 个股强。
   - 宏观弱。
   - 容易追高。
6. 日报中生成“可信度校正”。

### 预期效果

系统形成核心护城河：不只是听观点，而是知道谁在什么场景下更值得信。

### 工作量

约 4-6 周。

---

# 8. 总结：最应该优先改什么

如果只选三个最高价值优化点：

## 第一，日报从“文本生成”改成“ViewCard + EvidenceChain”生成

这是满足用户第一个痛点的核心。

没有证据链，日报再漂亮也不能辅助实盘。

---

## 第二，建立 PredictionEvent 回测数据库

这是满足用户第三个痛点的核心。

必须把每个分析师的历史判断转成可验证事件，并用市场数据逐一验证。

---

## 第三，RAG 从 chunk 检索升级为 EvidencePack 检索

这是保证长日报完整性和可追溯性的核心。

RAG 不应只返回相似文本，而应返回：

```text
观点、原文、理由、例证、历史同类判断、回测结果、冲突证据
```

完成这三项后，钱博士Agent会从“财经直播摘要工具”升级为：

> **面向实盘决策的可追溯投研Agent系统**。