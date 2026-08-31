#!/usr/bin/env python3
"""分析师预测事件构建器。"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from decision_db import clear_prediction_backtest, connect, upsert_prediction_events
from entity_normalizer import is_banned_source, load_aliases
from view_store import filter_views, load_views, views_path


WINDOW_DAYS = [1, 3, 5, 10, 20]
PREDICTIVE_STANCES = {"bullish", "bearish", "risk"}
SH_PREFIXES = ("600", "601", "603", "605", "688", "510", "512", "515", "516", "518", "588")
SZ_PREFIXES = ("000", "001", "002", "003", "300", "301", "150", "159", "160", "161", "162")
A_SHARE_PREFIXES = ("60", "68", "00", "30", "15", "51", "56", "58", "512", "515", "516", "518", "588")
FAKE_NUMBERS = {"000000", "111111", "222222", "333333", "444444", "555555", "666666", "777777", "888888", "999999", "123456", "654321"}
TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SYMBOL_RE = re.compile(r"^\d{6}\.(SS|SZ|HK)$")

# 数据质量黑名单：yfinance 份额折算跳变/不可信标的（2026-08-06 血泪坑：159813 7-31:1.432→8-06:0.77 假跳变）
DATA_QUALITY_BLACKLIST = {"159813.SZ"}


def quote_table(name: str) -> str:
    if not TABLE_NAME_RE.fullmatch(name):
        raise ValueError(f"非法表名: {name}")
    return f'"{name}"'


def normalize_symbol(value: str) -> str:
    """标准化股票/ETF 代码。"""
    symbol = str(value or "").strip().upper()
    if not symbol:
        return ""
    symbol = symbol.replace("SH.", "").replace("SZ.", "")
    if re.fullmatch(r"\d{6}\.(SS|SZ|HK)", symbol):
        return symbol
    if re.fullmatch(r"\d{6}", symbol):
        if symbol.startswith(SH_PREFIXES):
            return f"{symbol}.SS"
        if symbol.startswith(SZ_PREFIXES):
            return f"{symbol}.SZ"
    return symbol


def is_valid_symbol(code: str) -> bool:
    """噪音清洗：格式、A 股段位和明显假代码过滤。"""
    symbol = normalize_symbol(code)
    if not SYMBOL_RE.fullmatch(symbol):
        return False
    digits, suffix = symbol.split(".")
    if digits in FAKE_NUMBERS or len(set(digits)) == 1:
        return False
    # 数据质量黑名单：yfinance 份额折算跳变不可信标的（2026-08-06）
    if symbol in DATA_QUALITY_BLACKLIST:
        return False
    if suffix == "HK":
        return True
    return any(digits.startswith(prefix) for prefix in A_SHARE_PREFIXES)


def _load_known_symbols() -> set[str]:
    root = Path(__file__).resolve().parents[1]
    symbols: set[str] = set()
    for path in (root / "data" / "price_trends.json", root / "data" / "market_cache.json"):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if path.name == "market_cache.json":
            data = data.get("symbols") if isinstance(data, dict) else {}
        if isinstance(data, dict):
            symbols.update(str(key).upper() for key in data.keys())
    return symbols


def _values(items: Any) -> list[str]:
    if isinstance(items, list):
        return [str(item).strip() for item in items if str(item).strip()]
    if isinstance(items, str) and items.strip():
        return [items.strip()]
    return []


def pick_entities(view: dict[str, Any], known_symbols: set[str] | None = None) -> tuple[list[dict[str, str]], int]:
    """按 stocks 后 etfs 的原顺序返回全部合法标的，并在同观点内去重。"""
    entities = view.get("entities") or {}
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    invalid = 0
    known_symbols = known_symbols or set()
    for entity_type, key in (("stock", "stocks"), ("etf", "etfs")):
        for raw in _values(entities.get(key)):
            symbol = normalize_symbol(raw)
            if not is_valid_symbol(symbol) or (known_symbols and symbol not in known_symbols):
                invalid += 1
                continue
            dedupe_key = (symbol, entity_type)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            result.append({"entity": symbol, "entity_type": entity_type})
    return result, invalid


def pick_entity(view: dict[str, Any]) -> tuple[str, str, str | None]:
    """legacy：按股票、ETF、板块顺序取首个实体。"""
    entities = view.get("entities") or {}
    stocks = entities.get("stocks") or []
    if stocks:
        return normalize_symbol(stocks[0]), "stock", None
    etfs = entities.get("etfs") or []
    if etfs:
        return normalize_symbol(etfs[0]), "etf", None
    sectors = entities.get("sectors") or []
    if sectors:
        return str(sectors[0]).strip(), "sector", "sector_no_market_data"
    return "", "", "no_entity"


def build_event(
    view: dict[str, Any],
    window_days: int,
    entity: str | None = None,
    entity_type: str | None = None,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    if entity is None or entity_type is None:
        entity, entity_type, skip_reason = pick_entity(view)
    status = "skipped" if skip_reason in {"sector_no_market_data", "sector_outcome_unsupported", "no_valid_entity"} else "error" if skip_reason else "pending"
    event_id = f"pred_{view.get('view_id')}_{entity_type}_{entity}_{window_days}"
    return {
        "event_id": event_id,
        "view_id": view.get("view_id"),
        "analyst": view.get("analyst", ""),
        "entity": entity,
        "entity_type": entity_type,
        "stance": view.get("stance", ""),
        "horizon": view.get("horizon", "") or "unknown",
        "claim": view.get("claim", ""),
        "event_date": view.get("date", ""),
        "window_days": window_days,
        "price_at_event": None,
        "price_at_window": None,
        "return_pct": None,
        "status": status,
        "skip_reason": skip_reason,
    }


def load_prediction_views(path: str | Path | None = None) -> list[dict[str, Any]]:
    """轻量读取观点库；避免 load_views 每条重复加载别名造成扫描过慢。"""
    _ = (load_views, filter_views)
    source = Path(path) if path else views_path()
    if not source.exists():
        return []
    aliases = load_aliases()
    views: list[dict[str, Any]] = []
    seen: set[str] = set()
    with source.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                view = json.loads(line)
            except Exception:
                continue
            if is_banned_source(view.get("source_file", ""), aliases) or is_banned_source(view.get("analyst", ""), aliases):
                continue
            view_id = view.get("view_id") or f"{view.get('source_file')}|{view.get('claim')}"
            if view_id in seen:
                continue
            seen.add(str(view_id))
            views.append(view)
    return views


def _filtered_views(path: str | Path | None, since: str | None, limit: int | None) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for view in load_prediction_views(path=path):
        if view.get("stance") not in PREDICTIVE_STANCES:
            continue
        if not view.get("date"):
            continue
        if since and str(view.get("date"))[:10] < since:
            continue
        views.append(view)
        if limit and len(views) >= limit:
            break
    return views


def _sector_value(view: dict[str, Any]) -> str:
    sectors = _values((view.get("entities") or {}).get("sectors"))
    return sectors[0] if sectors else ""


def build_multiplex_events(
    path: str | Path | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    views = _filtered_views(path, since, limit)
    known_symbols = _load_known_symbols()
    events: list[dict[str, Any]] = []
    entities_seen: set[tuple[str, str]] = set()
    invalid_codes = 0
    sector_only_views = 0
    for view in views:
        picked, invalid = pick_entities(view, known_symbols)
        invalid_codes += invalid
        if picked:
            for item in picked:
                entities_seen.add((item["entity"], item["entity_type"]))
                for window in WINDOW_DAYS:
                    events.append(build_event(view, window, item["entity"], item["entity_type"]))
            continue
        sector = _sector_value(view)
        if sector:
            sector_only_views += 1
            for window in WINDOW_DAYS:
                events.append(build_event(view, window, sector, "sector", "sector_outcome_unsupported"))
            continue
        for window in WINDOW_DAYS:
            events.append(build_event(view, window, "", "", "no_valid_entity"))
    stats = {
        "views": len(views),
        "events": len(events),
        "entities": len(entities_seen),
        "invalid_codes": invalid_codes,
        "sector_only_views": sector_only_views,
    }
    return events, stats


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({quote_table(table)})").fetchall()}


def ensure_event_table(conn: sqlite3.Connection, table: str) -> None:
    quoted = quote_table(table)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {quoted} (
            event_id TEXT PRIMARY KEY,
            view_id TEXT,
            analyst TEXT,
            entity TEXT,
            entity_type TEXT,
            stance TEXT,
            horizon TEXT,
            claim TEXT,
            event_date TEXT,
            window_days INTEGER,
            price_at_event REAL,
            price_at_window REAL,
            return_pct REAL,
            status TEXT,
            skip_reason TEXT
        )
        """
    )
    columns = _table_columns(conn, table)
    if "skip_reason" not in columns and table != "prediction_events":
        conn.execute(f"ALTER TABLE {quoted} ADD COLUMN skip_reason TEXT")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_status_date ON {quoted}(status, event_date)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_entity_date ON {quoted}(entity, event_date)")
    conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_unique_event ON {quoted}(view_id, entity, entity_type, window_days)")
    conn.commit()


def write_events(events: list[dict[str, Any]], output: str, rebuild: bool = False) -> int:
    if output == "prediction_events" and not any("skip_reason" in event for event in events):
        if rebuild:
            clear_prediction_backtest()
        return upsert_prediction_events(events)
    with connect() as conn:
        ensure_event_table(conn, output)
        if rebuild or output != "prediction_events":
            conn.execute(f"DELETE FROM {quote_table(output)}")
        columns = [
            "event_id", "view_id", "analyst", "entity", "entity_type", "stance", "horizon", "claim",
            "event_date", "window_days", "price_at_event", "price_at_window", "return_pct", "status",
        ]
        if "skip_reason" in _table_columns(conn, output):
            columns.append("skip_reason")
        names = ", ".join(columns)
        values = ", ".join(f":{column}" for column in columns)
        updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "event_id")
        conn.executemany(
            f"""
            INSERT INTO {quote_table(output)} ({names})
            VALUES ({values})
            ON CONFLICT(event_id) DO UPDATE SET {updates}
            """,
            events,
        )
        conn.commit()
    return len(events)


def scan_views_for_predictions(
    path: str | Path | None = None,
    rebuild: bool = False,
    since: str | None = None,
    limit: int | None = None,
    mode: str = "legacy",
    output: str = "prediction_events",
    stats_only: bool = False,
) -> list[dict[str, Any]]:
    if mode == "multiplex":
        events, stats = build_multiplex_events(path=path, since=since, limit=limit)
        print(
            "stats "
            f"views={stats['views']} events={stats['events']} entities={stats['entities']} "
            f"invalid_codes={stats['invalid_codes']} sector_only_views={stats['sector_only_views']}"
        )
        if not stats_only:
            write_events(events, output=output, rebuild=rebuild)
        return events

    views = _filtered_views(path, since, limit)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for view in views:
        view_id = view.get("view_id")
        if not view_id or view_id in seen:
            continue
        seen.add(str(view_id))
        entity, _, skip_reason = pick_entity(view)
        if skip_reason == "no_entity" or not entity:
            continue
        for window in WINDOW_DAYS:
            event = build_event(view, window)
            event["event_id"] = f"pred_{view.get('view_id')}_{window}"
            event.pop("skip_reason", None)
            events.append(event)
    if not stats_only:
        if output != "prediction_events":
            write_events(events, output=output, rebuild=rebuild)
        else:
            if rebuild:
                clear_prediction_backtest()
            upsert_prediction_events(events)
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="构建分析师预测回测事件")
    parser.add_argument("--rebuild", action="store_true", help="清空并重建输出事件表")
    parser.add_argument("--mode", choices=["legacy", "multiplex"], default="legacy", help="事件生成模式，默认 legacy")
    parser.add_argument("--since", help="只处理 event_date >= 指定日期的观点，例如 2026-07-01")
    parser.add_argument("--limit", type=int, help="最多处理观点数")
    parser.add_argument("--output", default="prediction_events", help="输出事件表名，默认 prediction_events")
    parser.add_argument("--stats-only", action="store_true", help="只打印统计，不写表")
    args = parser.parse_args()

    events = scan_views_for_predictions(
        rebuild=args.rebuild,
        since=args.since,
        limit=args.limit,
        mode=args.mode,
        output=args.output,
        stats_only=args.stats_only,
    )
    pending = sum(1 for event in events if event.get("status") == "pending")
    skipped = sum(1 for event in events if event.get("status") == "skipped")
    error = len(events) - pending - skipped
    print(f"{args.output}={len(events)} pending={pending} skipped={skipped} error={error}")


if __name__ == "__main__":
    main()
