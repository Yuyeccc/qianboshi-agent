# 总判断

**不建议把 qianboshi-agent 的生产主链路整体迁移到 DSH。**

更合理的方案是：

> **保留 Hermes 作为生产调度与业务自动化层，先把 qianboshi 的 MCP 能力接入 DSH，再视需要开发一个轻量 DSH 插件，把 DSH 作为交互式研究工作台。**

DSH 的价值主要在于：

- 快速组合模型、工具、记忆、日志和 Agent Loop
- 适合交互式探索、调试和演示
- 通过插件和能力 seam 替换局部实现
- 让 Agent 框架本身成为可观察、可扩展的实验平台

而 qianboshi 当前最重要的能力不是“能不能再套一层 Agent”，而是：

- 稳定采集
- GPU ASR
- 结构化抽取
- RAG 检索
- 盘前日报生成
- 飞书推送
- 决策记录
- 到期复盘
- 定时任务和失败恢复

这部分已经形成了真实业务闭环，迁移到一个开发者预览阶段、存在破坏性变更的框架，收益未必覆盖风险。

---

# 1. DSH 与 Hermes 的核心差异

## DSH 的核心优势

### 1.1 “一切皆插件”带来的可替换性

DSH 的插件化不是简单的“增加几个工具”，而是把以下部分都放到插件体系中：

- 模型适配器
- 工具注册表
- 会话日志
- Agent Loop
- Web/headless profile
- 文件系统、Shell、沙箱等能力
- 遥测和事件处理

这使 DSH 更像一个**可组合的 Agent 运行时**。

例如，理论上可以替换：

```text
本地 Shell
    -> 远程执行沙箱

本地文件系统
    -> 受限工作区

默认 LLM
    -> DeepSeek API / 本地模型 / 多模型路由

默认 Agent Loop
    -> 带预算限制、审批机制、领域规则的 Loop
```

它的价值不在于“插件数量更多”，而在于：

> 以后替换一个基础能力时，不必修改整个 Agent 主循环。

### 1.2 能力 seam 适合做基础设施替换

Service Definition / Provider / Consumer 三角，适合把能力边界显式化。

对 qianboshi 来说，比较有价值的 seam 可能包括：

```text
MarketDataProvider
    -> B站采集实现
    -> 本地缓存实现
    -> 测试桩实现

ResearchStore
    -> SQLite
    -> PostgreSQL
    -> 只读快照

ExecutionProvider
    -> 本地分析任务
    -> 远程 GPU Worker
    -> 异步任务队列

LLMProvider
    -> deepseek-v4-flash
    -> deepseek-v4-pro
    -> 本地推理模型
```

但是，这种设计只有在你确实需要替换 Provider 时才产生实际收益。单纯为了“全部插件化”而改造，容易变成架构工作本身。

### 1.3 事件模型适合调试 Agent 行为

DSH 把会话事实、Agent 步骤、能力调用区分开，这对以下问题有帮助：

- 模型为什么选择了某个工具
- 哪一步发生了失败
- 工具返回后 Agent 如何继续
- 一次研究会话调用了哪些数据
- 哪些输出最终进入报告
- 当前结果是实时计算还是读取缓存

对投研系统来说，事件链可以辅助实现：

```text
session_id
    -> query
    -> retrieved_view_ids
    -> tool_calls
    -> model_decisions
    -> generated_claims
    -> final_report
```

这比单纯保存最终回答更适合做研究过程审计。

---

## Hermes 的现实优势

根据你描述的现状，Hermes 已经具备了 qianboshi 所需的生产编排能力：

- cron 定时调度
- MCP 工具暴露
- 飞书消息集成
- 会话记忆
- 技能库
- 定时采集、复盘和站点更新
- 与现有数据管道直接连接

这类能力虽然不一定像“一切皆插件”那样架构上漂亮，但对生产系统更重要：

- 是否能准时执行
- 失败后是否可重试
- 是否有幂等处理
- 是否能控制成本
- 是否能避免重复推送
- 是否能记录任务状态
- 是否能处理 GPU 和外部 API 不可用

因此两者并不是简单的“DSH 更先进，Hermes 更落后”。

可以这样理解：

| 维度 | DSH | Hermes |
|---|---|---|
| 主要定位 | 可组合 Agent 运行时、研究工作台 | 已接入业务的生产 Agent 编排器 |
| 核心优势 | 插件化、能力替换、事件驱动、交互式调试 | 已有定时任务、MCP、飞书、记忆、技能 |
| 适合场景 | 探索、调试、多工具交互、框架扩展 | 稳定运行、业务闭环、定时自动化 |
| 对 qianboshi 的直接收益 | 交互式研究和可观察性 | 已经支撑当前生产流程 |
| 主要风险 | 预览阶段、破坏性变更、生态成熟度 | 可能缺少标准化的能力替换模型 |
| 迁移必要性 | 低 | 当前系统已经可运行 |

DSH 的“全插件”架构是**潜在工程收益**，Hermes 的 cron/MCP/飞书/技能/记忆是**已经兑现的业务收益**。

---

# 2. 四种结合方式评估

## a. 完全迁移到 DSH

### 迁移内容

大致需要重新处理：

```text
Hermes cron
    -> DSH profile / 外部调度器 / 自定义调度插件

Hermes MCP 工具
    -> DSH ctx.tools 注册

Hermes 会话记忆
    -> DSH session/event/persistence 机制

Hermes 技能库
    -> DSH plugin 或 profile

飞书推送
    -> DSH notification/plugin 或外部 service

采集任务
    -> DSH tool / job runner / 外部 worker

ASR 和 GPU 流程
    -> DSH tool 调用现有 Python 服务

日报与复盘
    -> DSH Agent Loop 或专用任务插件
```

关键问题是：**你可能只是把现有业务逻辑重新包进 DSH，而没有得到业务能力提升。**

### 实际收益

可能得到：

- 一个统一的 Agent 插件运行时
- 更方便的交互式工具调用
- 更完整的 Agent 事件日志
- 更容易接入 DSH 生态插件
- 作品集里有框架级集成经历

### 实际风险

1. **业务调度语义可能被 Agent Loop 替代**

定时采集、日报生成、到期复盘，本质上是确定性工作流。它们不应该依赖模型临时决定是否执行。

2. **故障边界重新设计**

例如：

```text
ASR 成功，但结构化失败
结构化成功，但 ChromaDB 写入失败
日报生成成功，但飞书推送失败
推送成功，但任务状态未落库
```

这些状态需要明确的重试和补偿机制，不能只依赖 Agent 继续尝试。

3. **数据迁移和状态迁移**

需要处理：

- SQLite 表结构和历史数据
- ChromaDB collection
- 9727 条 structured views
- 11011 个 RAG chunks
- 历史决策日志
- 已完成和未完成的复盘任务
- 飞书推送去重状态

4. **框架预览阶段风险**

DSH 已明确存在破坏性变更警告。生产系统一旦绑定其内部插件 API，后续升级可能带来：

- 插件接口修改
- profile 配置修改
- 事件名称和字段变化
- 工具生命周期变化
- Web UI 集成方式变化

### 成本估计

在现有代码质量较好、业务逻辑可以服务化的前提下：

- 最小可运行迁移：约 `2-4 周`
- 生产级迁移：约 `4-8 周或更久`
- 后续维护成本：高于当前方案
- 测试重点：任务恢复、幂等、失败补偿、数据一致性、推送去重

### 结论

**不值得作为当前第一步。**

除非你有明确目标：

- 要开发 DSH 插件并参与生态
- 要研究 Agent Runtime 本身
- Hermes 已经无法满足扩展需求
- 计划把 qianboshi 做成通用 Agent 产品，而不是个人生产系统

否则这属于“迁移框架”，不是“提升产品”。

---

## b. DSH 作为独立研究界面或前端

这是最值得优先尝试的方案。

### 目标架构

```text
DSH Web UI
    |
    | DSH Plugin / MCP Client
    |
qianboshi MCP Gateway
    |
    +-- structured_views 查询
    +-- asset_cards 查询
    +-- debate_cards 查询
    +-- 决策日志查询
    +-- RAG 检索
    +-- 生成研究简报
    +-- 触发复盘
    |
SQLite / ChromaDB / 已有服务
```

DSH 负责：

- 交互式对话
- 工具选择
- 会话过程展示
- Agent 事件观察
- 研究问题探索
- 临时组合多个查询工具

qianboshi 继续负责：

- 数据采集
- ASR
- 数据清洗
- 结构化抽取
- RAG 索引
- 日报流水线
- 决策到期复盘
- 飞书自动化

### 适合暴露给 DSH 的工具

建议优先暴露只读和低风险工具：

```text
search_structured_views
get_asset_card
get_debate_card
search_rag_chunks
get_recent_creator_opinions
compare_asset_views
get_user_decision_history
build_research_brief
```

谨慎暴露写操作：

```text
create_user_decision
mark_decision_for_review
trigger_daily_report
send_feishu_message
rerun_ingestion
```

写操作应该经过：

- 参数校验
- 用户确认
- 权限判断
- 幂等键
- 超时控制
- 审计日志
- 失败状态回写

不要让 DSH Web UI 默认拥有：

```text
删除数据
任意执行 Shell
重跑全量采集
重复发送飞书
修改历史决策
```

### 工作量

如果现有 MCP 工具已经稳定：

- 启动 DSH Web 并连接 MCP：约 `1-3 天`
- 加鉴权、超时、审计和错误映射：约 `3-7 天`
- 做成可演示的研究界面：约 `1-2 周`
- 做到长期可靠运行：约 `2-3 周`

### 实际价值

这会给 qianboshi 增加一个新的使用方式：

```text
自动化系统：
晚上自动采集、生成日报、推送飞书、到期复盘

交互式系统：
白天询问某资产、检索观点、比较冲突、追踪历史决策
```

这两类工作流互补，而不是互相替代。

### 需要注意的边界

DSH Web UI 不应该成为你的正式作品集网站前端替代品。

你当前的 FastAPI + React 网站负责：

- 项目叙事
- 数据展示
- 作品集信息架构
- 运行结果和系统架构说明

DSH Web UI 负责：

- 现场交互
- Agent 运行过程
- 工具调用
- 研究问答

两者定位不同。

---

## c. 把 qianboshi 封装成 DSH 插件

这是最适合展示工程能力的中等投入方案。

### 插件职责

插件不应该重新实现采集、RAG、报表等业务逻辑，而应该做适配层：

```text
DSH Plugin
    -> 注册 qianboshi 工具
    -> 转换 DSH 输入输出格式
    -> 注入 session_id / user_id / trace_id
    -> 设置超时和权限
    -> 将工具调用映射到现有 MCP/API
    -> 将结果转成适合模型消费的结构
```

核心业务继续位于 qianboshi service：

```text
qianboshi-core
    -> ResearchService
    -> DecisionService
    -> RetrievalService
    -> ReportService
    -> ReviewService
```

### 推荐的插件分层

```text
@qianboshi/dsh-plugin
    |
    +-- tools/
    |     +-- searchViews
    |     +-- retrieveEvidence
    |     +-- compareAssets
    |     +-- getDecisionHistory
    |     +-- buildBrief
    |
    +-- adapters/
    |     +-- MCP client
    |     +-- HTTP client
    |     +-- local service client
    |
    +-- policy/
    |     +-- read-only defaults
    |     +-- confirmation rules
    |     +-- timeout limits
    |
    +-- telemetry/
          +-- trace mapping
          +-- audit events
```

### 工具设计原则

不要把一个“大而全”的工具直接暴露给模型：

```text
run_qianboshi_pipeline(action: string, args: object)
```

这种工具虽然开发快，但会导致：

- 参数不可发现
- 模型容易传错参数
- 权限控制粗粒度
- 审计日志不清晰
- 后续难以演示工具设计能力

应该使用明确的领域工具：

```text
search_structured_views({
  query,
  asset,
  creator,
  time_range,
  limit
})

compare_asset_views({
  asset,
  start_date,
  end_date,
  include_conflicts
})

get_decision_history({
  asset,
  status,
  limit
})

build_research_brief({
  asset,
  question,
  evidence_limit
})
```

返回结果也不要直接倾倒完整数据库记录，而应返回模型可消费的结构：

```json
{
  "query": "某资产近期风险变化",
  "evidence": [
    {
      "view_id": "view_123",
      "date": "2026-08-01",
      "creator": "UP主A",
      "claim": "……",
      "confidence": 0.78,
      "source_url": "……"
    }
  ],
  "truncated": false,
  "next_cursor": null
}
```

### 工具流水线中的关键钩子

可以利用 DSH 的 pre-execute / execute / post-execute 做：

```text
pre-execute:
    - 校验参数
    - 检查用户权限
    - 判断工具是否只读
    - 注入 trace_id
    - 设置预算和超时

execute:
    - 调用现有 MCP 或 HTTP 服务
    - 不直接操作 SQLite/ChromaDB

post-execute:
    - 过滤敏感字段
    - 截断过长文本
    - 记录耗时和结果摘要
    - 保存 evidence_id
    - 标记失败类型
```

这比单纯“把函数注册成工具”更有工程含量。

### 重要的幂等设计

对于 `trigger_daily_report` 和 `send_feishu_message`，必须带业务幂等键：

```text
report_date + report_type + recipient
```

重复调用时应返回：

```text
already_completed
```

而不是再次生成或再次推送。

对于 `mark_decision_for_review`，可以使用：

```text
decision_id + review_due_at
```

作为幂等条件。

### 工作量

- 基础工具插件：`3-5 天`
- 加入权限、审计、事件映射、错误处理：`1-2 周`
- 加入测试、Docker、配置文档、演示 profile：`2-3 周`

如果 DSH API 仍频繁变化，应把 DSH 适配层限制在单独目录中，避免污染 qianboshi 核心代码。

---

## d. 不结合，维持现状

在以下情况下，不结合反而是最优解：

1. 你当前主要目标是求职，而不是研究 DSH Runtime。
2. Hermes 已经稳定运行，且没有明确的功能缺口。
3. 近期需要补齐测试、部署、监控、数据血缘或作品集表达。
4. DSH 的插件 API 仍在快速变化。
5. DSH 只能重复已有功能，不能新增实际用户价值。
6. 你没有时间承担第二套 Agent Runtime 的维护成本。

当前 qianboshi 的独立价值已经很高：

```text
真实数据源
    -> GPU ASR
    -> 结构化观点
    -> RAG
    -> 盘前日报
    -> 投研决策
    -> 决策复盘
```

这是一个完整的 AI 应用系统，不是简单的聊天机器人。

如果当前还存在以下问题，优先级都高于接入 DSH：

- 采集失败后是否自动恢复
- 任务状态是否可追踪
- 抽取结果是否有 schema 校验
- 报告是否保存证据引用
- RAG 是否评估召回质量
- 模型输出是否有版本记录
- 飞书推送是否幂等
- 复盘是否能区分模型错误和市场结果
- 站点展示是否能解释系统真实运行过程

---

# 3. 对求职作品集的价值

## 现有 Hermes 流水线更能证明什么

现有系统可以证明你具备：

- AI 应用端到端落地能力
- 多阶段流水线编排能力
- 音频、ASR、LLM、RAG、数据库的集成能力
- GPU 资源和异步任务处理经验
- 定时任务和外部系统集成经验
- 业务闭环设计能力
- 结果追踪和自动复盘意识
- 真实生产系统的稳定性思维

这比“我接入了一个热门 Agent 框架”更有说服力。

尤其对于国内 AI 应用或工程开发实习，面试官通常更关心：

- 你是否真正跑过系统
- 失败怎么处理
- 数据如何进来
- 结果如何验证
- 为什么选择某个模型
- 如何控制延迟和成本
- 如何避免 Agent 乱调用工具
- 如何处理重复任务和脏数据

Hermes 在这里不是减分项。只要你能解释它的边界和设计取舍，它可以体现你不是盲目追逐框架。

## DSH 集成能增加什么

一个设计良好的 DSH 集成，可以额外证明：

- 能阅读和适配新型框架
- 能理解插件生命周期
- 能设计 Service Provider/Consumer 边界
- 能封装稳定的领域工具
- 能做工具权限、审计和幂等
- 能把已有系统开放给通用 Agent
- 能区分生产自动化和交互式研究

但前提是集成有合理的问题背景。

优秀的表达方式是：

> Hermes 负责确定性的生产调度和通知，DSH 负责交互式研究与工具探索。通过 DSH 插件将 qianboshi 的检索、证据比较和决策历史能力暴露出来，同时保留原有数据和任务边界。

较弱的表达方式是：

> 因为 DSH 很热门，所以把项目迁移到了 DSH。

## 18.6 万 star 是否加分

会带来一定的注意力，但不是核心竞争力。

它可能加分的地方：

- 说明你关注了最新 Agent 基础设施
- 说明你能快速理解新框架
- 说明你有开源生态意识

它不会自动证明：

- 你理解 Agent 架构
- 你的工具设计合理
- 系统真的可靠
- 项目有真实用户价值
- 你解决过生产问题

如果只是把项目启动在 DSH Web UI 中，面试官很可能追问：

- 为什么需要 DSH？
- Hermes 已经有什么不足？
- 哪部分被 DSH 替换了？
- 为什么不直接使用现有 MCP？
- DSH 的插件 seam 在你的项目中解决了什么问题？
- 如果 DSH API 变化，如何降低迁移成本？

你能回答这些问题，集成才是加分项。

---

# 4. 推荐实施方案

## 推荐结论

采用：

```text
Hermes = 生产自动化和调度层
qianboshi = 领域数据与业务能力层
DSH = 可选的交互式研究层
```

不要让 DSH 接管当前生产主链路。

## 推荐分阶段路线

### 阶段一：先做 DSH 独立验证

目标是验证“交互式研究”是否真正有价值。

保留现有：

```text
Hermes cron
采集链路
ASR
结构化抽取
SQLite
ChromaDB
日报
飞书
决策复盘
```

让 DSH 只访问：

```text
search_structured_views
search_rag_chunks
get_asset_card
get_debate_card
get_decision_history
build_research_brief
```

验证三个问题：

1. DSH 是否比现有网站更适合探索式研究？
2. Agent 是否能根据证据进行多步检索？
3. 工具调用和事件日志是否能帮助调试研究流程？

如果这三个问题没有明显答案，就停止集成，不继续迁移。

### 阶段二：做一个隔离的 DSH 插件

插件只负责适配：

```text
DSH ctx.tools
    -> qianboshi MCP Gateway
```

不要让插件直接依赖：

```text
SQLite 文件路径
ChromaDB 内部 collection
Python 模块内部函数
本地 GPU 进程
```

这样可以保证 qianboshi 继续独立运行，也能降低 DSH 升级带来的影响。

建议目录结构：

```text
qianboshi/
  core/
  services/
  mcp/
  pipelines/
  web/
  dsh-plugin/
    src/
      tools/
      adapters/
      policy/
      telemetry/
    package.json
    README.md
```

### 阶段三：补充可展示的工程能力

重点不是增加更多插件，而是补齐以下机制：

- 工具 schema
- 工具权限
- 读写分离
- 超时和取消
- 幂等键
- trace_id 关联
- 事件审计
- 证据引用
- 错误分类
- 结果截断和分页
- 测试桩 Provider
- 本地开发 profile

可以增加一个测试 Provider：

```text
RealResearchStore
MockResearchStore
```

这样能展示 DSH 能力 seam 的实际用法，而不是只展示表面接入。

### 阶段四：把集成写进作品集

作品集不应只写：

```text
接入 DeepSeek Harness
```

应该写成：

```text
采用双运行时架构：
Hermes 负责任务调度、飞书通知和决策复盘；
DSH 作为交互式研究 Agent，通过插件化工具访问结构化观点、
RAG 证据和历史决策，并使用 pre/post-execute 进行权限、
审计、超时和幂等控制。
```

最好附上一个可视化链路：

```text
用户问题
  -> DSH Agent
  -> qianboshi research tools
  -> evidence retrieval
  -> claim comparison
  -> research brief
  -> optional decision record
```

并明确说明为什么不迁移生产调度：

> 定时采集和日报推送是确定性工作流，因此继续由 Hermes 执行；DSH 只处理需要交互式推理的研究任务。

这句话本身就能体现架构判断力。

---

# 5. 主要风险与控制措施

## 框架绑定风险

**风险：** DSH 预览阶段 API 变化导致插件失效。

**控制：**

- DSH 代码集中在适配层
- qianboshi 核心不依赖 DSH 类型
- 通过 MCP/HTTP 访问业务服务
- 锁定 DSH 版本
- 为插件添加最小回归测试
- 不让 DSH 接管关键定时任务

## 工具越权风险

**风险：** Agent 误触发重跑、写入或推送。

**控制：**

- 默认只读
- 写工具需要显式确认
- 高风险工具单独 profile
- 工具级权限和用户级权限分离
- 发送飞书必须使用幂等键
- 禁止任意 Shell 和任意 SQL

## 财经内容可信度风险

**风险：** Agent 把模型推断当作原始观点，或者把检索结果错误归因给 UP 主。

**控制：**

- 每条观点保留 `view_id`
- 返回来源、时间、UP 主和原文片段
- 报告中的结论关联 evidence IDs
- 区分“原始观点”“模型归纳”“模型推断”
- 记录模型版本、提示词版本和检索参数

## 性能与成本风险

**风险：** DSH Agent 为了回答一个问题进行过多检索或重复调用。

**控制：**

- 设置最大步数
- 设置工具调用预算
- 限制单次返回条数
- 使用 cursor 分页
- 对相同查询缓存
- 对高成本工具要求显式调用
- `flash` 用于检索编排，`pro` 用于复杂总结

## Web 暴露风险

**风险：** DSH Web UI 被直接暴露到公网，导致工具和数据泄露。

**控制：**

- 默认绑定 `127.0.0.1`
- 通过反向代理和认证访问
- 不直接暴露数据库
- 生产环境只开放白名单工具
- 记录所有写操作
- 将 DSH 研究界面与作品集静态站点隔离

---

# 最终建议

按优先级排序：

1. **不迁移 Hermes 的生产主链路。**
2. **先用 DSH 连接现有 MCP，验证交互式研究场景。**
3. **验证有效后，再开发 `qianboshi-dsh-plugin`。**
4. **插件只访问 qianboshi 服务，不直接侵入数据库和流水线。**
5. **把 DSH 集成定位为架构扩展和研究工作台，而不是全面替换。**
6. **作品集重点仍然放在真实数据、可靠流水线、证据链和决策复盘上。**

最终结论：**保留Hermes，渐进接入DSH**
