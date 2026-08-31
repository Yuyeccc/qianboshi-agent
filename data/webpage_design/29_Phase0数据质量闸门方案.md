# 29_Phase0数据质量闸门方案.md — 观点库版本化 + 确定性清洗

> 方案作者：老手 | 日期：2026-08-29
> 依据：gpt-5.6-sol 评审（28_）+ 实测数据口径
> 状态：**待用户审核**（先 plan 后 action）

---

## 0. 一句话目标

在不破坏原始观点的前提下，用**确定性规则**识别并修复观点库的 timestamp 错误、补齐 BV 身份，
建立**可追溯、可复用**的证据锚点层，为后续 reasoning_unit / claim 铺路。

**本阶段绝对不碰 LLM**——所有识别、归一化、补齐都是确定性代码，每一步都给可解释 reason。

---

## 1. 现状口径（实测订正，别信旧数字）

| 指标 | 实测 | 说明 |
|---|---|---|
| 观点总数 | 11312 | JSON 0 坏行 |
| source_bv 空 | **1049** | 大多可由 source_file 确定性补出 |
| source_file 有值 | 11312（100%） | **10263 条文件名直接含 BV** |
| timestamp 真空值 | **494** | 字段真的为空 |
| timestamp 未解析 | 1954 | MM:SS 等格式变体（非真空缺） |
| timestamp 标错 | 1399 | 秒位>59 / 超音频时长 |
| transcript_segment | 1364250 | 已就位（27_） |

**关键洞察**：空 source_bv 的 1049 条里，绝大多数能从 `source_file`（如"任泽平 2026.06.27 BV1Zz7W6yEHo.md"）
用正则提取 BV——**确定性补齐，不用猜、不用 LLM**。

---

## 2. 数据模型（新表，独立库 `data/evidence/qianboshi_quality.db`）

不清空、不覆盖 `structured_views.jsonl`（原始层 immutable），派生层全新表。

```
view_raw          -- 原始观点（jsonl 导入，immutable）
view_quality_issue -- 质量问题清单（逐条，带 reason）
view_provenance   -- 溯源与锚点（归一化 ts + bv_id + 置信度状态）
view_evidence_link -- 观点↔transcript_segment 关联（下钻）
```

### 2.1 `view_raw`（immutable 原始层）
```sql
CREATE TABLE view_raw (
  view_id TEXT PRIMARY KEY,
  raw_json TEXT NOT NULL,          -- 原始完整 JSON 保真
  analyst TEXT, source_bv TEXT, timestamp_raw TEXT, stance TEXT,
  horizon TEXT, claim TEXT, evidence TEXT, view_type TEXT,
  load_ts TEXT DEFAULT (datetime('now'))
);
```

### 2.2 `view_quality_issue`（质量问题）
```sql
CREATE TABLE view_quality_issue (
  view_id TEXT, issue_code TEXT,
  field TEXT, raw_value TEXT, reason TEXT,
  suggested_status TEXT,          -- valid/normalized/invalid_format/out_of_duration/unresolvable
  detected_by TEXT DEFAULT 'ts_validator', detected_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY(view_id, issue_code)
);
```

`issue_code` 枚举：
- `MISSING_BV` / `MISSING_TS`（真空缺）
- `INVALID_TS_FORMAT`（解析失败）
- `TS_SEC_OVERFLOW`（秒位>59）
- `TS_OUT_OF_DURATION`（end 超音频时长）
- `TS_REVERSED`（start>end）
- `TS_UNIT_AMBIGUOUS`（毫秒/帧被当秒）
- `BV_FILE_MISMATCH`（source_file BV 与 source_bv 冲突）

### 2.3 `view_provenance`（溯源锚点，标准化结果）
```sql
CREATE TABLE view_provenance (
  view_id TEXT PRIMARY KEY,
  bv_id TEXT,
  anchor_status TEXT,              -- anchored/partially_anchored/unanchored
  anchor_start_ms INTEGER, anchor_end_ms INTEGER,
  normalized_ts TEXT,              -- 修复后 MM:SS-MM:SS
  anchor_confidence TEXT,          -- high/medium/low
  duration_ms INTEGER,             -- 对应音频时长
  notes TEXT
);
```

`anchor_status` 判定：
- video有transcript + timestamp有效且命中 → `anchored`
- bv_id 确定但 timestamp 无法归一化 → `partially_anchored`
- bv_id 无法确定 → `unanchored`

### 2.4 `view_evidence_link`（观点↔segment 下钻）
```sql
CREATE TABLE view_evidence_link (
  view_id TEXT, segment_id TEXT,
  start_ms INTEGER, end_ms INTEGER,
  match_method TEXT,               -- overlap/exact
  overlap_ms INTEGER,
  PRIMARY KEY(view_id, segment_id)
);
```

---

## 3. timestamp_validator（确定性规则引擎）

输入：`timestamp_raw` + 该 BV 的 `duration_ms`（= transcript_segment max(end_ms)，无 transcript 则 N/A）
输出：`(status, normalized_ts, reason)`

规则（顺序判定，命中即止）：
1. **格式解析**：支持 `HH:MM:SS` / `MM:SS` / `MM:SS.mmm`，允许 `-`分区间；失败 → `invalid_format`
2. **字段越界**：秒/分 >59（如 `00:02:82`）→ `sec_overflow`，**不猜测进位**（gpt 警告），标 invalid 进候选
3. **反向区间**：start>end → `reversed`，交换并记 reason
4. **超出时长**：end > duration_ms 或 start > duration_ms → `out_of_duration`，置 invalid
5. **单位混淆启发式**：若 start ~ duration 的 1000 倍量级，疑毫秒当秒 → `unit_ambiguous`
6. 通过 → `valid`，normalized_ts = 统一 `MM:SS-MM:SS`

归一化输出统一格式：`MM:SS-MM:SS`（对齐 verify_downdrill 的可解析格式）。

**判定原则**：本阶段只做"可信的确定性归一化"，模糊歧义一律标 `unresolvable/invalid` 进候选，不硬修。

---

## 4. resolve_bv_id（确定性补齐）

优先级（从高到低，取第一个确定值）：
1. `source_bv` 已是合法 BV 格式 → 直接用
2. `source_file` / `source_path` 正则提取 `BV[0-9A-Za-z]+`（**覆盖 10263 条**）
3. `source_file` 无 BV → 用 analyst+date+title 与 transcript 文件名做唯一匹配（不能唯一匹配则弃）
4. 均无 → `unanchored`，**绝不根据观点文本猜 BV**（gpt 红线）

输出：`view_provenance.bv_id` 更新 + `view_quality_issue` 记录 MISSING_BV（若原空）。

---

## 5. 验收：4 指标重算（recompute_metrics）

对全部 11312 条算（对齐 gpt 四指标）：
1. **可解析率** = 有有效 timestamp / 总数
2. **资产命中率** = bv_id 确定且 BV 有 transcript / bv_id 确定
3. **时间窗口命中率** = normalized_ts 落进对应 BV transcript 时间范围 / 可解析
4. **文本证据命中率** = 该时间窗 segment 原文是否真正支撑观点（**本阶段先算技术下钻 + 实体关键词粗查，阈值性结论标 PENDING，留给 LLM 阶段**）

产出报告 `data/evidence/quality_report.md`，含：缺口分布 / 修复率 / 4 指标 / 待人工复核清单。

---

## 6. 脚本清单（本阶段交付）

| 脚本 | 职责 | 是否写代码 |
|---|---|---|
| `import_views_to_db.py` | JSONL → view_raw（immutable 层） | 待拍板 |
| `timestamp_validator.py` | 规则引擎 → view_quality_issue + provenance 归一化 | 待拍板 |
| `resolve_bv_id.py` | source_file 提 BV → bv_id 补齐 | 待拍板 |
| `recompute_metrics.py` | 4 指标重算报告 | 待拍板 |

---

## 7. 执行步骤（拍板后）

1. `import_views_to_db.py`（备份 jsonl + 导入，immutable）
2. `timestamp_validator.py`（1399 条自动分类 + 494 真空 + 1954 格式变体归一化）
3. `resolve_bv_id.py`（1049 空 BV 补齐）
4. `recompute_metrics.py`（4 指标报告）
5. 复核：抽 20 条看 reason 是否合理；报告存证

---

## 8. 风险与红线

- ✅ **immutable 红线**：`structured_views.jsonl` 只读，**md5 校验前后一致**；所有修复落派生表
- ⚠️ 归一化可能误判 → 每条带 reason，可人工复核；模糊一律标 invalid 不硬修
- ⚠️ 1049 空 BV 中若 source_file 也无 BV，来源可能是"无源观点" → 标 unanchored 不伪造
- 🔒 本阶段零 LLM，全部确定性；LLM 修复（检索原文/文本证据命中）留到下一阶段
