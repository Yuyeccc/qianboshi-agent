#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ask_gpt_validator_stream.py — stream=True 调用 gpt-5.6-sol，稳定拿 timestamp_validator 规则。
fluxionai 长输出非流式必 524 → 必须 stream=True 逐段收。"""
import re, json, yaml, requests
from pathlib import Path

PROMPT = """你是解析校验算法专家。请给**确定性、不依赖LLM**的直播转录时间戳校验器(timestamp_validator)的可落地规则。**总输出严格控制在2800字以内**，只给关键可判定规则和伪代码，不要展开每类成因的详细思路，不要客套。

输入：timestamp_raw(字符串，如 `00:11:22-00:11:31`、`00:02:82`秒位>59、`(00:02:36-00:02:58)`带括号、`15:17-15:20`)、duration_ms(视频总时长或None)。
# 请给：
1. 解析正则 + 字段映射：覆盖 HH:MM:SS / MM:SS / MM:SS.mmm / 带括号 / 分隔符 -、–、~；标注每字段语义
2. 状态机(判定顺序)：valid / normalized / invalid_format / out_of_duration / reversed / unit_ambiguous / unresolvable，先判啥后判啥
3. `00:02:82` 秒位>59：成因有哪几种(秒被当分/毫秒误写/直接错)，为何不直接进位成00:03:22 → 判哪个 status
4. 单位混淆(毫秒被当秒/帧当秒)启发式规则
5. start>end、end>duration、start>duration 各自判定
6. 归一化统一输出格式
7. 8个 tricky 边界case + 各自应判 status 和一句原因

务实话少，给能直接写代码的规则。"""

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
p = cfg["llm"]["premium"]
key = open(p["api_key_file"]).read().strip()
url = f"{p['api_base'].rstrip('/')}/chat/completions"
body = {"model": p["model"], "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.3, "max_tokens": 3500, "stream": True}
print("prompt字符:", len(PROMPT))

try:
    r = requests.post(url, headers={"Authorization": f"Bearer {key}",
                                    "Content-Type": "application/json"},
                      json=body, stream=True, timeout=200)
    print("HTTP", r.status_code)
    if r.status_code != 200:
        print(r.text[:300]); raise SystemExit
    content = ""
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
                delta = obj["choices"][0]["delta"].get("content", "")
                if delta:
                    content += delta
            except Exception:
                pass
    print("finish内容字符:", len(content))
    Path(r"C:/tmp/gpt_validator_output.md").write_text(content, encoding="utf-8")
    print("已存 C:/tmp/gpt_validator_output.md")
except Exception as e:
    print("EXC", type(e).__name__, e)
