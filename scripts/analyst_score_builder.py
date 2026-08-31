#!/usr/bin/env python3
"""分析师回测评分构建器。"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from decision_db import connect, upsert_analyst_scores
from outcome_updater import is_hit


TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_table(name: str) -> str:
    if not TABLE_NAME_RE.fullmatch(name):
        raise ValueError(f"非法表名: {name}")
    return f'"{name}"'


def fetch_resolved_events(input_table: str = "prediction_events") -> list[dict[str, Any]]:
    """读取已回填收益的预测事件。"""
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT analyst, entity, horizon, window_days, stance, return_pct
            FROM {quote_table(input_table)}
            WHERE status = 'resolved' AND return_pct IS NOT NULL
            """
        ).fetchall()
    return [dict(row) for row in rows]


def wilson_interval(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    phat = hits / total
    denom = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom)


def build_scores(input_table: str = "prediction_events") -> list[dict[str, Any]]:
    """按 (analyst, entity, window_days) 聚合命中率和平均收益。"""
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for event in fetch_resolved_events(input_table):
        key = (event.get("analyst") or "", event.get("entity") or "", int(event.get("window_days") or 0))
        groups[key].append(event)

    now = datetime.now().isoformat(timespec="seconds")
    scores: list[dict[str, Any]] = []
    for (analyst, entity, window_days), events in groups.items():
        horizons = sorted({str(event.get("horizon") or "unknown") for event in events})
        sample_count = len(events)
        hits = sum(1 for event in events if is_hit(str(event.get("stance")), float(event.get("return_pct") or 0), window_days=int(event.get("window_days") or 1)))
        hit_rate = hits / sample_count if sample_count else 0.0
        avg_return = sum(float(event.get("return_pct") or 0) for event in events) / sample_count if sample_count else 0.0
        sample_small = sample_count < 3
        score = hit_rate * (0.5 if sample_small else 1.0)
        scores.append(
            {
                "analyst": analyst,
                "entity": entity,
                "horizon": ",".join(horizons),
                "window_days": window_days,
                "sample_count": sample_count,
                "hit_rate": round(hit_rate, 4),
                "avg_return": round(avg_return, 4),
                "score": round(score, 4),
                "sample_small": sample_small,
                "updated_at": now,
            }
        )
    scores.sort(key=lambda item: (item["score"], item["sample_count"]), reverse=True)
    upsert_analyst_scores(scores)
    return scores


def fetch_view_level_rows(input_table: str) -> list[dict[str, Any]]:
    """按 view_id/window_days 一次计权；任一实体命中即观点命中。"""
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT analyst, view_id, window_days,
                   MAX(CASE
                       WHEN status = 'resolved'
                        AND (
                           (stance = 'bullish' AND return_pct > 0)
                           OR (stance = 'bearish' AND return_pct < 0)
                           OR (stance = 'risk' AND window_days <= 3 AND return_pct < -0.5)
                           OR (stance = 'risk' AND window_days > 3 AND window_days <= 10 AND return_pct < -1.0)
                           OR (stance = 'risk' AND window_days > 10 AND return_pct < -2.0)
                        )
                       THEN 1 ELSE 0 END) AS view_hit,
                   MAX(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS has_resolved,
                   COUNT(*) AS event_rows
            FROM {quote_table(input_table)}
            WHERE entity_type IN ('stock', 'etf')
            GROUP BY analyst, view_id, window_days
            """
        ).fetchall()
    return [dict(row) for row in rows]


def build_view_report(input_table: str, min_sample: int = 0, confidence: str | None = None) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in fetch_view_level_rows(input_table):
        if int(row.get("has_resolved") or 0) != 1:
            continue
        groups[(row.get("analyst") or "", int(row.get("window_days") or 0))].append(row)

    report: list[dict[str, Any]] = []
    for (analyst, window_days), rows in groups.items():
        sample_count = len(rows)
        hits = sum(int(row.get("view_hit") or 0) for row in rows)
        hit_rate = hits / sample_count if sample_count else 0.0
        item: dict[str, Any] = {
            "analyst": analyst,
            "window_days": window_days,
            "hit_views": hits,
            "sample_count": sample_count,
            "hit_rate": round(hit_rate, 4),
            "ranked": sample_count >= min_sample,
        }
        if confidence == "wilson":
            low, high = wilson_interval(hits, sample_count)
            item["wilson_low"] = round(low, 4)
            item["wilson_high"] = round(high, 4)
        report.append(item)
    report.sort(key=lambda item: (item["ranked"], item["hit_rate"], item["sample_count"]), reverse=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 analyst_scores")
    parser.add_argument("--input", default="prediction_events", help="输入事件表名，默认 prediction_events")
    parser.add_argument("--dedupe-view", action="store_true", help="观点层一次计权")
    parser.add_argument("--report", action="store_true", help="输出分析师×窗口完整报表")
    parser.add_argument("--min-sample", type=int, default=0, help="样本数小于 N 不参与排名")
    parser.add_argument("--confidence", choices=["wilson"], help="置信区间算法")
    args = parser.parse_args()

    if args.dedupe_view or args.report:
        report = build_view_report(args.input, min_sample=args.min_sample, confidence=args.confidence)
        print(json.dumps({"input": args.input, "weighting": "view_level", "rows": len(report), "report": report}, ensure_ascii=False, indent=2))
        return

    scores = build_scores(args.input)
    print(json.dumps({"input": args.input, "score_count": len(scores), "top10": scores[:10]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
