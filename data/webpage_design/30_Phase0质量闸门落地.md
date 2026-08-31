# 30_Phase0数据质量闸门落地.md — 观点库版本化 + 确定性清洗（已执行）

> 执行：老手 | 依据：29_方案 + gpt-5.6-sol 评审（28_）
> 分工：复杂判定规则（validator）= gpt-5.6-sol 出方案，我落地；其余确定性脚本我写
> 状态：✅ 4 步全部落地并验证

---

## 交付清单（`scripts/`，全部确定性、零 LLM）

| 脚本 | 职责 | 结果 |
|---|---|---|
| `import_views_to_db.py` | jsonl → view_raw（immutable）+ 备份 + md5 留底 | 导入 11311 行，md5=e242558... |
| `timestamp_validator.py` | 确定性 timestamp 校验分类 | 见分布 |
| `resolve_bv_id.py` | source_file 提 BV 补齐 | 补 10262，MISSING_BV 1049 |
| `recompute_metrics.py` | 4 指标 + evidence_link + 报告 | 见下 |

## 数据库
- `data/evidence/qianboshi_quality.db`：view_raw / view_quality_issue / view_provenance / view_evidence_link

## timestamp 判定分布（全量 11311 条）
```
valid             6770 (59.9%)     格式合法
normalized        1003 (8.9%)      规范化（去括号/补零/秒格式转HH:MM:SS）
unit_ambiguous    1619 (14.3%)     秒/分>59（00:02:82 等，不进位，导候选）
invalid_format    1310 (11.6%)     无法解析
out_of_duration    605 (5.3%)      超时长（疑转写截断低估时长，待复核）
reversed             4              start>end
```
可锚定（valid+normalized 且 BV 有 transcript）≈ **6817**（60.3%）

## 4 指标（gpt 定义）
| 指标 | 结果 |
|---|---|
| 1 可解析率 | 68.7% (7773/11311) |
| 2 资产命中率 | 90.7% (bv_id 确定 10262) |
| 3 时间窗口命中率 | 60.3% (6817 anchored) |
| 4 文本证据命中率 | **PENDING** — 技术命中 1496/6817，5295 留 LLM 阶段确认 |

- `view_evidence_link` 生成 **48593** 条下钻关联
- 报告：`data/evidence/quality_report.md`

## 下钻链验证（真实命中）
```
观点"中长线：看多🐂📈" → BV1Zz7W6yEHo 15:17-15:20
  → 原文 [917s-920s] 偷偷票 增长50%
  → 原文 [920s-922s] 80% 最后100%
```
验证通过：观点可下钻到 ASR 原话时间点（Phase 0 验收线达成）。

## 关键踩坑（gpt+我）
1. **初版正则漏秒单位 `s`** → 100% orphan → 加 `\s*s?\s*` 修复
2. **括号 `\(` 写成强制** → 无括号输入全 invalid → 改 `\(?`
3. **分隔符字符类 `[-–~]` 里 en-dash+tilde 成反向区间** → 正则只匹配到 `00:15:17` 就停 → 弃大正则改"split 分隔符 + 两端各自解析单点"
4. **`00:02:82` 秒>59 不能自动进位**（gpt 红线，可能是紧凑毫秒）→ 判 unit_ambiguous
5. **fluxionai 长输出非流式必 524**（记忆）→ validator 评审用 stream=True 才稳定
6. **view_provenance.duration_ms 用 transcript MAX(end_ms) 可能低估**（转写截断）→ out_of_duration 605 需复核真实时长
7. **1 条 view_id 重复**：11312 行导入 11311（INSERT OR IGNORE 去重）

## 红线守住
- ✅ structured_views.jsonl 只读，md5 前后一致（备份在 data/views/backup/）
- ✅ 不猜 BV（MISSING_BV 标 unanchored）
- ✅ 模糊不硬修（00:02:82 标 unit_ambiguous 非进位）
- ✅ 本阶段零 LLM（validator 规则来源 gpt，执行是确定性代码）

## 下一步（待拍板）
1. 修 out_of_duration 误判：用 audio 文件时长/B站API 取代 transcript MAX(end_ms) 估算
2. 文本证据命中率（指标4）真实化：用 gpt-5.6-sol 检索候选原文→选 quote→segment 定时间（LLM 阶段）
3. 补 MISSING_BV 1049：analyst+date 反查当天 BV（确定性，不猜文本）
4. reasoning_unit 语义切段 + claim 反链（gpt 路线第3步）
