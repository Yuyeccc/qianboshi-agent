#!/usr/bin/env python3
"""
钱博士观点验证脚本 — Phase 4 反馈闭环

钱博士的核心输出是板块级观点（光模块/创新药/机器人...），不是个股推荐。
因此验证逻辑：板块观点 vs 板块ETF实际走势。

用法:
    python validate.py                  # 验证所有板块
    python validate.py --sector 光模块   # 单板块
    python validate.py --report         # 读已有日志生成报告
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_data_dir, get_proxy
from query_rag import QianboshiRAG

# ─── 板块↔ETF映射 ─────────────────────────────────────────

# 钱博士经常讨论的板块和对应的可交易ETF
SECTOR_ETFS = {
    "光模块":   {"code": "515060", "name": "光模块ETF"},
    "光通讯":   {"code": "515060", "name": "光模块ETF"},
    "创新药":   {"code": "159992", "name": "创新药ETF"},
    "机器人":   {"code": "562500", "name": "机器人ETF"},
    "半导体":   {"code": "512480", "name": "半导体ETF"},
    "AI":       {"code": "516630", "name": "AI人工智能ETF"},
    "AI应用":   {"code": "516630", "name": "AI人工智能ETF"},
    "芯片":     {"code": "512480", "name": "半导体ETF"},
    "储能":     {"code": "516380", "name": "储能ETF"},
    "新能源":   {"code": "516160", "name": "新能源ETF"},
    "消费电子": {"code": "159732", "name": "消费电子ETF"},
    "PCB":      {"code": "588380", "name": "科创板50ETF"},
    "MLCC":     {"code": "512480", "name": "半导体ETF"},
}

# ─── 观点方向检测 ─────────────────────────────────────────

BULLISH_KW = [
    "看多", "看好", "反弹", "上涨", "买入", "机会", "确定性高",
    "估值低", "底部", "反转", "加仓", "持有", "长期看好",
    "低吸", "景气", "放量", "突破", "牛市", "修复", "调整接近尾声",
    "距离反弹", "即将反弹", "逼空", "还能持续",
]
BEARISH_KW = [
    "看空", "风险", "逃顶", "减仓", "卖出", "调整", "下跌",
    "泡沫", "高估", "过热", "拥挤", "破位", "止损",
    "熊市", "暴跌", "出货", "离场", "谨慎", "大跌", "暴跌",
]


def detect_sentiment(text):
    text_lower = text.lower()
    bull = sum(1 for kw in BULLISH_KW if kw in text_lower)
    bear = sum(1 for kw in BEARISH_KW if kw in text_lower)
    if bull > bear:
        return "bullish", bull
    elif bear > bull:
        return "bearish", bear
    return "neutral", 0


def extract_date_from_source(source):
    m = re.search(r'(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})', source)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


# ─── 行情 ─────────────────────────────────────────────────

def fetch_price(code, from_date):
    """拉取从from_date至今的价格变化（30分钟缓存）"""
    cache_key = (code, str(from_date))
    if not hasattr(fetch_price, "_cache"):
        fetch_price._cache = {}

    if cache_key in fetch_price._cache:
        cached = fetch_price._cache[cache_key]
        if time.time() - cached["ts"] < 1800:
            return cached["data"], None

    try:
        import yfinance as yf
    except ImportError:
        return None, "yfinance 未安装"

    try:
        t = yf.Ticker(code)
        hist = t.history(start=from_date, end=date.today() + timedelta(days=1))
        if hist.empty or len(hist) < 2:
            return None, f"{code} 数据不足"

        sp = float(hist["Close"].iloc[0])
        ep = float(hist["Close"].iloc[-1])
        chg = round((ep - sp) / sp * 100, 2)

        data = {
            "code": code, "from_date": str(from_date), "to_date": str(date.today()),
            "start_price": round(sp, 2), "end_price": round(ep, 2),
            "change_pct": chg, "days": len(hist),
        }
        fetch_price._cache[cache_key] = {"data": data, "ts": time.time()}
        return data, None
    except Exception as e:
        return None, str(e)[:80]


# ─── 判定 ─────────────────────────────────────────────────

def verdict(sentiment, chg_pct):
    if sentiment == "bullish":
        if chg_pct >= 2:
            return "✅ 验证", f"看多+涨{chg_pct:+.1f}%"
        elif chg_pct >= -2:
            return "⏳ 待观察", f"看多但横盘{chg_pct:+.1f}%"
        else:
            return "❌ 打脸", f"看多却跌{chg_pct:+.1f}%"
    elif sentiment == "bearish":
        if chg_pct <= -2:
            return "✅ 验证", f"看空+跌{chg_pct:+.1f}%"
        elif chg_pct <= 2:
            return "⏳ 待观察", f"看空但横盘{chg_pct:+.1f}%"
        else:
            return "❌ 打脸", f"看空却涨{chg_pct:+.1f}%"
    return "⏳ 待观察", f"观点中性，走势{chg_pct:+.1f}%"


def days_ago_str(d):
    if d is None:
        return "?"
    delta = (date.today() - d).days
    if delta == 0: return "今天"
    if delta == 1: return "昨天"
    return f"{delta}天前"


# ─── 板块验证 ─────────────────────────────────────────────

def validate_sector(rag, sector, etf_code, etf_name, verbose=False):
    """验证钱博士对某个板块的观点"""
    # 1. RAG检索板块观点（多取一些，前几个往往是元数据chunk）
    results = rag.query(f"{sector} 观点 走势 判断 看好 风险", top_k=15)

    if not results:
        return {"sector": sector, "etf": etf_name, "code": etf_code,
                "verdict": "⏭ 跳过", "reason": "RAG无相关观点"}

    # 2. 找最佳观点chunk（有方向+有日期，跳过纯元数据chunk）
    best = None
    best_date = None
    best_sentiment = "neutral"
    best_score = 0

    for r in results:
        content = r.get("content", "")
        if len(content) < 40:
            continue

        # 跳过纯元数据chunk（标题+视频链接，无实质观点）
        if re.match(r'^# .+\n\n> .+[|｜]\s*\d{4}', content):
            continue
        if re.match(r'^# .+\n\n> B站', content):
            continue

        d = extract_date_from_source(r.get("source", ""))
        if d is None:
            continue

        s, score = detect_sentiment(content)

        if s != "neutral":
            if best is None or best_sentiment == "neutral" or d > (best_date or date.min):
                best = r
                best_date = d
                best_sentiment = s
                best_score = score
        elif best is None or d > (best_date or date.min):
            if best is None or d > (best_date or date.min):
                best = r
                best_date = d
                best_sentiment = s
                best_score = score

    if best is None or best_date is None:
        return {"sector": sector, "etf": etf_name, "code": etf_code,
                "verdict": "⏭ 跳过", "reason": "无法提取观点日期"}

    # 3. 拉行情
    price_data, err = fetch_price(etf_code, best_date)

    if err or price_data is None:
        return {
            "sector": sector, "etf": etf_name, "code": etf_code,
            "verdict": "⏳ 待观察", "reason": f"行情获取失败: {err}",
            "sentiment": best_sentiment, "view_date": str(best_date),
            "view_age": days_ago_str(best_date),
            "view_source": best.get("source", "?"),
            "view_snippet": best.get("content", "")[:120],
        }

    # 4. 判定
    v, v_reason = verdict(best_sentiment, price_data["change_pct"])

    return {
        "sector": sector,
        "etf": etf_name,
        "code": etf_code,
        "verdict": v,
        "reason": v_reason,
        "sentiment": best_sentiment,
        "sentiment_score": best_score,
        "view_date": str(best_date),
        "view_age": days_ago_str(best_date),
        "view_source": best.get("source", "?"),
        "view_snippet": best.get("content", "")[:150],
        "price": price_data,
    }


def validate_all(config, rag, verbose=False):
    """验证所有已知板块"""
    # 去重（同一ETF只验证一次）
    seen_etfs = set()
    sectors = []
    for sector, etf in SECTOR_ETFS.items():
        if etf["code"] not in seen_etfs:
            seen_etfs.add(etf["code"])
            sectors.append((sector, etf["code"], etf["name"]))

    results = []
    n = len(sectors)
    for i, (sector, code, name) in enumerate(sectors):
        if verbose:
            print(f"  [{i+1}/{n}] {sector}...", file=sys.stderr)
        r = validate_sector(rag, sector, code, name, verbose)
        results.append(r)

    return results


# ─── 报告 ─────────────────────────────────────────────────

def generate_report(results):
    verified = [r for r in results if "✅" in r.get("verdict", "")]
    disproved = [r for r in results if "❌" in r.get("verdict", "")]
    pending = [r for r in results if "⏳" in r.get("verdict", "")]
    skipped = [r for r in results if "⏭" in r.get("verdict", "")]

    lines = [
        "=" * 56,
        f"  钱博士观点验证报告 — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 56,
        "",
        f"  ✅ 验证通过: {len(verified)}  ❌ 被打脸: {len(disproved)}",
        f"  ⏳ 待观察: {len(pending)}  ⏭ 跳过: {len(skipped)}",
        "",
    ]

    # 准确率
    decidable = len(verified) + len(disproved)
    accuracy = len(verified) / decidable * 100 if decidable else 0
    if decidable:
        lines.append(f"  可判定准确率: {accuracy:.0f}% ({len(verified)}/{decidable})")
        lines.append("")

    if disproved:
        lines.append("━" * 56)
        lines.append("  ❌ 已被市场打脸")
        lines.append("━" * 56)
        for r in disproved:
            lines.append(f"  {r['sector']} → {r['etf']}({r['code']})")
            lines.append(f"    观点({r.get('view_age','?')}): {r.get('view_snippet','')[:80]}")
            lines.append(f"    {r['reason']}")
            if r.get("price"):
                p = r["price"]
                lines.append(f"    {p['from_date']} → {p['to_date']}: {p['change_pct']:+.1f}%")
            lines.append("")

    if verified:
        lines.append("━" * 56)
        lines.append("  ✅ 观点被市场验证")
        lines.append("━" * 56)
        for r in verified:
            lines.append(f"  {r['sector']} → {r['etf']} — {r['reason']}")
            if r.get("price"):
                p = r["price"]
                lines.append(f"    {p['from_date']} → {p['to_date']}: {p['change_pct']:+.1f}%")
            lines.append("")

    if pending:
        lines.append("━" * 56)
        lines.append("  ⏳ 待观察")
        lines.append("━" * 56)
        for r in pending[:8]:
            lines.append(f"  {r['sector']} — {r.get('reason','?')[:60]}")
            lines.append(f"    观点({r.get('view_age','?')}): {r.get('view_snippet','')[:80]}")
            lines.append("")

    return "\n".join(lines)


def save_log(results, config):
    data_dir = get_data_dir(config)
    log_path = data_dir / "validation_log.json"

    if log_path.exists():
        log = json.loads(log_path.read_text(encoding="utf-8"))
    else:
        log = {"version": 1, "entries": []}

    entry = {
        "date": str(date.today()),
        "time": datetime.now().strftime("%H:%M"),
        "results": [{
            "sector": r["sector"],
            "etf": r.get("etf", ""),
            "code": r.get("code", ""),
            "verdict": r["verdict"],
            "reason": r.get("reason", ""),
            "sentiment": r.get("sentiment", "unknown"),
            "view_date": r.get("view_date", ""),
            "price_change": r.get("price", {}).get("change_pct") if r.get("price") else None,
        } for r in results],
    }
    log["entries"].append(entry)
    log["updated"] = str(date.today())
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] 验证日志: {log_path}", file=sys.stderr)


# ─── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="钱博士观点验证")
    parser.add_argument("--sector", help="验证单个板块")
    parser.add_argument("--report", action="store_true", help="仅显示汇总报告")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--config", help="config.yaml路径")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.report:
        log_path = get_data_dir(config) / "validation_log.json"
        if log_path.exists():
            log = json.loads(log_path.read_text(encoding="utf-8"))
            latest = log["entries"][-1] if log["entries"] else None
            if latest:
                print(f"最近验证: {latest['date']} {latest.get('time','')}")
                for r in latest["results"]:
                    print(f"  {r['verdict']} {r['sector']} — {r.get('reason','?')}")
            else:
                print("暂无记录")
        else:
            print("暂无日志，先运行 python validate.py")
        sys.exit(0)

    rag = QianboshiRAG()

    if args.sector:
        sector = args.sector
        etf = SECTOR_ETFS.get(sector, {"code": "000001.SS", "name": sector})
        r = validate_sector(rag, sector, etf["code"], etf["name"], verbose=True)
        results = [r]
        print(f"\n{r['verdict']} {sector} → {etf['name']}({etf['code']})")
        print(f"  方向: {r.get('sentiment','?')} | 日期: {r.get('view_date','?')} ({r.get('view_age','?')})")
        print(f"  观点: {r.get('view_snippet','')[:150]}")
        if r.get("price"):
            p = r["price"]
            print(f"  走势: {p['from_date']} → {p['to_date']}: {p['change_pct']:+.1f}%")
        print(f"  判定: {r.get('reason','')}")
    else:
        print("[INFO] 验证板块观点...", file=sys.stderr)
        results = validate_all(config, rag, verbose=args.verbose)
        print(generate_report(results))
        save_log(results, config)
