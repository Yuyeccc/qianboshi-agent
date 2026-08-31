#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ask_gpt_validator_save.py — 裸 POST，解析 content 存文件，看 finish_reason 判断截断。"""
import requests, yaml, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ask_gpt_validator import PROMPT

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
p = cfg["llm"]["premium"]
key = open(p["api_key_file"]).read().strip()
url = f"{p['api_base'].rstrip('/')}/chat/completions"
body = {"model": p["model"], "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.3, "max_tokens": p.get("max_tokens", 3500)}  # 安全上限3500
try:
    r = requests.post(url, headers={"Authorization": f"Bearer {key}",
                                    "Content-Type": "application/json"},
                      json=body, timeout=200)
    print("HTTP", r.status_code)
    data = r.json()
    ch = data["choices"][0]
    fin = ch.get("finish_reason")
    content = ch["message"].get("content") or ""
    print("finish_reason:", fin)
    print("content 字符数:", len(content))
    print("tokens(approx):", len(content) // 4)
    out = Path(r"C:/tmp/gpt_validator_output.md")
    out.write_text(content, encoding="utf-8")
    print(f"已存 {out} （{out.stat().st_size} 字节）")
except Exception as e:
    print("EXC", type(e).__name__, e)
