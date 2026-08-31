#!/usr/bin/env python3
"""板块代理池回测：把 sector 事件用板块代表标的（龙头股+ETF）等权平均收益对照。

规则（2026-08-06 方案）：
- 每板块 2-4 个代表标的，等权平均收益
- 有效标的 >=2 才计分（单标的保留诊断不进入正式命中率）
- p0 = 事件日前最近收盘价（前视修正：<= event_date 最近交易日）
- p1 = p0 交易日 + window_days 个交易日后
- 命中判定复用 is_hit（bullish ret>0 / bearish ret<0 / risk 阈值）
- 只处理 event_date >= 2026-06-01（行情覆盖期）
- 结果写 sector_backtest_results 表，不影响主 prediction_events

用法：
    C:\\Python314\\python.exe scripts/sector_backtest.py [--since 2026-06-01] [--output sector_backtest_results]
"""
import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from outcome_updater import is_hit, load_json
from decision_db import connect

ROOT = Path(__file__).resolve().parents[1]
TREND_FILE = ROOT / "data" / "price_trends.json"

# 板块代表池（2026-08-06：观点频率优先 + 龙头/ETF + 行情可拉）
SECTOR_POOLS: dict[str, list[str]] = {
    "大盘": ["000001.SS", "399001.SZ", "399006.SZ", "510300.SS"],
    "大消费": ["600519.SS", "000858.SZ", "159928.SZ"],
    "大金融": ["512800.SS", "512880.SS", "601318.SS", "600036.SS"],
    "军工": ["512660.SS", "600760.SS"],
    "存储": ["603986.SS", "688008.SS"],
    "PCB": ["002463.SZ", "002916.SZ", "600183.SS"],
    "软件": ["515230.SS", "688111.SS", "600588.SS"],
    "消费电子": ["002475.SZ", "002241.SZ", "159732.SZ"],
}


def parse_day(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def sorted_price_rows(symbol: str, trends: dict) -> list[tuple[str, float]]:
    series = trends.get(symbol) or {}
    rows = []
    for day, rec in series.items():
        if isinstance(rec, dict):
            price = rec.get("price")
        else:
            price = rec
        if price is not None:
            rows.append((day, float(price)))
    return sorted(rows, key=lambda r: r[0])


def pool_window_prices(
    symbols: list[str],
    trends: dict,
    event_day: date,
    window_days: int,
) -> tuple[float | None, float | None, int]:
    """池等权：p0=池内各标的(事件日前最近收盘)均值；p1=start_idx+window 交易日价格均值。"""
    p0_list, p1_list = [], []
    for sym in symbols:
        rows = sorted_price_rows(sym, trends)
        if not rows:
            continue
        start_idx = None
        for idx in range(len(rows) - 1, -1, -1):
            parsed = parse_day(rows[idx][0])
            if parsed and parsed <= event_day:
                start_idx = idx
                break
        if start_idx is None:
            continue
        start_day = parse_day(rows[start_idx][0])
        if start_day and (event_day - start_day).days >= 7:
            continue  # 缺价过久不取
        p0_list.append(rows[start_idx][1])
        w_idx = start_idx + int(window_days)
        if w_idx < len(rows):
            p1_list.append(rows[w_idx][1])
    if not p0_list or len(p0_list) < 2:
        return None, None, len(p0_list)
    p0 = sum(p0_list) / len(p0_list)
    if not p1_list or len(p1_list) < 2:
        return p0, None, len(p0_list)
    p1 = sum(p1_list) / len(p1_list)
    return p0, p1, len(p0_list)


def run(since: str = "2026-06-01", output: str = "sector_backtest_results") -> dict[str, Any]:
    trends = load_json(TREND_FILE)
    since_day = parse_day(since)
    counts = {"total": 0, "resolved": 0, "low_coverage": 0, "no_price": 0}
    rows: list[dict[str, Any]] = []

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        events = conn.execute(
            """
            SELECT event_id, entity, stance, window_days, event_date
            FROM prediction_events
            WHERE entity_type='sector' AND status='skipped'
            ORDER BY event_date
            """
        ).fetchall()
        for ev in events:
            e_day = parse_day(ev["event_date"])
            if not e_day or (since_day and e_day < since_day):
                continue
            counts["total"] += 1
            pool = SECTOR_POOLS.get(ev["entity"])
            if not pool:
                continue
            p0, p1, n_avail = pool_window_prices(pool, trends, e_day, ev["window_days"])
            if p0 is None:
                counts["no_price"] += 1
                status = "no_price"
                ret = None
                hit = None
            elif p1 is None or n_avail < 2:
                counts["low_coverage"] += 1
                status = "low_coverage"
                ret = None
                hit = None
            else:
                ret = round((p1 - p0) / p0 * 100, 4)
                hit = 1 if is_hit(ev["stance"], ret, ev["window_days"]) else 0
                status = "resolved"
                counts["resolved"] += 1
            rows.append(
                {
                    "event_id": ev["event_id"],
                    "entity": ev["entity"],
                    "stance": ev["stance"],
                    "window_days": ev["window_days"],
                    "event_date": ev["event_date"],
                    "pool_size": len(pool),
                    "coverage": n_avail,
                    "p0": p0,
                    "p1": p1,
                    "return_pct": ret,
                    "hit": hit,
                    "status": status,
                }
            )

        # 写结果表
        conn.execute(f'DROP TABLE IF EXISTS "{output}"')
        conn.execute(
            f"""
            CREATE TABLE "{output}" (
                event_id TEXT PRIMARY KEY,
                entity TEXT, stance TEXT, window_days INTEGER, event_date TEXT,
                pool_size INTEGER, coverage INTEGER,
                p0 REAL, p1 REAL, return_pct REAL, hit INTEGER, status TEXT
            )
            """
        )
        conn.executemany(
            f'INSERT OR REPLACE INTO "{output}" VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            [
                (
                    r["event_id"], r["entity"], r["stance"], r["window_days"], r["event_date"],
                    r["pool_size"], r["coverage"], r["p0"], r["p1"], r["return_pct"], r["hit"], r["status"],
                )
                for r in rows
            ],
        )
        conn.commit()

    # 汇总
    resolved = [r for r in rows if r["status"] == "resolved"]
    by_board: dict[str, list[int]] = {}
    by_dir: dict[str, list[int]] = {}
    for r in resolved:
        by_board.setdefault(r["entity"], []).append(r["hit"])
        by_dir.setdefault(r["stance"], []).append(r["hit"])
    counts["resolved_views"] = len({r["event_id"].rsplit("_", 1)[0] for r in resolved})
    return {"counts": counts, "by_board": by_board, "by_dir": by_dir, "output": output}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="板块代理池回测")
    parser.add_argument("--since", default="2026-06-01")
    parser.add_argument("--output", default="sector_backtest_results")
    args = parser.parse_args()
    result = run(args.since, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
