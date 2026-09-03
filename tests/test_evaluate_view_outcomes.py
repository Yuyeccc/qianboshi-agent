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


# ---------- P0.5b：horizon↔窗口匹配 ----------

def test_horizon_none_keeps_legacy_behavior():
    # 不传 horizon = 旧行为不过滤（向后兼容）
    events = [_ev("300308.SZ", "bullish", 6.0, "e1", 5)]
    r = aggregate_view_events(events)
    assert r["suggestion"] == "confirmed", r


def test_medium_view_short_window_only_hold():
    # medium 观点只有 5d 结果（<10d 匹配线）→ 不强行结论
    events = [_ev("300308.SZ", "bullish", 6.0, "e1", 5), _ev("300308.SZ", "bullish", 6.5, "e2", 5)]
    r = aggregate_view_events(events, horizon="medium")
    assert r["suggestion"] == "hold", r
    assert "无匹配窗口事件" in r["reason"]


def test_medium_view_matched_window_confirmed():
    # medium 观点含 10d 结果且达标 → confirmed
    events = [_ev("300308.SZ", "bullish", 6.0, "e1", 5), _ev("300308.SZ", "bullish", 7.5, "e2", 10)]
    r = aggregate_view_events(events, horizon="medium")
    assert r["suggestion"] == "confirmed", r
    # 5d 事件被窗口过滤排除，证据只来自 ≥10d 匹配窗口（1 事件 7.5%）
    assert r["evidence"][0]["windows"] == 1
    assert r["evidence"][0]["avg_return_pct"] == 7.5


def test_medium_view_mixed_direction_conflict():
    # 5d 涨 但 10d 跌 → 过滤后仅看 ≥10d：bearish? bullish+10d 跌 → falsify 票
    events = [_ev("300308.SZ", "bullish", 8.0, "e1", 5),
              _ev("300308.SZ", "bullish", -9.0, "e2", 10)]
    r = aggregate_view_events(events, horizon="medium")
    assert r["suggestion"] == "falsified", r  # 短窗口小涨不救长窗口证伪
    assert "证伪" in r["reason"]


def test_long_view_only_20d():
    # long 观点 10d +6% 不够（需 ≥20d）→ hold；加 20d -8% → falsified
    r = aggregate_view_events([_ev("GOLD", "bullish", 6.0, "e1", 10)], horizon="long")
    assert r["suggestion"] == "hold", r
    r2 = aggregate_view_events([_ev("GOLD", "bullish", 6.0, "e1", 10),
                                _ev("GOLD", "bullish", -8.0, "e2", 20)], horizon="long")
    assert r2["suggestion"] == "falsified", r2


def test_intraday_and_unknown():
    # intraday 1d 即验证
    r = aggregate_view_events([_ev("X", "bullish", 5.5, "e1", 1)], horizon="intraday")
    assert r["suggestion"] == "confirmed", r
    # unknown 保守 ≥10d：5d 结果不构成验证
    r2 = aggregate_view_events([_ev("X", "bullish", 9.0, "e1", 5)], horizon="unknown")
    assert r2["suggestion"] == "hold", r2


def test_empty_hold():
    assert aggregate_view_events([])["suggestion"] == "hold"


def test_band_override():
    # 收紧阈值后小涨不再 confirm
    events = [_ev("300308.SZ", "bullish", 6.0, "e1")]
    assert aggregate_view_events(events, confirm_band=10.0)["suggestion"] == "hold"
    assert aggregate_view_events(events, confirm_band=5.0)["suggestion"] == "confirmed"
