#!/usr/bin/env python3
"""evaluate_view_outcomes 聚合规则单测（记忆体系 P0.5）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from evaluate_view_outcomes import aggregate_view_events  # noqa: E402


def _ev(entity, stance, ret, event_id="e1", window=5):
    return {"event_id": event_id, "entity": entity, "stance": stance,
            "window_days": window, "return_pct": ret}


def test_bullish_deep_fail_falsified():
    # 单实体多窗口：300308 平均深跌 -> falsified
    events = [_ev("300308.SZ", "bullish", -2.7, "e1", 1), _ev("300308.SZ", "bullish", -16.5, "e2", 20)]
    r = aggregate_view_events(events)
    assert r["suggestion"] == "falsified", r
    assert "300308.SZ" in r["evidence"][0]["entity"]


def test_bullish_gain_confirmed():
    events = [_ev("300308.SZ", "bullish", 3.2, "e1", 1), _ev("300308.SZ", "bullish", 12.1, "e2", 20)]
    r = aggregate_view_events(events)
    assert r["suggestion"] == "confirmed", r


def test_mixed_entities_conflict_hold():
    # 一实体验证 + 一实体证伪 -> hold（不强行结论）
    events = [
        _ev("300308.SZ", "bullish", 8.0, "e1"),
        _ev("300502.SZ", "bullish", -9.0, "e2"),
    ]
    r = aggregate_view_events(events)
    assert r["suggestion"] == "hold", r
    assert "冲突" in r["reason"]


def test_small_move_no_ticket_hold():
    # 收益未达阈值 -> hold
    events = [_ev("300308.SZ", "bullish", -2.0, "e1")]
    r = aggregate_view_events(events)
    assert r["suggestion"] == "hold", r


def test_bearish_reversal_falsified():
    # 看空但大涨 -> falsified
    events = [_ev("688981.SS", "bearish", 9.5, "e1")]
    r = aggregate_view_events(events)
    assert r["suggestion"] == "falsified", r


def test_bearish_drop_confirmed():
    events = [_ev("688981.SS", "bearish", -8.2, "e1")]
    r = aggregate_view_events(events)
    assert r["suggestion"] == "confirmed", r


def test_empty_hold():
    assert aggregate_view_events([])["suggestion"] == "hold"


def test_band_override():
    # 收紧阈值后小涨不再 confirm
    events = [_ev("300308.SZ", "bullish", 6.0, "e1")]
    assert aggregate_view_events(events, confirm_band=10.0)["suggestion"] == "hold"
    assert aggregate_view_events(events, confirm_band=5.0)["suggestion"] == "confirmed"
