# 31_维度增补_gpt评审.md — qianboshi 该增加哪些维度（借鉴 OpenJury + Turtle）

> 生成：老手整理 gpt-5.6-sol 评审 | 日期：2026-08-29
> 背景：用户下载赛博龟龟两套体系源码，问"怎么增加多的维度好"。gpt 基于 qianboshi 现状（观点驱动 + 五对象链）与两套体系（OpenJury 质量裁决 / Turtle 估价筛选）给维度的吸收/规避/落地判断。

---

## gpt 一句话结论

> qianboshi 不应照搬 A/B 的"完整生产流程"或"估值/价阶"，而应聚焦**加强观点证据链**：证据权威分级 + 推理类型区分 + 实时追踪/多空（这正是我们的差异化）。

---

## 一、最该吸收的 6 个维度（按优先级）

| 优先级 | 维度 | 为什么适合我们 |
|---|---|---|
| **P0** | **source_authority 证据权威分级**（TierA官方→B专业→C研报→D线索，决定能否支撑重大结论） | qianboshi 已建观点+证据链，天然衔接；给每条证据定权威级 |
| **P0** | **身份/数据质量硬门**（timestamps 校验 + BV身份补齐 + 身份/代码/名称/时间一致性校验） | 我们刚做完 timestamp 校验 + BV 补齐，正好升级为通用硬门 |
| **P0** | **推理类型区分**（fact/interpretation/correlation/hypothesis/causal_claim/forecast） | 防止"分析师推测"被当成"事实"，观点驱动最该分清 |
| **P1** | **因果主线**（report 最多收敛 3 条主线，正负面证据对称） | 从大量 claim 中收敛出主线，避免无重点风险清单 |
| **P1** | **结构性风险 + 硬否决标记**（open→monitoring→resolved/expired/confirmed） | 观点易冲突，需结构化风险状态机 |
| **P2** | **确定性计算 + 机器校验**（calc 层，AI 不能改数值，只能改公式/版本窗口重算） | 呼应架构 calc；防模型改事实库 |

## 二、不该抄的（避免丢差异化）

1. **OpenJury 完整多角色陪审团**（Lead/Opposition/Judge/Repair 四棒）——观点驱动不适用全流程；应改"**风险触发式裁决**"（只对高影响/高争议/高不确定性 claim 触发对抗）。
2. **A 的六维画像当主产出**——不是我们差异化；只作企业级补充，**别让每个分析师观点被强标到六维**（会让观点驱动产品变形、压制分析师独特判断）。
3. **GG/II/OwnerCash/价阶体系**——完整估值决策系统，不做qianboshi默认输出。但可保留"**确定性计算**"理念；对估值类判断标"不可计算/需人工/证据不足/风险未闭合"，**不强行转成"能买/需卖/评级为零"**（否则 Agent 越过证据审查给建议）。

## 三、落地字段（gpt 具体建议，对齐我们 25_架构表）

### `asset` 卡加
```
canonical_entity_id / entity_type / ticker / market / identity_status
  (confirmed/ambiguous/unresolved/incorrect)
identity_evidence_ids / source_authority_default / asset_time_start/end / data_quality_status
```

### `evidence` 加
```
evidence_id / source_tier / source_type / authority_basis / directness
quote_text / source_locator(可直接跳转原文时间戳) / asset_id
event_time / publication_time / as_of
supports_claim_ids / contradicts_claim_ids / verification_status / materiality
```

### `reasoning_unit` 加
```
premise_ids / inference_type(fact/interpretation/correlation/hypothesis/causal_claim/forecast)
causal_role / mechanism_text / assumption_ids
alternative_explanation_ids / missing_evidence_ids / invalidation_condition
```

### `claim` 加
```
claim_type / stance / subject_entity_id / horizon
effective_from / effective_to / conditions / invalidation_conditions
causal_node_id / materiality / impact_level / support_level
support_evidence_ids / contradict_evidence_ids
opposition_status / judge_status / repair_status / claim_lifecycle_status
  (draft/published/monitoring/partially_supported/contradicted/invalidated/expired/repaired)
```
⚠️ **不要只留一个 confidence**：拆成 `evidence_confidence / reasoning_confidence / forecast_confidence` 三维。

### `compliance` 加机器门
```
identity_gate / timestamp_gate / source_gate / quote_consistency_gate
numeric_integrity_gate / contradiction_gate / major_claim_support_gate
publication_status / human_review_required / failure_reasons
```
所有落库数值都应标 `calc_id`（来源确定性计算）。

## 四、第一阶段只加这 2 个维度最见效

1. **证据权威分级（source_authority + 直接度）** → 加到 evidence/claim（给现有 11312 条观点的每条证据定 Tier）
2. **推理类型 + 因果主线**（inference_type 区分事实/推测/因果）→ 加到 claim/reasoning_unit（区分"分析师说了什么/算什么论据/在哪条观点主线"）

> 这两项结合，qianboshi 会更清楚"分析师说了什么、这算什么证据、在哪条观点主线里"——正是观点驱动实时追踪这条河。
