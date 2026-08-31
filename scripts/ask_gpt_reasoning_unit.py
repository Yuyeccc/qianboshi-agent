#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ask_gpt_reasoning_unit.py — 请 gpt-5.6-sol 设计 #6 reasoning_unit 语义归并方案。"""
import re, json, yaml, requests
from pathlib import Path

PROMPT = """你是 Agent 架构 + 语义分割专家。我在做 qianboshi（财经观点认知内核）的 #6：把转录文本归并为 reasoning_unit（语义推理单元），作为 claim 的载体。请给我**可落地的设计**。

【现状 · 五对象链】raw_asset(视频)→transcript_segment(164万段)→reasoning_unit→claim→report。
【当前数据】
1. transcript_segment：faster-whisper 细颗粒，**平均段长1.9秒/9字**（55% <2s、42% 2-5s），太碎不能当语义单元。
2. candidate_sentence：我已做**确定性预聚合**（句末标点/段间gap硬切+逗号软断+超长软切），单BV产生**860句**，平均56字，时长跨度合理。仍有无标点口语长句（>60字无法软切）。
3. view_evidence_annotation：已用 gpt-5.6-sol 标注 **501条观点**（每条：claim原文 + quote(逐字) + 时间锚start/end_ms + evidence_authority(A/B/C/D) + inference_type(fact/interpretation/correlation/hypothesis/causal_claim/forecast) + topic(因果主线) + supported + match_quality）。

【#6 目标】把 candidate_sentence（句子）聚合为 reasoning_unit（语义推理单元），一条 claim 可以承载一个或多个 reasoning_unit，可反链到原始句子/段/时间。

【请你设计，务实话少，给可执行方案】
1. **reasoning_unit 语义定义**：什么算一个 unit（如"一个完整的观点陈述/判断+依据"）；何时句子该独立成 unit、何时合并（连续/因果/转折/同一标的）
2. **LLM 归并规则**：输入一段候选句子序列（每个带 start/end/text/topic），LLM 怎么判断归并边界、输出什么 JSON 结构（unit 边界、unit 主题、inference_type、所属标的、支撑判断）
3. **reasoning_unit 表字段**：对齐 claim 反链 + 复用已有维度（inference_type/topic/authority 从 annotation 继承）
4. **规模控制（关键）**：全量 164万段归并成本爆炸。建议先做**观点锚点归并**（以已标注的501条观点为锚，把其 quote 窗口内的句子聚成 unit，规模可控）还是全量？给成本/收益判断
5. **落地步骤**：确定性预切已有；LLM 归并怎么接入（一次处理一个窗口/多个 unit），checkpoint 防丢失
6. **边界 case**：口语无标点长句、一段话多次提同一标的、跨时间段同一观点、多人讨论（单一主播场景可忽略）"""

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
p = cfg["llm"]["premium"]
key = open(p["api_key_file"]).read().strip()
url = f"{p['api_base'].rstrip('/')}/chat/completions"
body = {"model": p["model"], "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.3, "max_tokens": 3500, "stream": True}
print("prompt字符:", len(PROMPT))
r = requests.post(url, headers={"Authorization": f"Bearer {key}",
                                "Content-Type": "application/json"},
                  json=body, stream=True, timeout=200)
print("HTTP", r.status_code)
if r.status_code != 200:
    print(r.text[:300]); raise SystemExit
content = ""
for line in r.iter_lines():
    if not line or not line.startswith(b"data:"):
        continue
    pl = line[5:].strip()
    if pl == b"[DONE]":
        break
    try:
        delta = json.loads(pl.decode("utf-8"))["choices"][0]["delta"].get("content", "")
        if delta:
            content += delta
    except Exception:
        pass
print("content字符:", len(content))
Path(r"C:/tmp/gpt_reasoning_unit.md").write_text(content, encoding="utf-8")
print("已存 C:/tmp/gpt_reasoning_unit.md")
