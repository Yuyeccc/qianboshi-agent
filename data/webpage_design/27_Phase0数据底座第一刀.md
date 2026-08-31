# 27_Phase0数据底座第一刀.md — transcript_segment 结构化重建

> 执行：老手 | 日期：2026-08-29
> 背景：Phase 0 数据底座止损第一刀 = 核查 ASR JSON 保真度 → 重建结构化 transcript_segment
> 验收线：任一日报观点可下钻 claim→reasoning_unit→ASR 时间点

---

## 一、ASR 保真度核查结论

| 项目 | 现状 |
|---|---|
| 分段时间戳 | ✅ 完好，内嵌 txt 行首 `[12.80s -> 14.60s] 文本` |
| 独立结构化 JSON | ❌ 无，只存 `*_transcript_corrected.txt` 文本 |
| 词级时间戳 | ❌ 无（faster-whisper `word_timestamps=False`） |
| 纠错 | ✅ batch_asr_fix 纯文本替换，不动时间戳行 |

**结论**：不用重转写，写解析器把内嵌时间戳重建为 segment 即可。段级时间戳足够下钻定位，词级后续可选补。

## 二、交付1：transcript_segment_indexer.py（重建 + 落库）

- 路径：`scripts/transcript_segment_indexer.py`
- 输入：`transcripts/*_transcript_corrected.txt`（缺则 raw）
- 输出：SQLite `data/evidence/qianboshi_evidence.db` `transcript_segment` 表 + 归档 `bv_analyst.json`
- 字段：id/raw_asset_id/source/order_idx/speaker/start_ms/end_ms/text/asr_confidence/correction_status/raw_file
- **source 双路权威**：`bv_source_map.json`（900条）优先 → 缺的用观点库 analyst 回填（补171个）
- **解析健壮性**：`[x.xxs -> y.yys]` 标准 + `-->` 变体 + 行首截断兜底；孤儿只留原文不丢
- ⚠️ **踩坑**：初版正则漏了数字后 `s` 单位 → 100% 全 orphan；加 `\s*s?\s*` 后 0.01%（全量 0.00%）

## 三、全量结果（51s）

```
文件 1081（1080 有段，1个0行）
segment 1,364,250   orphan 4（0.00%）
独立 BV 1,074   已知分析师 11
```

## 四、交付2：verify_downdrill.py（验收：观点→原文下钻）

- 路径：`scripts/verify_downdrill.py`
- 读观点库 `data/views/structured_views.jsonl`（11312 条），timestamp(MM:SS)→秒→查 transcript_segment 重叠段

**验收结果**：
```
观点总数 11312
  timestamp 可解析 8864            （2448 无 timestamp）
  BV 在 transcript 库 7893          （971 条 source_bv 为空 → 无源观点）
  timestamp 命中原文段 6494         （可下钻口径 6494/7893 ≈ 82%）
  BV 有但 ts 未命中 1399            （timestamp 标注垃圾）
```

**缺口性质（Phase 0 止损点）**：
1. 2448 条观点无 timestamp（无源观点）
2. 971 条 source_bv 为空（无法溯源）
3. 1399 条 timestamp 标错：**秒位超 59**（`00:02:82`、`00:08:92`）、**超音频时长**（BV1oTM16CEdq 音频仅387s 却标到 25分）→ LLM 生成 timestamp 质量差

## 五、下一步选项（待拍板）

- **A**：修观点库 timestamp —— 解析 `秒位>59` 归一化 + 超音频时长清标 NULL（风险：改现有观点库）
- **B**：evidence_extractor —— 把 transcript_segment 切成 reasoning_unit（语义段），再挂 claim 反链 evidence_ids
- **C**：补 2448 无 timestamp 观点的时间锚（重抽 timestamp，贵模型 sol）
- 建议顺序：A（清垃圾）→ C（补缺）→ B（推理单元）使下钻覆盖拉满

## 六、复用备忘

- **运行索引**：`env -u PYTHONPATH python scripts/transcript_segment_indexer.py --overwrite`（幂等，重跑覆盖）
- **验收**：`env -u PYTHONPATH python scripts/verify_downdrill.py`
- **环境**：必须 `env -u PYTHONPATH`（Hermes 劫持 python 会污染）；Python 子进程用 `/c/Python314/python.exe`
