#!/usr/bin/env python3
"""对比两张预测事件表的回测结果。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from decision_db import connect
from outcome_updater import is_hit


TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_table(name: str) -> str:
    if not TABLE_NAME_RE.fullmatch(name):
        raise ValueError(f"非法表名: {name}")
    return f'"{name}"'


def fetch_events(table: str, since: str | None) -> list[dict[str, Any]]:
    where = ""
    params: list[Any] = []
    if since:
        where = "WHERE event_date >= ?"
        params.append(since)
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM {quote_table(table)} {where}", params).fetchall()
    return [dict(row) for row in rows]


def event_hit(event: dict[str, Any]) -> bool:
    return is_hit(str(event.get("stance")), float(event.get("return_pct") or 0), int(event.get("window_days") or 1))


def summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [event for event in events if event.get("status") == "resolved" and event.get("return_pct") is not None]
    hits = sum(1 for event in resolved if event_hit(event))
    direction_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in resolved:
        direction_groups[str(event.get("stance") or "unknown")].append(event)
    direction_hit_rate = {}
    for stance, rows in sorted(direction_groups.items()):
        direction_hit_rate[stance] = {
            "events": len(rows),
            "hit_rate": round(sum(1 for row in rows if event_hit(row)) / len(rows), 4) if rows else 0.0,
        }
    return {
        "events": len(events),
        "evaluable": len(resolved),
        "hits": hits,
        "hit_rate": round(hits / len(resolved), 4) if resolved else 0.0,
        "direction_hit_rate": direction_hit_rate,
    }


def analyst_rates(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("status") == "resolved" and event.get("return_pct") is not None:
            groups[str(event.get("analyst") or "")].append(event)
    result: dict[str, dict[str, Any]] = {}
    for analyst, rows in groups.items():
        hits = sum(1 for row in rows if event_hit(row))
        result[analyst] = {"events": len(rows), "hit_rate": hits / len(rows) if rows else 0.0}
    return result


def biggest_analyst_changes(before: list[dict[str, Any]], after: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    before_rates = analyst_rates(before)
    after_rates = analyst_rates(after)
    changes = []
    for analyst in sorted(set(before_rates) | set(after_rates)):
        old = before_rates.get(analyst, {"events": 0, "hit_rate": 0.0})
        new = after_rates.get(analyst, {"events": 0, "hit_rate": 0.0})
        changes.append(
            {
                "analyst": analyst,
                "before_events": old["events"],
                "after_events": new["events"],
                "before_hit_rate": round(old["hit_rate"], 4),
                "after_hit_rate": round(new["hit_rate"], 4),
                "delta_hit_rate": round(new["hit_rate"] - old["hit_rate"], 4),
                "delta_events": new["events"] - old["events"],
            }
        )
    changes.sort(key=lambda item: (abs(item["delta_hit_rate"]), abs(item["delta_events"])), reverse=True)
    return changes[:limit]


def new_entity_contributions(before: list[dict[str, Any]], after: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    before_keys = {(event.get("view_id"), event.get("entity"), event.get("entity_type"), event.get("window_days")) for event in before}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in after:
        key = (event.get("view_id"), event.get("entity"), event.get("entity_type"), event.get("window_days"))
        if key not in before_keys:
            groups[(str(event.get("entity") or ""), str(event.get("entity_type") or ""))].append(event)
    rows = []
    for (entity, entity_type), events in groups.items():
        resolved = [event for event in events if event.get("status") == "resolved" and event.get("return_pct") is not None]
        hits = sum(1 for event in resolved if event_hit(event))
        rows.append(
            {
                "entity": entity,
                "entity_type": entity_type,
                "new_events": len(events),
                "evaluable": len(resolved),
                "hit_rate": round(hits / len(resolved), 4) if resolved else None,
            }
        )
    rows.sort(key=lambda item: (item["new_events"], item["evaluable"]), reverse=True)
    return rows[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description="对比两张预测事件表")
    parser.add_argument("--before", required=True, help="改造前事件表")
    parser.add_argument("--after", required=True, help="改造后事件表")
    parser.add_argument("--since", help="只比较 event_date >= 指定日期")
    args = parser.parse_args()

    before_events = fetch_events(args.before, args.since)
    after_events = fetch_events(args.after, args.since)
    before_summary = summary(before_events)
    after_summary = summary(after_events)
    result = {
        "before": args.before,
        "after": args.after,
        "since": args.since,
        "before_summary": before_summary,
        "after_summary": after_summary,
        "delta": {
            "events": after_summary["events"] - before_summary["events"],
            "evaluable": after_summary["evaluable"] - before_summary["evaluable"],
            "hit_rate": round(after_summary["hit_rate"] - before_summary["hit_rate"], 4),
        },
        "biggest_analyst_changes": biggest_analyst_changes(before_events, after_events),
        "new_entity_contributions": new_entity_contributions(before_events, after_events),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
