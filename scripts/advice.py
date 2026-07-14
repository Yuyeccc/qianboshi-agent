#!/usr/bin/env python3
"""
钱博士Agent — 每日投资建议生成器（v2.0）

核心逻辑:
  1. 采集市场数据（yfinance + RAG + 持仓 + 标的池）
  2. 构造完整上下文
  3. 调用 DeepSeek/OpenRouter API 生成真正的分析判断
  4. AI 的推理能力是建议的核心，不是模板格式化

用法:
    python scripts/advice.py                          # 实时API生成
    python scripts/advice.py --output file            # 保存到桌面+data目录
    python scripts/advice.py --dry-run                # 只看上下文，不调API
"""
import argparse
import json
import os
import sys
import requests
import random
from datetime import datetime, date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path.home() / "AppData/Local/hermes/skills/research/qianboshi-agent/scripts"))


# ═══════════════════════════════════════════
# API 配置
# ═══════════════════════════════════════════

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

def call_llm(system_prompt, user_prompt, api_key=None):
    """调用 LLM API 生成内容，优先 DeepSeek，回退 OpenRouter"""
    
    key = api_key or DEEPSEEK_API_KEY or OPENROUTER_API_KEY
    if not key:
        return None

    # 尝试 DeepSeek
    try:
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 4000,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        else:
            print(f"[WARN] DeepSeek error: {resp.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"[WARN] DeepSeek failed: {e}", file=sys.stderr)

    # 回退 OpenRouter
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek/deepseek-v4",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 4000,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        else:
            print(f"[WARN] OpenRouter error: {resp.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"[WARN] OpenRouter failed: {e}", file=sys.stderr)

    return None


# ═══════════════════════════════════════════
# 数据采集
# ═══════════════════════════════════════════

SECTOR_RATINGS = {
    "半导体设备": "最高确定性🥇——资本开支写在文件里，扩产周期2-4年",
    "英伟达供应链": "最高确定性🥇——AI基建投资持续1-2年",
    "光模块": "最高确定性🥇——业绩翻倍、产品升级驱动",
    "创新药": "中等确定性🥈——增长慢但确定，防御品种",
    "黄金": "中等确定性🥈——期货坚挺，金股背离是机会",
    "PCB": "中等确定性🥈——电子布>覆铜板>钻针>PCB",
    "电网设备": "中等确定性🥈——近期悄悄走强",
    "机器人": "中等偏下🥉——资金驱动，波动大",
    "商业航天": "中等偏下🥉——确定性高但不是现在",
    "有色": "中等偏下🥉——半周期半成长，看商品价格",
    "MLCC": "观望⚠️——代理商囤货，业绩兑现不了",
    "光纤": "观望⚠️——已按27年PE估值画饼",
    "存储周期": "谨慎⚠️——周期顶部，PE最低时卖",
    "消费": "不推荐❌——当前非主线",
    "医疗器械": "不推荐❌——集采+海外限制",
    "汽车": "不推荐❌——竞争太激烈",
}

RISK_SIGNALS = [
    "缩量创新高——价格新高但成交量萎缩",
    "加速上涨后放量砸盘——场子散了",
    "不该涨时涨了——透支多头精力",
    "散户情绪一致性乐观——人人觉得还能涨=危险",
    "涨停家数<100家——行情可能走坏",
]


def collect_context():
    """采集上下文（跳过yfinance实时行情，非交易时段必挂）
       核心数据源：框架评级 + RAG + 持仓记录
    """
    ctx = {
        "date": datetime.now().strftime("%Y-%m-%d %A"),
        "indexes_note": "非交易时段，实时指数未获取",
        "portfolio": {},
        "tracking": [],
        "rag_views": [],
        "sector_ratings": SECTOR_RATINGS,
        "risk_signals": RISK_SIGNALS,
    }

    # 持仓（从文件读，不拉实时价）
    try:
        pf_path = PROJECT_DIR / "data" / "portfolio.json"
        if not pf_path.exists():
            pf_path = SCRIPT_DIR.parent / "portfolio.json"
        pf = json.loads(pf_path.read_text(encoding="utf-8"))
        for code, info in pf.get("holdings", {}).items():
            ctx["portfolio"][code] = {
                "name": info.get("name", code),
                "shares": info.get("shares", 0),
                "cost": info.get("avg_cost", 0),
                "price_note": "非交易时段，现价未获取",
            }
    except:
        pass

    # RAG 查询主要板块
    try:
        from query_rag import QianboshiRAG
        rag = QianboshiRAG()
        for sec in ["光模块", "半导体设备", "创新药", "机器人", "黄金", "大盘"]:
            results = rag.query(sec, top_k=1)
            if results:
                r = results[0]
                ctx["rag_views"].append({
                    "sector": sec,
                    "source": r.get("source", "?")[:20].replace(".md", ""),
                    "score": r.get("score", 0),
                    "content": r.get("content", "")[:200],
                })
    except:
        pass

    return ctx


# ═══════════════════════════════════════════
# 构造 prompt
# ═══════════════════════════════════════════

def build_prompt(ctx):
    """构造 system prompt + user prompt"""
    
    sys_prompt = """你是钱博士投资顾问系统的分析引擎。你的工作是：
基于每日市场数据、钱博士分析框架、多源观点，生成一份结构化的投资建议。

核心原则：
1. 数据驱动——每一句判断都要有数据支撑
2. 不预测——而是给出"什么条件下应该怎么做"
3. 框架优先——用钱博士的确定性评级和逃顶信号体系做分析骨架
4. 个性化——结合用户的持仓给出具体操作建议
5. 可溯源——每条逻辑都能追溯到数据或框架

输出格式要求：
- 用中文，简洁直接
- 包含：市场概览、板块分析（分确定性等级）、持仓诊断、关注机会、风险提醒
- 每条建议附带逻辑依据
- 板块分析必须区分：确定性高（🥇🥈）、可观察（🥉⚠️）、回避（❌）
- 风险提醒必须引用逃顶信号体系的具体信号
"""

    # 构造上下文
    ctx_parts = [f"日期: {ctx['date']}\n"]

    # 市场状态
    ctx_parts.append(f"【市场状态】\n  {ctx['indexes_note']}\n")

    # 持仓
    if ctx["portfolio"]:
        ctx_parts.append("【用户持仓】")
        for code, info in ctx["portfolio"].items():
            ctx_parts.append(f"  {info['name']}({code}) {info['shares']:.0f}份 成本{info['cost']} {info.get('price_note','')}")
        ctx_parts.append("")

    # RAG 观点
    if ctx["rag_views"]:
        ctx_parts.append("【钱博士最近观点（RAG检索）】")
        for v in ctx["rag_views"]:
            ctx_parts.append(f"  [{v['sector']}] 来源{v['source']} 匹配度{v['score']:.0%}")
            ctx_parts.append(f"    {v['content'][:150]}")
        ctx_parts.append("")

    # 框架评级
    ctx_parts.append("【钱博士分析框架 - 板块确定性评级】")
    for sec, rating in ctx["sector_ratings"].items():
        ctx_parts.append(f"  {rating}")
    ctx_parts.append("")

    # 逃顶信号
    ctx_parts.append("【逃顶信号体系（需组合判断）】")
    for s in ctx["risk_signals"]:
        ctx_parts.append(f"  · {s}")

    user_prompt = "\n".join(ctx_parts)
    user_prompt += """

---
基于以上数据，请生成一份今日投资建议。要求：
1. 先概述当前市场状态
2. 按确定性等级分析各个板块（🥇🥈推荐关注、🥉⚠️可观察、❌回避）
3. 对用户的持仓给出具体操作判断（持有/加仓/减仓/止损+理由）
4. 指出今天值得关注的具体机会（板块+具体标的）
5. 检查逃顶信号是否触发
6. 给出参考仓位建议

格式自由，但每一条判断必须有逻辑依据。不要写废话。"""

    return sys_prompt, user_prompt


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="输出上下文JSON（供agent调用API用）")
    args = parser.parse_args()

    ctx = collect_context()

    if args.json:
        # agent 模式：输出 JSON，agent 负责调 API
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
        return

    # 独立模式：直接输出数据+模板
    sys_prompt, user_prompt = build_prompt(ctx)
    print("=== SYSTEM PROMPT ===")
    print(sys_prompt)
    print("\n=== USER PROMPT ===")
    print(user_prompt)


if __name__ == "__main__":
    main()
