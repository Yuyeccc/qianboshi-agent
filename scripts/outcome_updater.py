#!/usr/bin/env python3
"""预测事件收益回填器。"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import get_data_dir, load_config
from decision_db import connect, fetch_pending_prediction_events, update_prediction_event_outcomes_batch, upsert_market_outcomes_batch


ROOT = Path(__file__).resolve().parents[1]
TREND_FILE = ROOT / "data" / "price_trends.json"
CACHE_FILE = ROOT / "data" / "market_cache.json"
TABLE_NAME_RE = __import__("re").compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_table(name: str) -> str:
    if not TABLE_NAME_RE.fullmatch(name):
        raise ValueError(f"非法表名: {name}")
    return f'"{name}"'


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def trend_path() -> Path:
    data_dir = get_data_dir(load_config())
    return data_dir / "price_trends.json"


def cache_path() -> Path:
    data_dir = get_data_dir(load_config())
    return data_dir / "market_cache.json"


def parse_day(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except Exception:
        return None


def price_from_row(row: dict[str, Any]) -> float | None:
    for key in ("price", "close"):
        try:
            value = row.get(key)
            if value is not None:
                return float(value)
        except Exception:
            continue
    return None


def sorted_price_rows(symbol: str, trends: dict[str, Any]) -> list[tuple[str, float, float | None]]:
    rows: list[tuple[str, float, float | None]] = []
    for day, row in (trends.get(symbol) or {}).items():
        if not isinstance(row, dict):
            continue
        price = price_from_row(row)
        if price is None or price <= 0:
            continue
        change_pct = row.get("change_pct")
        try:
            change_pct = float(change_pct) if change_pct is not None else None
        except Exception:
            change_pct = None
        rows.append((str(day)[:10], price, change_pct))
    rows.sort(key=lambda item: item[0])
    return rows


PriceRowsCache = dict[str, list[tuple[str, float, float | None]]]


def find_window_prices(
    event: dict[str, Any],
    trends: dict[str, Any],
    price_cache: PriceRowsCache | None = None,
) -> tuple[float | None, str | None, float | None, str | None, float | None, float | None]:
    """按交易日序列找到事件日和窗口日价格。"""


    event_day = parse_day(event.get("event_date", ""))
    if not event_day:
        return None, None, None, None, None, None
    symbol = event.get("entity", "")
    if price_cache is not None:
        if symbol not in price_cache:
            price_cache[symbol] = sorted_price_rows(symbol, trends)
        rows = price_cache[symbol]
    else:
        rows = sorted_price_rows(symbol, trends)
    if not rows:
        return None, None, None, None, None, None
    # 找事件日或之前最近的交易日（p0 用事件前已知价格，避免前视偏差；2026-08-06 修复：原逻辑取 >=event_day 会用周末/节假日后的价格当基准）
    start_idx = None
    for idx in range(len(rows) - 1, -1, -1):
        parsed = parse_day(rows[idx][0])
        if parsed and parsed <= event_day:
            start_idx = idx
            break
    if start_idx is None:
        return None, None, None, None, None, None
    # 事件日价格缺失过久时不做回测，避免把远期价格错当事件日价格。
    start_day = parse_day(rows[start_idx][0])
    if start_day and (event_day - start_day).days >= 7:
        return None, None, None, None, None, None
    window_idx = start_idx + int(event.get("window_days") or 0)
    if window_idx >= len(rows):
        return rows[start_idx][1], rows[start_idx][0], None, None, rows[start_idx][2], None
    return rows[start_idx][1], rows[start_idx][0], rows[window_idx][1], rows[window_idx][0], rows[start_idx][2], rows[window_idx][2]


def target_date(event: dict[str, Any]) -> str | None:
    event_day = parse_day(event.get("event_date", ""))
    if not event_day:
        return None
    return (event_day + timedelta(days=int(event.get("window_days") or 0))).strftime("%Y-%m-%d")

def fetch_missing_symbol(symbol: str, days: int = 30) -> bool:
    """补拉单个标的历史行情，并同步写入 price_trends.json。"""
    try:
        from market_data_sources import build_snapshot, save_snapshot

        snapshot = build_snapshot(days=days, symbols=[symbol], no_brief=True)
        save_snapshot(snapshot)
        symbols = snapshot.get("symbols") or {}
        info = symbols.get(symbol) or {}
        history = info.get("history") or []
        if not history:
            return False
        trends = load_json(trend_path())
        symbol_trends = trends.setdefault(symbol, {})
        for row in history:
            if not isinstance(row, dict):
                continue
            day = str(row.get("date") or "")[:10]
            price = price_from_row(row)
            if not day or price is None or price <= 0:
                continue
            change_pct = row.get("change_pct")
            try:
                change_pct = float(change_pct) if change_pct is not None else None
            except Exception:
                change_pct = None
            symbol_trends[day] = {"price": price, "change_pct": change_pct}
        save_json(trend_path(), trends)
        return bool(symbol_trends)
    except Exception:
        return False






def resolve_event(
    event: dict[str, Any],
    trends: dict[str, Any],
    price_cache: PriceRowsCache,
    fetched_symbols: set[str],
    market_rows: dict[tuple[str, str], dict[str, Any]],
    allow_fetch: bool = True,
) -> tuple[str, float | None, float | None, float | None]:
    if event.get("entity_type") == "sector":
        return "error", None, None, None

    symbol = event.get("entity", "")
    price_at_event, event_day, price_at_window, window_day, event_change_pct, window_change_pct = find_window_prices(event, trends, price_cache)
    if price_at_window is None and allow_fetch:
        if symbol and symbol not in fetched_symbols and fetch_missing_symbol(symbol):
            trends.clear()
            trends.update(load_json(trend_path()))
            price_cache[symbol] = sorted_price_rows(symbol, trends)
            price_at_event, event_day, price_at_window, window_day, event_change_pct, window_change_pct = find_window_prices(
                event,
                trends,
                price_cache,
            )
        if symbol:
            fetched_symbols.add(symbol)

    if price_at_event is None or price_at_window is None or price_at_event <= 0:
        return "error", price_at_event, price_at_window, None

    return_pct = round((price_at_window - price_at_event) / price_at_event * 100, 4)
    if symbol and event_day:
        market_rows[(symbol, event_day)] = {"symbol": symbol, "date": event_day, "price": price_at_event, "change_pct": event_change_pct}
    if symbol and window_day:
        market_rows[(symbol, window_day)] = {"symbol": symbol, "date": window_day, "price": price_at_window, "change_pct": window_change_pct}
    return "resolved", price_at_event, price_at_window, return_pct


def resolve_event_detail(
    event: dict[str, Any],
    trends: dict[str, Any],
    price_cache: PriceRowsCache,
    fetched_symbols: set[str],
    market_rows: dict[tuple[str, str], dict[str, Any]],
    allow_fetch: bool = True,
) -> dict[str, Any]:
    if event.get("entity_type") == "sector":
        return {"status": "skipped", "price_at_event": None, "price_at_window": None, "return_pct": None, "target_date": target_date(event), "actual_price_date": None, "source": "sector"}

    symbol = event.get("entity", "")
    p0, event_day, p1, window_day, event_change_pct, window_change_pct = find_window_prices(event, trends, price_cache)
    if p1 is None and allow_fetch:
        if symbol and symbol not in fetched_symbols and fetch_missing_symbol(symbol):
            trends.clear()
            trends.update(load_json(trend_path()))
            price_cache[symbol] = sorted_price_rows(symbol, trends)
            p0, event_day, p1, window_day, event_change_pct, window_change_pct = find_window_prices(event, trends, price_cache)
        if symbol:
            fetched_symbols.add(symbol)

    if p0 is None or p1 is None or p0 <= 0:
        return {"status": "error", "price_at_event": p0, "price_at_window": p1, "return_pct": None, "target_date": target_date(event), "actual_price_date": window_day, "source": "price_trends"}

    ret = round((p1 - p0) / p0 * 100, 4)
    if symbol and event_day:
        market_rows[(symbol, event_day)] = {"symbol": symbol, "date": event_day, "price": p0, "change_pct": event_change_pct}
    if symbol and window_day:
        market_rows[(symbol, window_day)] = {"symbol": symbol, "date": window_day, "price": p1, "change_pct": window_change_pct}
    return {"status": "resolved", "price_at_event": p0, "price_at_window": p1, "return_pct": ret, "target_date": target_date(event), "actual_price_date": window_day, "source": "price_trends"}


def is_hit(stance: str, return_pct: float, window_days: int = 1) -> bool:
    """命中规则：bullish > 0，bearish < 0，risk < -1。"""
    if stance == "bullish":
        return return_pct > 0
    if stance == "bearish":
        return return_pct < 0
    if stance == "risk":
        if window_days <= 3:
            risk_threshold = 0.5
        elif window_days <= 10:
            risk_threshold = 1.0
        else:
            risk_threshold = 2.0
        return return_pct < -risk_threshold
    return False


def fetch_events(table: str, limit: int = 100, since: str | None = None, status: str = "pending") -> list[dict[str, Any]]:
    if table == "prediction_events":
        return fetch_pending_prediction_events(limit=limit, since=since) if status == "pending" else []
    with connect() as conn:
        params: list[Any] = [status]
        where = "status = ?"
        if since:
            where += " AND event_date >= ?"
            params.append(since)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT * FROM {quote_table(table)}
            WHERE {where}
            ORDER BY event_date, event_id
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def update_events(table: str, updates: list[dict[str, Any]]) -> int:
    if table == "prediction_events":
        return update_prediction_event_outcomes_batch(updates)
    if not updates:
        return 0
    with connect() as conn:
        conn.executemany(
            f"""
            UPDATE {quote_table(table)}
            SET price_at_event = :price_at_event,
                price_at_window = :price_at_window,
                return_pct = :return_pct,
                status = :status
            WHERE event_id = :event_id
            """,
            updates,
        )
        conn.commit()
    return len(updates)


def sample_resolved(table: str, sample: int, show: list[str]) -> list[dict[str, Any]]:
    trends = load_json(trend_path())
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM {quote_table(table)}
            WHERE status = 'resolved' OR status = 'pending'
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (sample,),
        ).fetchall()
    price_cache: PriceRowsCache = {}
    sampled: list[dict[str, Any]] = []
    for row in rows:
        event = dict(row)
        p0, event_day, p1, window_day, _event_change_pct, _window_change_pct = find_window_prices(event, trends, price_cache)
        ret = round((p1 - p0) / p0 * 100, 4) if p0 and p1 else event.get("return_pct")
        values = {
            "event_id": event.get("event_id"),
            "view_id": event.get("view_id"),
            "analyst": event.get("analyst"),
            "entity": event.get("entity"),
            "stance": event.get("stance"),
            "window_days": event.get("window_days"),
            "p0": p0 if p0 is not None else event.get("price_at_event"),
            "p1": p1 if p1 is not None else event.get("price_at_window"),
            "event_date": event.get("event_date"),
            "target_date": target_date(event),
            "actual_price_date": window_day,
            "event_price_date": event_day,
            "return_pct": ret,
            "source": "price_trends",
        }
        sampled.append({key: values.get(key) for key in show if key in values})
    return sampled


def update_outcomes(
    limit: int = 100,
    allow_fetch: bool = True,
    since: str | None = None,
    input_table: str = "prediction_events",
    dry_run: bool = False,
    sample: int = 0,
    show: list[str] | None = None,
) -> dict[str, Any]:
    """遍历 pending 事件并回填窗口收益。"""
    trends = load_json(trend_path())
    cache = load_json(cache_path())
    if not trends and cache:
        # market_cache 只有最新价，只能作为存在性兜底，不能构成窗口收益。
        trends = {}

    events = fetch_events(input_table, limit=limit, since=since, status="pending")
    counts = {"processed": 0, "resolved": 0, "error": 0, "skipped": 0}
    examples: list[dict[str, Any]] = []
    price_cache: PriceRowsCache = {}
    fetched_symbols: set[str] = set()
    outcome_updates: list[dict[str, Any]] = []
    market_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        detail = resolve_event_detail(
            event,
            trends,
            price_cache,
            fetched_symbols,
            market_rows,
            allow_fetch=allow_fetch and not dry_run,
        )
        status = detail["status"]
        p0 = detail["price_at_event"]
        p1 = detail["price_at_window"]
        ret = detail["return_pct"]
        outcome_updates.append(
            {
                "event_id": event["event_id"],
                "status": status,
                "price_at_event": p0,
                "price_at_window": p1,
                "return_pct": ret,
            }
        )
        counts["processed"] += 1
        counts[status] = counts.get(status, 0) + 1
        if status == "resolved" and len(examples) < 5:
            examples.append(
                {
                    "event_id": event["event_id"],
                    "analyst": event.get("analyst"),
                    "entity": event.get("entity"),
                    "stance": event.get("stance"),
                    "window_days": event.get("window_days"),
                    "return_pct": ret,
                    "hit": is_hit(str(event.get("stance")), float(ret or 0), window_days=int(event.get("window_days") or 1)),
                }
            )
    if not dry_run:
        update_events(input_table, outcome_updates)
        upsert_market_outcomes_batch(list(market_rows.values()))
    counts["examples"] = examples
    counts["dry_run"] = dry_run
    counts["input"] = input_table
    if sample:
        sample_fields = show or ["event_id", "entity", "stance", "p0", "p1", "event_date", "window_days", "target_date", "actual_price_date", "source"]
        counts["sample"] = sample_resolved(input_table, sample, sample_fields)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 prediction_events 的市场收益")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--since", help="只处理 event_date >= 指定日期的 pending 事件，例如 2026-01-01")
    parser.add_argument("--no-fetch", action="store_true", help="只用本地 price_trends/market_cache，不尝试拉取")
    parser.add_argument("--input", default="prediction_events", help="输入事件表名，默认 prediction_events")
    parser.add_argument("--dry-run", action="store_true", help="只计算不写表")
    parser.add_argument("--sample", type=int, default=0, help="随机抽样 N 条事件打印核对字段")
    parser.add_argument("--show", default="event_id,entity,stance,p0,p1,event_date,window_days,target_date,actual_price_date,source", help="抽样输出字段，逗号分隔")
    args = parser.parse_args()

    show = [item.strip() for item in args.show.split(",") if item.strip()]
    result = update_outcomes(limit=args.limit, allow_fetch=not args.no_fetch, since=args.since, input_table=args.input, dry_run=args.dry_run, sample=args.sample, show=show)
    if not args.since:
        result["note"] = "sector 事件已标记为 skipped 并天然跳过；如旧事件阻塞新事件，建议使用 --since 2026-01-01。"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
