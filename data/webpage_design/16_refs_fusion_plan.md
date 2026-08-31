# Turtle + OpenJury 框架融合方案 — gpt-5.6-sol 评判（2026-08-23）

> 评判对象：turtle-investment-framework（分析流水线）+ open_jury_prompts（多角色研究）
> 评判模型：gpt-5.6-sol（fluxionai），原始输出见下方

## 总判断

两个框架**不应整套移植**：
- Turtle 补强"确定性计算、渐进式上下文、断点续跑、日报呈现"——工程可靠性与可交付性
- OpenJury 补强"观点冲突、证据对称、裁决合同、反方独立性"——研究结论抗偏差能力
- 最值得做的：先建立一条可复现链路 `原始证据 → 确定性行情/统计 → 结构化观点 → 多空裁决 → 决策日志 → 到期复盘`

## 核心机制评判（高价值项）

### Turtle
| 机制 | 价值 | 落点 |
|---|---|---|
| quality_control 确定性预计算 | **极高** | 行情涨跌幅/5日趋势/命中率/观点聚合由 Python 算，LLM 只解释禁算数——当前最明确缺口 |
| 渐进式披露 | 高 | morning_brief 8 章规则拆到 references/，按章加载 |
| Checkpoint | 高 | 每章完成即写盘，失败从最近成功章恢复 |
| 引用合同 [src: CM§N] | 高 | 扩展为 [src: VIEW-xxx]/[src: CM-xxx]/[src: MARKET-xxx] |
| MD→HTML | 中 | 已有 React 渲染链，不引 Jinja2 第二套 |
| coordinator 交互询问 | 中 | 用于决策台补全风险预算/期限，非日报主流程 |

### OpenJury
| 机制 | 价值 | 落点 |
|---|---|---|
| 正反证据对称 | **极高** | debate_cards 从"两观点汇总"升级为"正证/反证/证据强度/缺失证据" |
| 严格 JSON 输出合同 | **极高** | 日报生成改 Pydantic 校验，ID 必须能在 SQLite/JSONL 查到 |
| 确定性数据层只读 | **极高** | LLM 不能改行情/命中率/趋势/观点原文/决策结果——与 Turtle 确定性层共底座 |
| Lead/Opposition 物理隔离 | 高 | 多头/空头分别从同一证据池独立生成，互不读对方输出 |
| 因果收敛 ≤3 主线 | 高 | 每主题最多 3 条"驱动→传导→可观测指标→失效条件" |
| 证据分级 | 中 | 视频项目不伪装官方证据，定义来源等级+unresolved 标记 |
| Repair | 高 | 校验失败先确定性修复，再重试角色，阻止错误进飞书 |

## 已有能力 vs 真实缺口

**已有**：view_id/source_bv/evidence 溯源 ≈ 证据ID；prediction_events 经验校验层；debate_cards 四类研究语义；asset_cards 长期记忆；decision_logs+reviews 决策闭环；9 个 MCP 工具可观测；market_cache.py 确定性行情输入

**缺口**：
1. 行情输入与日报脱节（非交易时段显示 N/A，缓存有美股指数没接进去）
2. 无统一日报中间产物合同（章节/观点/证据/行情/建议缺可校验 JSON 接口）
3. 多空卡非严格独立裁决（多头空头是否独立生成不明，无 Judge 记录）
4. 证据等级/核验状态不统一（source_bv 可追溯但不能表达来源层级）
5. 无按章 Checkpoint 和重跑语义
6. 统计结果未与 LLM 隔离
7. 前端仍是原文阅读器（无行情卡/证据链/多空裁决展示）

## 落地优先级

**P0 可信日报数据管线**
1. report_data.py：生成带 as_of/market_status/数据源/快照哈希的 market_snapshot，统一输出三大指数+AI链+持仓代理+5日趋势；agent.py 非交易时段显示"最近可用收盘价/时间"而非 N/A（工作量：中）
2. report_schema.py：Pydantic 模型覆盖 ReportRun/8章/EvidenceRef/MetricRef/DebateResult，校验 ID 真实存在（中）
3. morning_brief 拆阶段：load_snapshot→aggregate_views→build_evidence_packs→debate→compose→validate→publish，每阶段写 runs/<run_id>/ 下 JSON+日志（中）
4. 8 章规则移 references/report_sections/，主 Prompt 只留流程+合同；每章 Checkpoint；失败从最近成功章恢复（中）

**P1 多空裁决升级**
5. debate_pipeline.py：同一只读 evidence_pack，Bull/Bear 独立生成，互不读对方输出（大）
6. Judge 步骤：输出 ≤3 条因果主线 + stance + disagreement_score + unresolved_items；debate_cards 向后兼容加 causal_chains/bull_evidence/bear_evidence/invalidators（中）
7. 证据来源等级：primary_video/transcript/market_data/user_log/external_official/derived_metric + verified/indirect/unresolved（中）
8. repair.py：校验必填/枚举/证据ID/正反对称/数值一致，失败先修再重试，阻止飞书发布（中）

**P1 作品集接通**
9. FastAPI /api/market-snapshot + /api/reports/{run_id}，React 简报详情页全球市场区块（指数卡+AI链chips+持仓代理+as_of+5日趋势）（中）← 当前正在做
10. 详情页改"结构化章节组件+证据抽屉"：观点旁 view_id，指标旁 metric_id，点击展开来源/时间窗/置信度/支持反证（中）
11. 决策台"采纳/跳过/观察"+理由期限失效条件 → user_decision_logs，到期关联 reviews（中）

**P2 复盘转规则**
12. prediction_events 与 decision_reviews 关联字段扩展，区分分析师命中 vs 用户决策命中（中）
13. 离线回放评估：9727 观点/31320 事件，对比改造前后证据覆盖率/ID有效率/结论稳定性（大）
14. new_rule_learned 生成版本化规则变更，过离线评估才更新 references（大）

## 最小数据流

```
B站视频/字幕 → structured_views.jsonl → evidence_registry（来源等级/核验状态/view_id）
  → quality_control.py/report_data.py（market_snapshot/derived_metrics/view_aggregates）
  → evidence_pack（只读带ID）→ Bull(独立) + Bear(独立) → Judge(≤3因果主线)
  → report_schema校验 → 分章Checkpoint + report JSON
  → FastAPI结构化接口 / 飞书 / React简报
  → user_decision_logs → decision_reviews → 离线评估与候选规则
```

## 作品集最值得突出的一句话

> 系统不是让 LLM"预测市场"，而是把有来源的观点、只读的确定性数据、独立的多空论证和用户决策复盘，组织成一条可重放的研究生产链。

---
*以上为 gpt-5.6-sol 原始评判的提炼整理；原始完整输出保存在本次会话。*
