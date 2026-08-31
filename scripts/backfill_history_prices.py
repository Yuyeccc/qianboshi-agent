#!/usr/bin/env python3
"""历史行情补拉（68 号方案，2026-09-01）。

2026 年 error 事件 85% 是 p0 历史行情缺失（1-5 月事件早于 price_trends 起始 6 月中）。
对 2026 error 涉及的 7 个 symbol 用 yfinance 拉 1y 历史，**增量合并**写 price_trends.json
（保留现有数据不覆盖；冲突以新为准）。逐标的 sleep 防限流，失败不中断。

用法:
    python scripts/backfill_history_prices.py            # 补默认 7 symbols
    python scripts/backfill_history_prices.py --symbols 300308.SZ,601899.SS   # 指定
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRENDS_FILE = ROOT / "data" / "price_trends.json"

# 2026 error 涉及 symbols（按事件数降序，侦察 68 号方案）
DEFAULT_SYMBOLS = ["300502.SZ", "300308.SZ", "688981.SS", "300394.SZ",
                   "601899.SS", "159992.SZ", "159770.SZ"]


def load_trends() -> dict:
    if not TRENDS_FILE.exists():
        return {}
    try:
        return json.loads(TRENDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fetch_symbol(symbol: str, period: str = "1y") -> dict:
    """yfinance 拉历史 → {date: {price, change_pct}}。"""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period, auto_adjust=True)
    if hist is None or hist.empty:
        return {}
    out: dict = {}
    closes = hist["Close"].dropna()
    prev_close = None
    for day, close in closes.items():
        d = str(day.date())
        p = float(close)
        chg = None
        if prev_close and prev_close > 0:
            chg = round((p - prev_close) / prev_close * 100, 4)
        out[d] = {"price": p, "change_pct": chg}
        prev_close = p
    return out


def merge_trends(trends: dict, symbol: str, new_rows: dict) -> tuple[int, int]:
    """增量合并：返回 (新增天数, 更新天数)。"""
    cur = trends.setdefault(symbol, {})
    added = updated = 0
    for d, row in new_rows.items():
        if d not in cur:
            added += 1
        else:
            updated += 1
        cur[d] = row
    return added, updated


def backfill(symbols: list[str], period: str = "1y", sleep: float = 1.0) -> dict:
    trends = load_trends()
    result: dict = {"total": 0, "ok": [], "failed": []}
    for sym in symbols:
        try:
            rows = fetch_symbol(sym, period)
            if not rows:
                result["failed"].append({"symbol": sym, "reason": "empty"})
                continue
            added, updated = merge_trends(trends, sym, rows)
            result["ok"].append({"symbol": sym, "days": len(rows), "added": added, "updated": updated})
            result["total"] += len(rows)
            # 增量写盘（每标的一次，失败不丢已成功标的）
            TRENDS_FILE.write_text(json.dumps(trends, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            result["failed"].append({"symbol": sym, "reason": str(e)[:120]})
        time.sleep(sleep)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="历史行情补拉（增量合并 price_trends.json）")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="逗号分隔 symbol 列表")
    parser.add_argument("--period", default="1y", help="yfinance period")
    parser.add_argument("--backup", action="store_true", default=True, help="备份 price_trends.json（默认开）")
    args = parser.parse_args()

    if args.backup and TRENDS_FILE.exists():
        bak = TRENDS_FILE.with_name("price_trends.json.bak_20260901_pre_backfill")
        shutil.copy2(TRENDS_FILE, bak)
        print(f"[backup] {bak}")

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    print(f"[start] {len(symbols)} symbols, period={args.period}")
    result = backfill(symbols, period=args.period)
    for o in result["ok"]:
        print(f"  ✅ {o['symbol']}: {o['days']} 天（新增 {o['added']} / 更新 {o['updated']}）")
    for f in result["failed"]:
        print(f"  ❌ {f['symbol']}: {f['reason']}")
    trends = load_trends()
    print(f"[done] 新增/更新总天数 {result['total']}，price_trends 现 {len(trends)} symbols")
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
