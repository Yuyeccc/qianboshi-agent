#!/usr/bin/env python3
"""Fetch Hong Kong market history into data/price_trends.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TREND_FILE = DATA_DIR / "price_trends.json"
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from entity_normalizer import normalize_hk_symbol
from market_data_sources import fetch_hk_yfinance


def _load_trends() -> dict[str, Any]:
    if not TREND_FILE.exists():
        return {}
    try:
        data = json.loads(TREND_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[WARN] failed to read {TREND_FILE}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {}


def _save_trends(trends: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TREND_FILE.write_text(json.dumps(trends, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_rows(trends: dict[str, Any], rows_by_symbol: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    for symbol, rows in rows_by_symbol.items():
        history = trends.setdefault(symbol, {})
        if not isinstance(history, dict):
            history = {}
            trends[symbol] = history
        for row in rows:
            date = row.get("date")
            close = row.get("close")
            # nan/None 价格跳过（yfinance 港股偶发 nan）
            if not date or close is None:
                continue
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            if close_f != close_f:  # nan check
                continue
            history[str(date)] = {
                "price": round(close_f, 4),
                "change_pct": row.get("change_pct"),
            }
    return trends


def _print_summary(symbols: list[str], rows_by_symbol: dict[str, list[dict[str, Any]]]) -> None:
    for symbol in symbols:
        rows = rows_by_symbol.get(symbol) or []
        if not rows:
            print(f"{symbol}: failed or empty")
            continue
        dates = [str(row.get("date")) for row in rows if row.get("date")]
        if dates:
            print(f"{symbol}: {len(rows)} days {min(dates)}..{max(dates)}")
        else:
            print(f"{symbol}: {len(rows)} days")


def parse_symbols(raw: str) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for item in raw.split(","):
        symbol = normalize_hk_symbol(item)
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch HK symbols from yfinance into data/price_trends.json")
    parser.add_argument("--symbols", required=True, help="Comma-separated HK symbols, e.g. 3069.HK,1801.HK")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--no-proxy", action="store_true", help="Do not set Clash proxy env vars")
    args = parser.parse_args()

    symbols = parse_symbols(args.symbols)
    if not symbols:
        print("no valid symbols", file=sys.stderr)
        return 2

    try:
        rows_by_symbol = fetch_hk_yfinance(symbols, args.days, use_proxy=not args.no_proxy)
    except Exception as exc:
        print(f"[ERROR] fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        rows_by_symbol = {}

    _print_summary(symbols, rows_by_symbol)
    if rows_by_symbol:
        trends = _merge_rows(_load_trends(), rows_by_symbol)
        try:
            _save_trends(trends)
            print(f"saved={TREND_FILE}")
        except Exception as exc:
            print(f"[ERROR] save failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
