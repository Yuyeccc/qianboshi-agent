# 28_gpt评审_Phase0数据底座.md — gpt-5.6-sol 数据底座改造建议

> 评审背景：Phase 0 第一刀（transcript_segment 重建 136万段 + 观点下钻 82%）完成后，
> 老手拟 A/B/C 三选，交 gpt-5.6-sol 评审"怎么改更好"。本文为 gpt 输出存档。

---

## 一句话结论（gpt）

> Phase 0 最该先做的**不是继续让 LLM 补 timestamp**，而是建立**不可覆盖的证据版本层**，
> 并用**确定性规则**清理错误时间轴、补齐资产身份，再让 LLM 从候选原文中找证据。

## 一、缺口优先级（gpt 排序，跟老手 A/B/C 不同）

| 优先级 | 缺口 | 处理原则 |
|---|---|---|
| 🥇 第一 | 1399 条错误 timestamp | 最危险=**伪证据**（看似可下钻实则错），但大多可**确定性规则识别**，不需要贵模型；**不覆盖原字段** |
| 🥈 第二 | 971 条 source_bv 为空 | 先判断是否真缺 BV；多数可由 raw_asset_id / transcript 文件名**确定性补出** |
| 🥉 第三 | 2448 条 timestamp 为空 | 属"证据缺失"非"错误"，可后置甚至长期保留为 unanchored，**绝不强行生成** |

gpt 对 1399 的核心警示：`00:02:82` **不要**简单当 `00:03:22`，除非能确认原始标注逻辑；否则标 `invalid_format` 进候选恢复。

## 二、关键建构建议

### 1. 观点库版本化（最重要，别直接改）
```
structured_views   -- 原始观点，immutable 不覆盖
view_quality_issue -- 质量问题
view_provenance    -- 溯源与锚点
view_revision      -- 修复后版本
view_evidence_link -- 观点↔transcript_segment 关联
```

### 2. LLM 不该生成绝对 timestamp
正确架构 = **LLM 找原文 → 确定性系统给时间 → 校验器判有效**
LLM 输出 `quote + candidate_segment_ids + relation`，时间由系统从 segment 算。模型直接输出 `00:12:37` 不可靠。

### 3. source 语义要拆
```
analyst_id / source_channel / raw_asset_id / bv_id / transcript_id
source_bv 改 bv_id（BV 是资产身份不是 source），建唯一约束
```
原因：`source` 同时表示"分析师名/账号名/数据来源"会产生歧义。

### 4. 分段粒度多层级（不要只追求越细越好）
```
transcript_segment -- 原始时间分段（ASR 定，不改写）
sentence_unit      -- 句子级
reasoning_unit     -- 语义推理级（可由多 segment 组成）
evidence_span      -- 观点需要的最小连续证据范围
```
reasoning_unit 是语义组织层，**不能替代**原始 transcript_segment。

### 5. 82% 命中率要拆 4 指标
可解析率 / 资产命中率 / 时间窗口命中率 / **文本证据命中率**（最后者最关键：该时间点原文是否真正支持观点，否则是"技术命中、内容不命中"）。

### 6. claim 类型区分 & 条件化观点
```
quoted_claim / normalized_claim / inferred_claim / analyst_prediction / agent_synthesis
```
inferred_claim 不应声称"原话如此"，要记 inference_rule + supporting/contradicting evidence。
条件化观点不能被压平成无条件多空：应存 `direction/condition/time_horizon/trigger/exception`。

### 7. audio 时长不一致的深层原因（存 raw_asset 多时长）
原视频≠下载音频、裁剪、断流、offset、变速转码、字幕/播放器/音频起点不同 → raw_asset 存
`original/downloaded/asr_duration_ms + trim_offset + timeline_offset + asset_version`。

## 三、gpt 建议的可执行顺序（4 阶段）

1. **第一周·数据质量闸门**：冻结 views；建 view_revision/evidence_link；timestamp 解析归一化 + 时长校验；把 1399 条分"可确定修复/不可确定"；补 bv_id；重算 4 指标
2. **第二·证据解析层**：观点→segment/span（支持多 segment evidence span、quote+上下文窗口），**不急着生成全部 reasoning_unit**；批量复核 11312 条
3. **第三·reasoning_unit + claim**：不改变原始 segment；LLM 只做语义聚合/条件抽取/claim 分类
4. **第四·恢复 2448 缺失 timestamp**：先定资产 BV → 检索候选文本 → LLM 在候选窗口选原文 → segment 定时间 → 低置信进人工

## 四、对老手 A/B/C 的修正
- **A（清 timestamp 垃圾）** ✅ 保留但升级：改造成 version 化 + 确定性 timestamp_validator，不覆盖原字段
- **B（evidence_extractor 切段）** ⭕ 延后到第二阶段，且切分用"确定性预切 + LLM 合并标注"，reasoning_unit 不替代原始段
- **C（用 sol 补 timestamp）** ❌ **方向错**：LLM 不该生成绝对时间。改成"检索候选 → LLM 选原文 → 系统算时间"
