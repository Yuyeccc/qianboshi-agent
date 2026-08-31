# -*- coding: utf-8 -*-
"""港股创新药多方位分析生成（2026-08-06）：行情+观点 → deepseek-v4-flash → 报告"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_loader import load_config, get_llm_config

ROOT = Path(__file__).resolve().parents[1]

# 1. 行情
with open(ROOT / "data" / "price_trends.json", "r", encoding="utf-8") as f:
    trends = json.load(f)

HK_SYMBOLS = {
    "3069.HK": "翰森制药", "1801.HK": "信达生物", "9926.HK": "康方生物",
    "1877.HK": "君实生物", "9969.HK": "诺诚健华", "1177.HK": "中国生物制药",
    "1093.HK": "石药集团", "9995.HK": "荣昌生物", "1952.HK": "云顶新耀", "2162.HK": "康诺亚",
}

def pct(series, days):
    dates = sorted(series.keys())
    if len(dates) < 2:
        return None
    p0 = series[dates[-1]]["price"]
    target = None
    for d in dates:
        if (date.fromisoformat(dates[-1]) - date.fromisoformat(d)).days >= days:
            target = series[d]["price"]
            break
    return round((p0 - target) / target * 100, 2) if target else None

market_lines = []
for sym, name in HK_SYMBOLS.items():
    series = trends.get(sym)
    if not series:
        market_lines.append(f"- {name}({sym})：行情缺失")
        continue
    dates = sorted(series.keys())
    last = dates[-1]
    p = series[last]["price"]
    chg5 = pct(series, 5); chg10 = pct(series, 10); chg20 = pct(series, 20); chg40 = pct(series, 40)
    highs = max(series[d]["price"] for d in dates)
    lows = min(series[d]["price"] for d in dates)
    market_lines.append(
        f"- {name}({sym})：现价 {p}（{last}）｜5日 {chg5}% 10日 {chg10}% 20日 {chg20}% 40日 {chg40}%｜区间 {lows}~{highs}"
    )
market_str = "\n".join(market_lines)

# 2. 观点（近60天）
cutoff = (date.today() - timedelta(days=60)).isoformat()
kws = ["创新药", "港股", "翰森", "信达", "康方", "君实", "诺诚", "荣昌", "云顶", "康诺亚", "百济", "药明", "生物医药", "BD"]
views = []
with open(ROOT / "data" / "views" / "structured_views.jsonl", "r", encoding="utf-8") as f:
    for ln in f:
        try:
            v = json.loads(ln)
        except Exception:
            continue
        if v.get("date", "") < cutoff:
            continue
        text = (v.get("claim", "") + " " + v.get("logic", "") + " " + str(v.get("entities", "")))[:600]
        if any(k in text for k in kws) and v.get("stance") in ("bullish", "bearish", "risk"):
            views.append(
                {"date": v.get("date"), "analyst": v.get("analyst"), "stance": v.get("stance"),
                 "claim": (v.get("claim") or "")[:100], "logic": (v.get("logic") or "")[:220]}
            )
# 按日期倒序，去重（date+analyst+stance）
seen = set()
views_dedup = []
for v in sorted(views, key=lambda x: x["date"], reverse=True):
    key = (v["date"], v["analyst"], v["stance"], v["claim"][:20])
    if key in seen:
        continue
    seen.add(key)
    views_dedup.append(v)
views_str = "\n".join(
    f"- {v['date']} {v['analyst']} [{v['stance']}] {v['claim']}｜{v['logic']}" for v in views_dedup[:35]
)

# 3. 组装 prompt（模板）
prompt = f"""# 任务：港股创新药板块多方位分析报告（含标的清单）

## 硬性要求
1. **资料时效**：以下观点以近2个月为主，每条带日期；超过2个月的只作背景
2. **数据来源**：行情与观点均为真实数据（下方提供），禁止编造数字
3. **禁止**：不推荐买卖（只整理观点和数据）、不写"近期/最新"模糊词、不使用未提供的价格

## 一、行情走势（近2个月，真实数据）
{market_str}

## 二、分析师观点面（近2个月，带日期）
{views_str}

## 三、分析要求
1. 板块整体判断：港股创新药近2个月表现、驱动因素（从观点中提取）
2. 标的分层清单（用户想买港股创新药，需要标的画像）：
   - 每个标的：现价/区间位置/近期趋势/分析师观点（带日期）/逻辑要点
   - 按"确定性/逻辑硬/估值位置"分层：核心配置型 / 弹性进攻型 / 观察型
3. 多空对照：港股创新药多方逻辑 vs 空方/风险逻辑（每条带来源和日期）
4. 独立分析：观点与行情的交叉验证、值得跟踪的信号
5. 关键位置与验证信号（可量化的2-3个）

## 输出格式
Markdown 报告（标题：港股创新药多方位分析_20260806.md）
开头注明：生成时间、数据来源、非投资建议；结尾注明：不构成投资建议
"""

# 4. 调 pro 生成
llm = get_llm_config(load_config())
import requests

resp = requests.post(
    f"{llm['api_base']}/chat/completions",
    headers={"Authorization": f"Bearer {llm['api_key']}", "Content-Type": "application/json"},
    json={
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 8000,
        "thinking": {"type": "disabled"},
    },
    timeout=300,
)
resp.raise_for_status()
content = resp.json()["choices"][0]["message"]["content"]

out = ROOT / "data" / "reviews" / "港股创新药多方位分析_20260806.md"
out.write_text(content, encoding="utf-8")
print(f"✅ 报告已生成: {out}（{len(content)} 字符）")
print(f"行情标的 {len(HK_SYMBOLS)} 个, 观点 {len(views_dedup)} 条入上下文")
