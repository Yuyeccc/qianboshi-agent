#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ask_gpt_validator.py — 请 gpt-5.6-sol 出 timestamp_validator 判定规则精确方案。"""
import sys, json, yaml
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm_fallback import call_premium

PROMPT = """你是解析/校验算法专家，帮我设计一个**确定性、不依赖 LLM** 的直播转录时间戳校验器（timestamp_validator），给 Python 实现用的精确判定规则。

# 输入
对每条观点记录，输入：
- timestamp_raw: 字符串，LLM 标注的视频内时间区间。例子：`00:11:22-00:11:31`、`00:15:17-00:15:20`、`00:02:82-...`(秒位>59)、`00:25:76-00:26:14`(超音频时长)、`(00:02:36-00:02:58)`(带括号)、`MM:SS` 两段式
- duration_ms: 对应视频/音频总时长（毫秒）。来源：transcript_segment 表该 BV 的 max(end_ms)；无 transcript 则 None
- 该 BV 的 transcript_segment 最小/最大时间范围（可用来判断窗口是否落在有内容的区间）

# 要求输出
1. **timestamp 字符串解析正则 + 字段映射**：要覆盖 HH:MM:SS / MM:SS / MM:SS.mmm / 带括号 / 不同分隔符（-、–、~）等变体；给出 Python regex 和它如何映射到 start_ms/end_ms（考虑两种时间基：HH:MM:SS 的 SS 是秒，MM:SS 的 SS 也是秒，说明每种格式各自的字段语义）
2. **字段越界判定**：秒/分 >59（如 `00:02:82`）到底有哪几种可能的成因（秒被当分/毫秒误写/直接错误），**为什么不建议直接进位**为 `00:03:22`；每种成因对应什么 status
3. **单位混淆检测**：毫秒被当秒（如 `123456ms` 写成 `123456` 秒）、帧号被当秒；给启发式规则和阈值
4. **时长校验**：start>end、end>duration、start>duration 各自怎么判、怎么处理
5. **归一化输出**：统一输出格式建议（如 `MM:SS-MM:SS`），以及 normalized 时间如何算
6. **status 枚举**：valid/normalized/invalid_format/out_of_duration/reversed/unit_ambiguous/unresolvable 的判定树（先判哪个后判哪个）
7. **边界 case 清单**：列 10-15 个你想到的 tricky 输入 + 每个应判什么 status 和原因

务实话少，直接给可落地的规则和伪代码，不要泛泛而谈。这是确定性代码，要求"宁标 invalid 不硬修"，模糊一律给 unresolvable。"""


def main():
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    llm = cfg.get("llm", {})
    messages = [{"role": "user", "content": PROMPT}]
    resp = call_premium(llm, messages, temperature=0.3, max_tokens=3500)
    if resp is None:
        print("__PREMIUM_FAILED__")
        return
    content = resp["choices"][0]["message"]["content"]
    print(f"__MODEL={llm.get('premium',{}).get('model')}__")
    print(content)


if __name__ == "__main__":
    main()
