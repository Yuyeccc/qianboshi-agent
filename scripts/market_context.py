#!/usr/bin/env python3
"""Deterministic market context for morning briefs.

This module reads cached market data and sector watchlist metadata. It never
invents missing A-share returns from a single cached close.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
WATCHLIST_PATH = ROOT / "config" / "sector_watchlist.yaml"


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def load_sector_watchlist(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else WATCHLIST_PATH
    if not p.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(f"[WARN] 读取 sector_watchlist 失败: {exc}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def _load_cache() -> dict[str, Any]:
    snapshot_path = DATA_DIR / "market_snapshot_10d.json"
    if snapshot_path.exists():
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            symbols = data.get("symbols") if isinstance(data, dict) else {}
            if isinstance(symbols, dict) and symbols:
                return symbols
        except Exception:
            pass
    try:
        import market_cache
        cache = market_cache.get_cached_prices() or {}
        return cache if isinstance(cache, dict) else {}
    except Exception:
        path = DATA_DIR / "market_cache.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _symbol_info(cache: dict[str, Any], symbol: str | None) -> dict[str, Any] | None:
    if not symbol:
        return None
    info = cache.get(symbol)
    return info if isinstance(info, dict) else None


def _safe_change(info: dict[str, Any] | None, symbol: str, notes: list[str]) -> float | None:
    if not isinstance(info, dict):
        return None
    change = _to_float(info.get("change_pct"))
    prices = info.get("prices") if isinstance(info.get("prices"), list) else []
    if change is None:
        if symbol.endswith((".SS", ".SZ")):
            notes.append(f"{symbol} 只有缓存价或缺 change_pct，未计算涨跌。")
        return None
    if symbol.endswith((".SS", ".SZ")) and len(prices) < 2:
        notes.append(f"{symbol} 只有单点缓存价，未计算涨跌。")
        return None
    return round(change, 3)


def sector_market_score(info: dict[str, Any]) -> float:
    """Return a 0..1 score from available relative strength and turnover."""
    rs = _to_float(info.get("relative_strength"))
    turnover = _to_float(info.get("turnover_vs_5d"))
    score = 0.0
    if rs is not None:
        # -2pct relative weakness -> 0, +2pct relative strength -> 1.
        score += max(0.0, min(1.0, (rs + 2.0) / 4.0)) * 0.75
    if turnover is not None:
        # 1.0x is neutral, 2.0x is strong.
        score += max(0.0, min(1.0, (turnover - 0.8) / 1.2)) * 0.25
    return round(max(0.0, min(1.0, score)), 3)


def build_market_context(
    config: dict[str, Any] | None = None,
    watchlist: dict[str, Any] | None = None,
    cache: dict[str, Any] | None = None,
    trade_date: str | None = None,
) -> dict[str, Any]:
    watchlist = watchlist if isinstance(watchlist, dict) else load_sector_watchlist()
    cache = cache if isinstance(cache, dict) else _load_cache()
    notes: list[str] = []
    ctx = {
        "trade_date": trade_date or datetime.now().strftime("%Y-%m-%d"),
        "session_type": "cached",
        "indexes": {},
        "sectors": {},
        "symbols": {},
        "overnight": {},
        "notes": notes,
    }

    for name, raw_cfg in watchlist.items():
        cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
        sector_notes: list[str] = []
        proxy = cfg.get("market_proxy")
        if proxy is None and cfg.get("etfs"):
            proxy = cfg.get("etfs", [None])[0]
        benchmark = cfg.get("benchmark")
        proxy_info = _symbol_info(cache, proxy)
        benchmark_info = _symbol_info(cache, benchmark)
        ret = _safe_change(proxy_info, str(proxy or ""), sector_notes)
        bench_ret = _safe_change(benchmark_info, str(benchmark or ""), sector_notes)
        relative = round(ret - bench_ret, 3) if ret is not None and bench_ret is not None else None

        if not proxy:
            source = "missing"
            if cfg.get("proxy_note"):
                sector_notes.append(str(cfg.get("proxy_note")))
        elif proxy_info:
            source = "cached"
        else:
            source = "missing"
            sector_notes.append(f"{proxy} 缓存缺失。")

        core_symbols = cfg.get("core_symbol_codes") if isinstance(cfg.get("core_symbol_codes"), dict) else {}
        core_prices = {}
        for label, symbol in core_symbols.items():
            sinfo = _symbol_info(cache, symbol)
            if sinfo:
                item = dict(sinfo)
                item["label"] = label
                core_prices[symbol] = item
                ctx["symbols"][symbol] = item

        turnover_vs_5d = _to_float((proxy_info or {}).get("turnover_vs_5d"))
        info = {
            "market_proxy": proxy,
            "benchmark": benchmark,
            "return_pct": ret,
            "benchmark_return_pct": bench_ret,
            "turnover": (proxy_info or {}).get("turnover"),
            "turnover_vs_5d": turnover_vs_5d,
            "relative_strength": relative,
            "rank": None,
            "source": source,
            "core_symbols": core_symbols,
            "core_prices": core_prices,
            "notes": sector_notes,
        }
        info["score"] = sector_market_score(info)
        ctx["sectors"][name] = info
        notes.extend(sector_notes)

    ranked = sorted(
        [(name, info) for name, info in ctx["sectors"].items() if info.get("score", 0) > 0],
        key=lambda x: (-float(x[1].get("score", 0)), x[0]),
    )
    for rank, (_, info) in enumerate(ranked, 1):
        info["rank"] = rank
    return ctx


if __name__ == "__main__":
    print(json.dumps(build_market_context(), ensure_ascii=False, indent=2))
