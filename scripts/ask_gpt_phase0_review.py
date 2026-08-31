#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ask_gpt_phase0_review.py — 把 Phase 0 数据底座现状交给 gpt-5.6-sol 评审，要更优改造路径。"""
import sys, json, yaml
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from llm_fallback import call_premium

PROMPT = """你是资深金融数据工程 + AI Agent 架构顾问，帮我评审一个财经数据底座改造方案。

# 项目背景
我在做"qianboshi"独立财经 Agent（提取B站财经主播直播观点做研究）。它的灵魂是一套拥有**原始证据、条件化推理、确定性计算、可复盘记忆**的认知内核。核心数据模型是**五对象保真链**：
raw_asset(原始视频/音频) → transcript_segment(转录分段,含起止时间) → reasoning_unit(语义推理单元) → claim(观点断言) → research_output(研究报告)
验收目标：**任一日报观点，都能下钻到分析师直播原话的时间点**。

# 当前数据底座现状（Phase 0 第一刀已完成）
- ASR 转录文本：1081 个 `*_transcript_corrected.txt`，每行内嵌时间戳 `[12.80s -> 14.60s] 文本`
- 已重建为结构化 `transcript_segment`（SQLite），**136万段**，字段含 id/raw_asset_id(BV号)/source(分析师)/start_ms/end_ms/text/order_idx
- 观点库 `structured_views`：11312 条带分析师/立场/时间戳/资产实体的观点
- 已打通"观点 → (BV号+timestamp) → 原文段"下钻，可下钻口径下命中率 **82%**

# 三个数据缺口（需止损）
1. **2448 条**观点 timestamp 字段为空（无源观点，无法下钻）
2. **971 条** source_bv 为空（BV号缺失，无法溯源）
3. **1399 条** timestamp 标错（秒位超59如`00:02:82`、超音频时长如音频仅387s却标到25min）→ 是LLM标注的质量垃圾

# 我拟的下一步三选（你评审）
- **A. 清垃圾**：归一化/置 NULL 那 1399 条标错 timestamp（改现有观点库，有风险）
- **B. evidence_extractor**：把 transcript_segment 切成 reasoning_unit（语义切段），再挂 claim 反链
- **C. 补缺**：2448 条无锚观点用贵模型重抽时间锚

# 请你输出（中文，给可执行建议）
1. 三个缺口的**处理优先级**排序与理由（哪些先修、哪些可后置/忽略）
2. 你的**更优改造路径**：如果有比 A→B→C 更好的顺序或做法，说出来
3. **我没考虑到的坑**（比如时间戳与音频时长不一致的深层原因、分段粒度过粗细的取舍、现有观点库字段冲突、下钻精度等）
4. 评价一下"用 LLM 生成 timestamp/切段"这条路是否可靠，是否该换成确定性手段
5. 一句话结论：Phase 0 数据底座最该先做什么

务实话少，直接给判断和可执行步骤，不要客套。"""


def main():
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    llm = cfg.get("llm", {})
    messages = [{"role": "user", "content": PROMPT}]
    resp = call_premium(llm, messages, temperature=0.3, max_tokens=3500)
    if resp is None:
        print("__PREMIUM_FAILED__")
        return
    content = resp["choices"][0]["message"]["content"]
    model = llm.get("premium", {}).get("model")
    print(f"__MODEL={model}__")
    print(content)


if __name__ == "__main__":
    main()
