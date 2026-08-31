#!/usr/bin/env python3
"""Multi-source 10-day market data snapshot for A/HK/US assets.

Primary goal: collect enough recent market context for briefs without relying on
one fragile provider. A-share data prefers AkShare; global tickers prefer
Yahoo/yfinance with direct/proxy fallback.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SNAPSHOT_FILE = DATA_DIR / "market_snapshot_10d.json"
CACHE_FILE = DATA_DIR / "market_cache.json"
TREND_FILE = DATA_DIR / "price_trends.json"
WATCHLIST_FILE = ROOT / "config" / "sector_watchlist.yaml"

DEFAULT_INDEXES = ["000001.SS", "399001.SZ", "399006.SZ", "000688.SS", "^DJI", "^IXIC", "^GSPC", "^HSI"]
DEFAULT_GLOBAL = ["NVDA", "AMD", "AVGO", "MRVL", "SMCI", "TSLA", "AAPL", "MSFT", "GOOGL", "META"]


def is_a_share(symbol: str) -> bool:
    return symbol.endswith((".SS", ".SZ")) and symbol[:6].isdigit()


def is_cn_index(symbol: str) -> bool:
    return symbol in {"000001.SS", "399001.SZ", "399006.SZ", "000688.SS"}


def strip_suffix(symbol: str) -> str:
    return symbol.split(".", 1)[0]


def symbol_name(symbol: str) -> str:
    names = {
        "000001.SS": "上证指数",
        "399001.SZ": "深证成指",
        "399006.SZ": "创业板指",
        "000688.SS": "科创50",
        "^DJI": "道琼斯指数",
        "^IXIC": "纳斯达克指数",
        "^GSPC": "标普500",
        "^HSI": "恒生指数",
    }
    return names.get(symbol, "")


def _clear_proxy() -> None:
    for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
        os.environ.pop(k, None)


def _proxy_env() -> None:
    proxy = "http://127.0.0.1:7897"
    os.environ["HTTP_PROXY"] = proxy
    os.environ["HTTPS_PROXY"] = proxy


def _rows_from_frame(df: Any, limit: int = 10) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    out: list[dict[str, Any]] = []
    tail = df.tail(limit)
    for idx, row in tail.iterrows():
        date = getattr(idx, "strftime", lambda _fmt: str(idx))("%Y-%m-%d")
        close = row.get("close", row.get("Close"))
        open_v = row.get("open", row.get("Open"))
        high = row.get("high", row.get("High"))
        low = row.get("low", row.get("Low"))
        volume = row.get("volume", row.get("Volume"))
        turnover = row.get("turnover")
        pct = row.get("pct_chg", row.get("change_pct"))
        try:
            close_f = round(float(close), 4)
        except Exception:
            continue
        item = {"date": str(date)[:10], "close": close_f}
        for key, value in [("open", open_v), ("high", high), ("low", low), ("volume", volume), ("turnover", turnover), ("change_pct", pct)]:
            try:
                if value is not None and value == value:
                    item[key] = round(float(value), 4)
            except Exception:
                pass
        out.append(item)
    return out


def normalize_ak_daily(df: Any) -> Any:
    rename = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "turnover",
        "涨跌幅": "change_pct",
    }
    df = df.rename(columns={c: rename.get(c, c) for c in df.columns})
    if "date" in df.columns:
        df["date"] = df["date"].astype(str)
        df = df.set_index("date")
    return df


def fetch_a_share_akshare(symbol: str, days: int) -> tuple[list[dict[str, Any]], str | None]:
    _clear_proxy()
    try:
        import akshare as ak
        code = strip_suffix(symbol)
        if is_cn_index(symbol):
            try:
                df = ak.index_zh_a_hist(symbol=code, period="daily")
                rows = _rows_from_frame(normalize_ak_daily(df), days)
                if rows:
                    return rows, "akshare_index_zh_a_hist"
            except Exception:
                # Some indexes (notably 科创50/000688) are flaky through
                # index_zh_a_hist / EastMoney clist discovery. Sina index daily
                # works directly with sh/sz-prefixed index code.
                prefix = "sh" if symbol.endswith(".SS") else "sz"
                df = ak.stock_zh_index_daily(symbol=f"{prefix}{code}")
                rows = _rows_from_frame(normalize_ak_daily(df), days)
                return rows, "akshare_stock_zh_index_daily"
        else:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
        rows = _rows_from_frame(normalize_ak_daily(df), days)
        return rows, "akshare"
    except Exception as exc:
        return [], f"akshare_failed:{type(exc).__name__}"


def baostock_code(symbol: str) -> str | None:
    code = strip_suffix(symbol)
    if not code.isdigit() or len(code) != 6:
        return None
    if symbol.endswith(".SS") or code.startswith(("5", "6", "9")):
        return f"sh.{code}"
    if symbol.endswith(".SZ") or code.startswith(("0", "1", "2", "3")):
        return f"sz.{code}"
    return None


def fetch_a_share_baostock(symbols: list[str], days: int, delay: float = 0.35) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """BaoStock fallback for A-share daily K lines.

    Polite rules: one login, sequential requests, small sleep between symbols,
    no concurrency, no retry storm. This is intentionally slower.
    """
    if not symbols:
        return {}, {}
    _clear_proxy()
    results: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    try:
        import baostock as bs
    except Exception as exc:
        return {}, {s: f"baostock_import_failed:{type(exc).__name__}" for s in symbols}

    lg = bs.login()
    if getattr(lg, "error_code", "") != "0":
        return {}, {s: f"baostock_login_failed:{getattr(lg, 'error_msg', '')}" for s in symbols}
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        # Calendar days > trading days, avoids repeat calls for holiday gaps.
        start_date = (datetime.now() - timedelta(days=max(days * 3, 30))).strftime("%Y-%m-%d")
        fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg,turn"
        for sym in symbols:
            bs_code = baostock_code(sym)
            if not bs_code:
                errors[sym] = "baostock_unsupported_symbol"
                continue
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    fields,
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="2",
                )
                if getattr(rs, "error_code", "") != "0":
                    errors[sym] = f"baostock_query_failed:{getattr(rs, 'error_msg', '')}"
                    time.sleep(delay)
                    continue
                rows = []
                while rs.next():
                    item = dict(zip(rs.fields, rs.get_row_data()))
                    try:
                        close = float(item.get("close") or 0)
                    except Exception:
                        close = 0.0
                    if close <= 0:
                        continue
                    row = {"date": item.get("date"), "close": round(close, 4)}
                    mapping = {
                        "open": "open",
                        "high": "high",
                        "low": "low",
                        "volume": "volume",
                        "amount": "turnover",
                        "pctChg": "change_pct",
                        "turn": "turnover_rate",
                    }
                    for src, dst in mapping.items():
                        value = item.get(src)
                        try:
                            if value not in {None, ""}:
                                row[dst] = round(float(value), 4)
                        except Exception:
                            pass
                    rows.append(row)
                if rows:
                    results[sym] = rows[-days:]
                else:
                    errors[sym] = "baostock_empty"
            except Exception as exc:
                errors[sym] = f"baostock_failed:{type(exc).__name__}"
            time.sleep(delay)
    finally:
        try:
            bs.logout()
        except Exception:
            pass
    return results, errors


def fetch_yfinance(symbols: list[str], days: int, use_proxy: bool) -> dict[str, list[dict[str, Any]]]:
    if use_proxy:
        _proxy_env()
    else:
        _clear_proxy()
    try:
        import pandas as pd
        import yfinance as yf
        data = yf.download(symbols, period=f"{max(days + 5, 15)}d", progress=False, timeout=30, auto_adjust=False, group_by="ticker")
        if data is None or data.empty:
            return {}
        is_multi = isinstance(data.columns, pd.MultiIndex)
        out: dict[str, list[dict[str, Any]]] = {}
        for sym in symbols:
            try:
                col = data[sym] if is_multi and sym in data.columns.get_level_values(0) else data
                rows = _rows_from_frame(col.dropna(how="all"), days)
                if rows:
                    out[sym] = rows
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _normalize_hk_symbol(symbol: str) -> str:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return symbol
    if symbol.endswith(".HK"):
        code = symbol[:-3]
    else:
        code = symbol
    if re.match(r"^\d{4,5}$", code):
        return f"{int(code)}.HK"
    return symbol


def _fill_change_pct(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prev_close: float | None = None
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            close = float(item["close"])
        except Exception:
            out.append(item)
            continue
        if item.get("change_pct") is None:
            item["change_pct"] = round((close - prev_close) / prev_close * 100, 4) if prev_close else None
        prev_close = close
        out.append(item)
    return out


def fetch_hk_yfinance(symbols: list[str], days: int, use_proxy: bool) -> dict[str, list[dict[str, Any]]]:
    hk_symbols = [_normalize_hk_symbol(s) for s in symbols if _normalize_hk_symbol(s)]
    if not hk_symbols:
        return {}
    if use_proxy:
        _proxy_env()
    else:
        _clear_proxy()
    try:
        import pandas as pd
        import yfinance as yf

        data = yf.download(
            hk_symbols,
            period=f"{max(days + 5, 15)}d",
            progress=False,
            timeout=30,
            auto_adjust=False,
            group_by="ticker",
        )
        if data is None or data.empty:
            return {}
        is_multi = isinstance(data.columns, pd.MultiIndex)
        out: dict[str, list[dict[str, Any]]] = {}
        for sym in hk_symbols:
            try:
                col = data[sym] if is_multi and sym in data.columns.get_level_values(0) else data
                rows = _fill_change_pct(_rows_from_frame(col.dropna(how="all"), days))
                if rows:
                    out[sym] = rows
            except Exception:
                continue
        return out
    except Exception:
        return {}


def calc_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"price": None, "change_pct": None, "prices": []}
    prices = [float(r["close"]) for r in rows if r.get("close") is not None]
    if not prices:
        return {"price": None, "change_pct": None, "prices": []}
    latest = prices[-1]
    prev = prices[-2] if len(prices) >= 2 else None
    first = prices[0]
    change = round((latest - prev) / prev * 100, 3) if prev else None
    change_10d = round((latest - first) / first * 100, 3) if len(prices) >= 2 and first else None
    volumes = [float(r.get("volume")) for r in rows[-6:-1] if r.get("volume") is not None]
    latest_vol = rows[-1].get("volume")
    turnover_vs_5d = None
    if latest_vol is not None and volumes:
        avg = sum(volumes) / len(volumes)
        if avg:
            turnover_vs_5d = round(float(latest_vol) / avg, 3)
    return {
        "price": round(latest, 4),
        "change_pct": change,
        "change_10d_pct": change_10d,
        "prices": [round(x, 4) for x in prices],
        "turnover": rows[-1].get("turnover") or rows[-1].get("volume"),
        "turnover_vs_5d": turnover_vs_5d,
        "updated": datetime.now().isoformat(timespec="seconds"),
    }


def load_watchlist_symbols() -> list[str]:
    try:
        import yaml
        data = yaml.safe_load(WATCHLIST_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    symbols: set[str] = set()
    for cfg in data.values():
        if not isinstance(cfg, dict):
            continue
        for key in ["market_proxy", "benchmark"]:
            if cfg.get(key):
                symbols.add(str(cfg[key]))
        for item in cfg.get("etfs") or []:
            if item:
                symbols.add(str(item))
        codes = cfg.get("core_symbol_codes") or {}
        if isinstance(codes, dict):
            symbols.update(str(x) for x in codes.values() if x)
    return sorted(symbols)


def load_brief_symbols() -> list[str]:
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import brief_parser
        return list(brief_parser.get_tracking_symbols())
    except Exception:
        return []


def collect_symbols(no_brief: bool = False) -> list[str]:
    symbols = set(DEFAULT_INDEXES + DEFAULT_GLOBAL + load_watchlist_symbols())
    if not no_brief:
        symbols.update(load_brief_symbols())
    return sorted(s for s in symbols if s and s.lower() != "nan")


def build_snapshot(days: int = 10, symbols: list[str] | None = None, no_brief: bool = False, yfinance_a_fallback: bool = True) -> dict[str, Any]:
    symbols = symbols or collect_symbols(no_brief=no_brief)
    snapshot = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "sources": {
            "a_share_primary": "akshare(stock_zh_a_hist/index_zh_a_hist)",
            "global_primary": "yfinance direct -> proxy fallback",
            "proxy": "127.0.0.1:7897 for global fallback",
        },
        "symbols": {},
        "errors": {},
    }

    a_symbols = [s for s in symbols if is_a_share(s)]
    y_symbols = [s for s in symbols if not is_a_share(s)]

    a_failures: dict[str, str] = {}
    for i, sym in enumerate(a_symbols, 1):
        rows, source = fetch_a_share_akshare(sym, days)
        if rows:
            info = calc_summary(rows)
            info.update({"symbol": sym, "name": symbol_name(sym), "source": source, "history": rows})
            snapshot["symbols"][sym] = info
        else:
            a_failures[sym] = source or "akshare_failed"
        if i % 20 == 0:
            time.sleep(1)

    # A-share fallback order: BaoStock politely first, then yfinance direct.
    if a_failures:
        bs_rows, bs_errors = fetch_a_share_baostock(list(a_failures), days)
        for sym, rows in bs_rows.items():
            info = calc_summary(rows)
            info.update({"symbol": sym, "name": symbol_name(sym), "source": "baostock_fallback", "history": rows})
            snapshot["symbols"][sym] = info
        a_failures = {sym: bs_errors.get(sym, a_failures[sym]) for sym in a_failures if sym not in snapshot["symbols"]}

    # Last A-share fallback is yfinance direct only; proxy often breaks China-market TLS.
    if a_failures and yfinance_a_fallback:
        y_a = fetch_yfinance(list(a_failures), days, use_proxy=False)
        for sym, rows in y_a.items():
            info = calc_summary(rows)
            info.update({"symbol": sym, "name": symbol_name(sym), "source": "yfinance_direct_fallback", "history": rows})
            snapshot["symbols"][sym] = info
        a_failures = {sym: err for sym, err in a_failures.items() if sym not in snapshot["symbols"]}
    for sym, err in a_failures.items():
        snapshot["errors"][sym] = err

    direct = fetch_yfinance(y_symbols, days, use_proxy=False) if y_symbols else {}
    missing = [s for s in y_symbols if s not in direct]
    proxy = fetch_yfinance(missing, days, use_proxy=True) if missing else {}
    for sym, rows in {**direct, **proxy}.items():
        info = calc_summary(rows)
        info.update({"symbol": sym, "name": symbol_name(sym), "source": "yfinance_proxy" if sym in proxy else "yfinance_direct", "history": rows})
        snapshot["symbols"][sym] = info
    for sym in y_symbols:
        if sym not in snapshot["symbols"]:
            snapshot["errors"][sym] = "yfinance_failed"

    return snapshot


def save_snapshot(snapshot: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 合并旧快照：新数据覆盖同名标的，旧快照中本次未拉取的标的保留，
    # 避免部分失败（如 yfinance 限流）把已有数据整个覆盖掉。
    if SNAPSHOT_FILE.exists():
        try:
            old = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
            old_symbols = old.get("symbols") if isinstance(old, dict) else {}
            if isinstance(old_symbols, dict):
                new_symbols = snapshot.get("symbols", {})
                for sym, info in old_symbols.items():
                    new_symbols.setdefault(sym, info)
        except Exception:
            pass
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    cache = {sym: {k: v for k, v in info.items() if k != "history"} for sym, info in snapshot.get("symbols", {}).items()}
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    trends: dict[str, Any] = {}
    if TREND_FILE.exists():
        try:
            trends = json.loads(TREND_FILE.read_text(encoding="utf-8"))
        except Exception:
            trends = {}
    for sym, info in snapshot.get("symbols", {}).items():
        trends.setdefault(sym, {})
        for row in info.get("history") or []:
            if row.get("date") and row.get("close") is not None:
                trends[sym][row["date"]] = {"price": row["close"], "change_pct": row.get("change_pct")}
    TREND_FILE.write_text(json.dumps(trends, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="抓取近10日国内外行情，保存 market_snapshot_10d + market_cache")
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--symbols", help="逗号分隔标的；为空则读取默认+watchlist+近期简报")
    ap.add_argument("--no-brief", action="store_true", help="不从历史简报提取额外标的")
    ap.add_argument("--no-yfinance-a", action="store_true", help="A股只试 akshare+baostock，不再打 yfinance")
    ap.add_argument("--output", default=str(SNAPSHOT_FILE))
    args = ap.parse_args()

    symbols = [x.strip() for x in args.symbols.split(",") if x.strip()] if args.symbols else None
    snapshot = build_snapshot(days=args.days, symbols=symbols, no_brief=args.no_brief, yfinance_a_fallback=not args.no_yfinance_a)
    save_snapshot(snapshot)
    if args.output != str(SNAPSHOT_FILE):
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = len(snapshot.get("symbols", {}))
    bad = len(snapshot.get("errors", {}))
    print(f"saved={SNAPSHOT_FILE} ok={ok} failed={bad}")
    if bad:
        print("failed_symbols=" + ",".join(list(snapshot["errors"].keys())[:30]), file=sys.stderr)


if __name__ == "__main__":
    main()
