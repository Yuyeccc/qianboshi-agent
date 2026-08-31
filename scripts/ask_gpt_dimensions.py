#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ask_gpt_dimensions.py — 请 gpt-5.6-sol 评审：qianboshi 该增加哪些维度（借鉴龟龟两套体系）。"""
import re, json, yaml, requests
from pathlib import Path

PROMPT = """你是投资研究 Agent 架构顾问。我在给"qianboshi"财经 Agent 增加分析维度，请你从下面两套成熟体系里判断：**哪些维度值得吸收、优先级怎么排、怎么落地、哪些不该抄**。

【qianboshi 现状】独立财经 Agent，灵魂=有原始证据/条件化推理/确定性计算/可复盘记忆的认知内核。核心是**分析师直播观点**挖掘：五对象链 raw_asset(视频)→transcript_segment(136万段含时间戳)→reasoning_unit→claim(观点)→report。已建：观点库11312条(分析师/立场/证据原文/实体)下钻命中60%；timestamps校验分类；BV资产身份补齐。已有"多空对照/用户决策复盘/行情数据"。是**观点驱动+实时追踪**，不是财报估值。

【体系A：OpenJury 质量裁决】四棒角色对抗(行业专家→主研Lead→反方Opposition→法官Judge→修复Repair)；八议题(商业模式/护城河/管理层治理/资本配置/结构性风险/鬼故事传闻核查/硬否决候选/数据质量身份核对)；source_authority 四级证据(TierA官方→B专业→C研报→D线索，决定能否支撑重大结论)；因果主线(最多收敛3条)；六维画像(业务经济性/竞争地位/经营趋势/现金质量/财务韧性/资本纪律，仅展示)；确定性估值公式 GG(动态穿透回报率)/II(市场门槛)/OwnerCash/价阶(观察仓=定价/重仓/标准仓)；**确定性数据层=AI禁改写数值、禁心算**；角色物理隔离；硬性机器门(自动重算+逐字节校验)。

【体系B：Turtle 估价筛选】四因子pipeline：factor1资产质量与商业模式→factor2穿透回报率粗算(TopDown)→factor3精算(BottomUp)+现金质量审计→factor4估值安全边际(以factor3为锚)；tushare确定性数据为主+yfinance降级；渐进式披露(因子规则按需加载防context爆炸)；每因子完成立即Checkpoint写盘防丢失；支付率必须用年报附注禁yfinance字段。

【请你输出，务实话少，给可执行判断】
1. 从A/B里，qianboshi 最该吸收哪 5-6 个维度？（按对qianboshi价值排优先级）每个说一句"为什么适合我们"
2. 哪些维度**不该抄**（因为qianboshi是观点驱动非财报估值，或会丢差异化护城河）？
3. 具体怎么落地：推荐维度对应我们哪张表/哪个模块（asset卡/claim/evidence/reasoning_unit/calc/compliance）？给字段级建议
4. 建议一次先加哪 2 个维度最见效（不超过3500字）？"""

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
            pl = line[5:].strip()
            if pl == "[DONE]":
                break
            try:
                delta = json.loads(pl)["choices"][0]["delta"].get("content", "")
                if delta:
                    content += delta
            except Exception:
                pass
    print("content字符:", len(content))
    Path(r"C:/tmp/gpt_dimensions_output.md").write_text(content, encoding="utf-8")
    print("已存 C:/tmp/gpt_dimensions_output.md")
except Exception as e:
    print("EXC", type(e).__name__, e)
