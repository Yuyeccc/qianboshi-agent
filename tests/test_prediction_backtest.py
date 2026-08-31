#!/usr/bin/env python3
"""分析师回测 MVP 真实数据烟测。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyst_score_builder import build_scores
from decision_db import connect
from outcome_updater import update_outcomes
from prediction_event_builder import scan_views_for_predictions


def resolved_examples(limit: int = 5) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT event_id, analyst, entity, stance, horizon, window_days, return_pct, status
            FROM prediction_events
            WHERE status = 'resolved'
            ORDER BY event_date, event_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def main() -> None:
    events = scan_views_for_predictions(rebuild=True)
    assert len(events) > 100, f"prediction_events too few: {len(events)}"
    print(f"generated_events={len(events)}")

    outcome_result = update_outcomes(limit=500, allow_fetch=False)
    print("outcome_result=" + json.dumps(outcome_result, ensure_ascii=False, indent=2))

    examples = resolved_examples()
    print("resolved_examples=" + json.dumps(examples, ensure_ascii=False, indent=2))

    scores = build_scores()
    print("analyst_scores_top10=" + json.dumps(scores[:10], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
