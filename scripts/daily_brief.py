#!/usr/bin/env python3
"""
钱博士盘前简报 — 集成实时行情 + RAG观点

用法:
    python daily_brief.py                    # 生成简报
    python daily_brief.py --force            # 跳过交易日检查
    python daily_brief.py --verbose          # 详细输出
    python daily_brief.py --push-webhook URL # 推送到飞书
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_data_dir, get_obsidian_path, get_proxy
from query_rag import QianboshiRAG


# ─── 交易日判断 ───────────────────────────────────────────

def is_trading_day():
    today = date.today()
    return today.weekday() < 5

def is_a_stock_session():
    """A股是否在交易时段（北京时间 9:30-15:00）"""
    now = datetime.now()
    return now.weekday() < 5 and 9 <= now.hour < 15 or (now.hour == 9 and now.minute >= 30)

def is_us_stock_session():
    """美股是否在交易时段（北京时间 21:30-次日04:00 夏令时）"""
    now = datetime.now()
    h = now.hour
    return now.weekday() < 5 and (h >= 21 or h < 4)


# ─── 行情数据采集 ─────────────────────────────────────────

def _yf_fetch(symbols, period="2d", timeout=15):
    """批量下载yfinance行情，带超时保护"""
    import yfinance as yf
    import threading

    result = {"data": None, "error": None}

    def _fetch():
        try:
            result["data"] = yf.download(symbols, period=period, progress=False, timeout=timeout)
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout + 5)

    if t.is_alive():
        return None, "timeout"

    if result["error"]:
        return None, result["error"]

    return result["data"], None


def fetch_market_indexes(config):
    """拉取中美六大指数（批量+超时保护）"""
    symbols = ["000001.SS", "399001.SZ", "399006.SZ", "^DJI", "^IXIC", "^GSPC"]
    names = {
        "000001.SS": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指",
        "^DJI": "道琼斯", "^IXIC": "纳斯达克", "^GSPC": "标普500",
    }

    data, err = _yf_fetch(symbols, period="2d", timeout=20)

    if err or data is None or data.empty:
        return {"indexes": [], "error": err or "无数据", "timestamp": datetime.now().strftime("%H:%M")}

    results = []
    for sym in symbols:
        try:
            # Handle MultiIndex columns from batch download
            if isinstance(data.columns, pd.MultiIndex):
                col = data.xs(sym, level=1, axis=1)
            else:
                col = data

            if col.empty or "Close" not in col:
                results.append({"name": names.get(sym, sym), "code": sym, "error": "无数据"})
                continue

            closes = col["Close"].dropna()
            if len(closes) < 1:
                results.append({"name": names.get(sym, sym), "code": sym, "error": "无收盘价"})
                continue

            close = round(float(closes.iloc[-1]), 2)
            prev = round(float(closes.iloc[-2]), 2) if len(closes) >= 2 else close
            chg_pct = round((close - prev) / prev * 100, 2) if prev else 0
            emoji = "🟢" if chg_pct > 0 else ("🔴" if chg_pct < 0 else "⚪")
            results.append({
                "name": names.get(sym, sym), "code": sym,
                "price": close, "change_pct": chg_pct, "emoji": emoji,
            })
        except Exception as e:
            results.append({"name": names.get(sym, sym), "code": sym, "error": str(e)[:50]})

    return {"indexes": results, "timestamp": datetime.now().strftime("%H:%M")}


def fetch_portfolio_status(config):
    """查询持仓盈亏（批量+超时保护）"""
    data_dir = get_data_dir(config)
    pf_path = data_dir / "portfolio.json"
    if not pf_path.exists():
        return {"holdings": [], "empty": True}

    pf = json.loads(pf_path.read_text(encoding="utf-8"))
    holdings = pf.get("holdings", {})
    if not holdings:
        return {"holdings": [], "empty": True}

    codes = list(holdings.keys())
    data, err = _yf_fetch(codes, period="2d", timeout=15)

    if err or data is None or data.empty:
        return {"holdings": [], "empty": True, "error": err or "行情获取失败"}

    results = []
    total_value = 0
    total_cost = 0

    for code in codes:
        h = holdings[code]
        try:
            if isinstance(data.columns, pd.MultiIndex):
                col = data.xs(code, level=1, axis=1)
            else:
                col = data

            closes = col["Close"].dropna()
            if closes.empty:
                results.append({"code": code, "name": h.get("name", code), "error": "无数据"})
                continue

            price = round(float(closes.iloc[-1]), 3)
            shares = h.get("shares", 0)
            cost = h.get("avg_cost", 0)
            mv = round(price * shares, 2)
            cv = round(cost * shares, 2)
            pnl = round(mv - cv, 2)
            pnl_pct = round((pnl / cv * 100), 2) if cv else 0

            total_value += mv
            total_cost += cv

            results.append({
                "code": code, "name": h.get("name", code),
                "shares": int(shares), "cost": cost, "price": price,
                "market_value": mv, "pnl": pnl, "pnl_pct": pnl_pct,
            })
        except Exception as e:
            results.append({"code": code, "name": h.get("name", code), "error": str(e)[:50]})

    total_pnl = round(total_value - total_cost, 2)
    total_pnl_pct = round((total_pnl / total_cost * 100), 2) if total_cost else 0

    return {
        "holdings": results,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "empty": False,
    }


def fetch_tracking_alerts(config):
    """扫描标的池，返回异动列表（批量+超时保护）"""
    data_dir = get_data_dir(config)
    tp_path = data_dir / "tracking_pool.json"
    if not tp_path.exists():
        return {"alerts": [], "gainers": [], "losers": []}

    tp = json.loads(tp_path.read_text(encoding="utf-8"))

    # 汇总所有标的
    all_items = {}
    for section in ["stocks", "etfs", "us_stocks", "cn_indexes", "us_indexes"]:
        for code, info in tp.get(section, {}).items():
            all_items[code] = {"name": info.get("name", code), "market": section}

    if not all_items:
        return {"alerts": [], "gainers": [], "losers": []}

    codes = list(all_items.keys())
    data, err = _yf_fetch(codes, period="5d", timeout=20)

    if err or data is None or data.empty:
        return {"alerts": [], "gainers": [], "losers": [], "error": err}

    gainers = []
    losers = []

    for code in codes:
        meta = all_items[code]
        try:
            if isinstance(data.columns, pd.MultiIndex):
                col = data.xs(code, level=1, axis=1)
            else:
                col = data

            closes = col["Close"].dropna()
            if len(closes) < 2:
                continue

            close = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            chg_pct = round((close - prev) / prev * 100, 2) if prev else 0

            item = {"name": meta["name"], "code": code, "change_pct": chg_pct, "market": meta["market"]}

            if chg_pct >= 4:
                gainers.append(item)
            elif chg_pct <= -4:
                losers.append(item)
        except Exception:
            pass

    return {
        "alerts": gainers + losers,
        "gainers": sorted(gainers, key=lambda x: -x["change_pct"]),
        "losers": sorted(losers, key=lambda x: x["change_pct"]),
    }


# ─── 格式化 ───────────────────────────────────────────────

def fmt_index_row(item):
    if "error" in item:
        return f"  {item['name']:　<6}  ----"
    return f"  {item['emoji']} {item['name']:　<6} {item['price']:>10.2f}  {item['change_pct']:+.2f}%"


def fmt_indexes_section(indexes_data):
    indexes = indexes_data.get("indexes", [])
    if not indexes:
        err = indexes_data.get("error", "")
        if err:
            return f"\n【📊 全球指数】\n  ⚠️ 行情数据暂不可用（{err}）"
        return "\n【📊 全球指数】\n  暂无数据"

    lines = ["", "【📊 全球指数】"]
    # A股
    cn = [i for i in indexes if i.get("code", "").endswith((".SS", ".SZ"))]
    if cn:
        lines.append("  A股：")
        for i in cn:
            lines.append(fmt_index_row(i))
    # 美股
    us = [i for i in indexes if i.get("code", "").startswith("^")]
    if us:
        lines.append("  美股：")
        for i in us:
            lines.append(fmt_index_row(i))
    lines.append(f"  ⏱ 数据时间: {indexes_data.get('timestamp', '?')}")
    return "\n".join(lines)


def fmt_portfolio_section(pf_data):
    if pf_data.get("empty"):
        return ""
    if pf_data.get("error"):
        return f"\n【💼 持仓盈亏】\n  ⚠️ 行情获取失败（{pf_data['error'][:40]}）"

    lines = ["", "【💼 持仓盈亏】"]
    for h in pf_data.get("holdings", []):
        if "error" in h:
            lines.append(f"  {h['name']}({h['code']}) — 无法获取行情")
            continue
        emoji = "🟢" if h["pnl"] > 0 else ("🔴" if h["pnl"] < 0 else "⚪")
        lines.append(
            f"  {emoji} {h['name']}({h['code']}) "
            f"¥{h['price']:.3f} × {h['shares']} "
            f"= ¥{h['market_value']:.0f}  "
            f"{'+' if h['pnl']>0 else ''}{h['pnl']:.0f} ({h['pnl_pct']:+.1f}%)"
        )

    emoji = "🟢" if pf_data["total_pnl"] > 0 else ("🔴" if pf_data["total_pnl"] < 0 else "⚪")
    lines.append(
        f"  ────────────────\n"
        f"  {emoji} 总市值 ¥{pf_data['total_value']:,.0f}  "
        f"总盈亏 {pf_data['total_pnl']:+,.0f} ({pf_data['total_pnl_pct']:+.1f}%)"
    )
    return "\n".join(lines)


def fmt_tracking_section(tracking_data):
    gainers = tracking_data.get("gainers", [])
    losers = tracking_data.get("losers", [])
    if not gainers and not losers:
        return ""

    lines = ["", "【🔔 标的池异动】"]
    if gainers:
        lines.append("  🟢 涨幅>4%:")
        for g in gainers[:5]:
            lines.append(f"    {g['name']}({g['code']}) {g['change_pct']:+.1f}% [{g['market']}]")
    if losers:
        lines.append("  🔴 跌幅>4%:")
        for l in losers[:5]:
            lines.append(f"    {l['name']}({l['code']}) {l['change_pct']:+.1f}% [{l['market']}]")
    return "\n".join(lines)


def fmt_rag_section(rag_results, title, emoji, key, max_items=2, max_chars=150):
    items = rag_results.get(key, [])
    if not items:
        return f"{emoji} {title}\n  暂无数据"

    lines = [f"{emoji} {title}"]
    for r in items[:max_items]:
        content = _clean_rag(r["content"], max_chars)
        lines.append(f"  📌 {r['source']}")
        lines.append(f"  {content}")
        lines.append("")
    return "\n".join(lines)


def _clean_rag(text, max_len=150):
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = text.strip()
    return text[:max_len] + ("..." if len(text) > max_len else "")


def get_random_quote(config):
    """从框架文档取随机语录"""
    skill_refs = Path(__file__).parent.parent / "references"
    framework = skill_refs / "分析框架.md"
    if not framework.exists():
        framework = Path("E:/qianboshi-agent/references/分析框架.md")
    if not framework.exists():
        return "大A是夜店，你是来寻开心的，不是来谈长期恋爱的。"

    text = framework.read_text(encoding="utf-8")
    quotes = re.findall(r'"> (.+?)"', text)
    if quotes:
        import random
        return random.choice(quotes).strip()
    return "牛市里最重要的是跌的时候你能跑，是留住利润。"


# ─── 主简报 ───────────────────────────────────────────────

BRIEF_TEMPLATE = """📊 **钱博士盘前简报** | {date_str}

{indexes}

{portfolio}

{tracking}

━━━━━━━━━━━━━━━━━━━━━━━

{mkt_overview}

{sector}

{risks}

━━━━━━━━━━━━━━━━━━━━━━━
【📖 钱博士经典】
> "{quote}"

━━━━━━━━━━━━━━━━━━━━━━━
🤖 投资研究Agent | 数据: yfinance + RAG(88篇/10位分析师)
⚡ 不构成投资建议 | 投资有风险
"""


def generate_brief(config, rag, skip_market=False):
    """生成完整简报"""
    now = datetime.now()

    # ── 行情数据 ──
    indexes_data = {"indexes": [], "timestamp": now.strftime("%H:%M")}
    pf_data = {"empty": True}
    tracking_data = {"alerts": [], "gainers": [], "losers": []}

    if not skip_market:
        try:
            indexes_data = fetch_market_indexes(config)
        except Exception as e:
            indexes_data = {"indexes": [], "error": str(e)}

        try:
            pf_data = fetch_portfolio_status(config)
        except Exception as e:
            pf_data = {"empty": True, "error": str(e)}

        try:
            tracking_data = fetch_tracking_alerts(config)
        except Exception as e:
            tracking_data = {"alerts": [], "error": str(e)}

    # ── RAG观点（不限来源）──
    rag_results = {
        "大势": rag.query("当前市场环境 牛市 熊市 大盘判断 市场状态", top_k=3),
        "板块": rag.query("看好的板块 确定性最高 板块推荐 重点关注", top_k=3),
        "风险": rag.query("风险提示 逃顶信号 警惕 减仓 注意风险", top_k=3),
    }

    # ── 组装 ──
    date_str = now.strftime("%Y年%m月%d日 %A")
    weekday_cn = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    date_str = now.strftime(f"%Y年%m月%d日 周{weekday_cn}")

    brief = BRIEF_TEMPLATE.format(
        date_str=date_str,
        indexes=fmt_indexes_section(indexes_data),
        portfolio=fmt_portfolio_section(pf_data),
        tracking=fmt_tracking_section(tracking_data),
        mkt_overview=fmt_rag_section(rag_results, "当前大势", "【📌", "大势", max_chars=200),
        sector=fmt_rag_section(rag_results, "重点板块", "【🥇", "板块", max_chars=200),
        risks=fmt_rag_section(rag_results, "风险提醒", "【⚠️", "风险", max_chars=200),
        quote=get_random_quote(config),
    )

    return brief


# ─── 推送 ─────────────────────────────────────────────────

def push_to_feishu(brief, webhook_url=None):
    webhook_url = webhook_url or os.environ.get("FEISHU_WEBHOOK_URL")
    if not webhook_url:
        print("[INFO] 未配置飞书Webhook，仅输出到stdout", file=sys.stderr)
        return False

    import urllib.request

    payload = json.dumps({
        "msg_type": "text",
        "content": {"text": brief},
    }).encode("utf-8")

    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        if result.get("StatusCode") == 0 or result.get("code") == 0:
            print("[OK] 已推送到飞书", file=sys.stderr)
            return True
        print(f"[WARN] 飞书返回异常: {result}", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] 推送失败: {e}", file=sys.stderr)
    return False


# ─── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="钱博士盘前简报")
    parser.add_argument("--force", action="store_true", help="跳过交易日检查")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细模式")
    parser.add_argument("--push-webhook", help="飞书Webhook URL")
    parser.add_argument("--skip-market", action="store_true", help="跳过行情采集（仅RAG）")
    parser.add_argument("--config", help="指定config.yaml路径")
    args = parser.parse_args()

    if not args.force and not is_trading_day():
        print("[INFO] 今天不是交易日（周末），使用 --force 强制运行", file=sys.stderr)
        sys.exit(0)

    config = load_config(args.config)
    rag = QianboshiRAG()

    if args.verbose:
        print("[INFO] 采集行情数据...", file=sys.stderr)

    brief = generate_brief(config, rag, skip_market=args.skip_market)
    print(brief)

    if args.push_webhook or os.environ.get("FEISHU_WEBHOOK_URL"):
        push_to_feishu(brief, args.push_webhook)
