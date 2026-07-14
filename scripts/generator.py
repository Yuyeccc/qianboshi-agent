#!/usr/bin/env python3
"""generator.py - 由 agent 调用，采集数据→调API→生成建议"""
import subprocess, json, os, requests
from datetime import date
from pathlib import Path

# 1. 采集上下文
r = subprocess.run(
    [r'C:\Python314\python', r'E:\qianboshi-agent\scripts\advice.py', '--json'],
    capture_output=True, text=True, timeout=60
)
ctx = json.loads(r.stdout)

# 2. 构造 prompt
sys_prompt = """你是钱博士投资顾问系统的分析引擎。基于市场数据和钱博士框架生成投资建议。

核心原则：数据驱动、不预测只给条件、框架优先、个性化、可溯源。

必须输出以下内容（简洁直接，每条有依据）：
1.【当前市场状态】
2.【板块分析】分三级：🥇🥈推荐关注(带逻辑和具体标的)、🥉⚠️可观察、❌回避
3.【持仓诊断】用户持仓怎么处理
4.【关注机会】今天最值得看的方向
5.【逃顶信号检查】
6.【参考仓位】"""

parts = [f"日期: {ctx['date']}", ""]
if ctx["portfolio"]:
    parts.append("【用户持仓】")
    for c, i in ctx["portfolio"].items():
        parts.append(f"  {i['name']}({c}) {i['shares']:.0f}份 成本{i['cost']} {i.get('price_note','')}")
    parts.append("")
if ctx["rag_views"]:
    parts.append("【钱博士最近观点】")
    for v in ctx["rag_views"]:
        parts.append(f"  [{v['sector']}] {v['source']} 匹配{v['score']:.0%}")
        parts.append(f"    {v['content'][:150]}")
    parts.append("")
parts.append("【钱博士板块确定性评级】")
for sec, rating in sorted(ctx["sector_ratings"].items()):
    parts.append(f"  {rating}")
parts.append("")
parts.append("【逃顶信号体系】")
for s in ctx["risk_signals"]:
    parts.append(f"  · {s}")
parts.append("")
parts.append("---基于以上信息生成今日投资建议---")

user_prompt = "\n".join(parts)

# 3. 调 API
key = os.environ.get('OPENROUTER_API_KEY') or ''
resp = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    json={
        "model": "deepseek/deepseek-v4",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4000,
    },
    timeout=120,
)

if resp.status_code == 200:
    result = resp.json()["choices"][0]["message"]["content"]
    today = date.today().isoformat()
    output = f"📊 钱博士投资顾问简报 | {ctx['date']}\n{'='*60}\n🤖 AI分析 | 数据: 钱博士RAG+框架\n⚡ 不构成投资建议\n\n{result}"
    desk = Path.home() / "Desktop" / f"钱博士投资建议_{today}.md"
    desk.write_text(output, encoding="utf-8")
    print(output)
    print(f"\n--- 已保存到桌面 ---")
else:
    print(f"API Error: {resp.status_code}")
    print(resp.text[:500])
