#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ask_gpt_validator_debug.py — 裸 POST 看 gpt 完整返回，定位 __PREMIUM_FAILED__ 根因。"""
import requests, yaml, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ask_gpt_validator import PROMPT  # 复用同一 prompt

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
p = cfg["llm"]["premium"]
key = open(p["api_key_file"]).read().strip()
url = f"{p['api_base'].rstrip('/')}/chat/completions"
body = {"model": p["model"], "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.3, "max_tokens": p.get("max_tokens", 3500)}
print("prompt字符数:", len(PROMPT))
try:
    r = requests.post(url, headers={"Authorization": f"Bearer {key}",
                                    "Content-Type": "application/json"},
                      json=body, timeout=180)
    print("HTTP", r.status_code)
    txt = r.text
    print("响应长度:", len(txt))
    print("响应前1200字符:\n", txt[:1200])
except Exception as e:
    print("EXC", type(e).__name__, e)
