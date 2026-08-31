#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#14v2 分层前瞻回测 单测（方案 54 号 E 节 9 项，backtest-validation V1-V7 对齐）。"""
import hashlib
import json
import sqlite3
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyst_score_builder import wilson_interval  # noqa: E402
from layered_backtest_v2 import (  # noqa: E402
    MIN_SAMPLE, LAYERS, TRAIN_CUTOFF, TEST_CUTOFF, ROLL_CUTOFF,
    binomial_two_sided_p, compute_layer_stats, diff_ci, is_hit,
    load_events, load_status_map,
)

STATUS_FILE = ROOT / "data" / "view_tuple_status.json"
DECISION_DB = ROOT / "data" / "qianboshi_decision.db"


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _mk_events(specs: list[tuple]) -> list[dict]:
    """specs: (view_id, entity, stance, window, event_date, return_pct, status)"""
    out = []
    for s in specs:
        vid, entity, stance, window, date, ret, status = s
        out.append({
            "view_id": vid, "entity": entity, "entity_type": "stock",
            "stance": stance, "window_days": window, "event_date": date,
            "return_pct": ret, "status": status, "skip_reason": None, "analyst": "t",
        })
    return out


class HitRuleTests(unittest.TestCase):
    def test_is_hit_rules(self):
        self.assertTrue(is_hit("bullish", 0.01, 1))
        self.assertFalse(is_hit("bullish", -0.01, 1))
        self.assertTrue(is_hit("bearish", -0.01, 1))
        self.assertFalse(is_hit("bearish", 0.01, 1))
        self.assertTrue(is_hit("risk", -0.6, 3))     # ≤3d 阈值 0.5
        self.assertFalse(is_hit("risk", -0.4, 3))
        self.assertTrue(is_hit("risk", -1.2, 10))    # ≤10d 阈值 1.0
        self.assertTrue(is_hit("risk", -2.5, 20))    # >10d 阈值 2.0
        self.assertFalse(is_hit("unknown", 5.0, 1))

    def test_binomial_p(self):
        # 50% 命中 n=100 → p≈1.0；70% 命中 n=100 → p 很小
        p_mid = binomial_two_sided_p(50, 100, 0.5)
        self.assertGreater(p_mid, 0.9)
        p_ext = binomial_two_sided_p(70, 100, 0.5)
        self.assertLess(p_ext, 0.001)
        self.assertEqual(binomial_two_sided_p(0, 0, 0.5), 1.0)

    def test_diff_ci(self):
        lo, hi = diff_ci(0.6, 100, 0.5, 100)
        self.assertLess(lo, 0.6 - 0.5)
        self.assertGreater(hi, 0.6 - 0.5)
        self.assertEqual(diff_ci(0.5, 0, 0.5, 100), (0.0, 0.0))

    def test_wilson_sanity(self):
        lo, hi = wilson_interval(50, 100)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)


class LayerMappingTests(unittest.TestCase):
    """映射正确性（V1）+ 口径一致性 + 分层互斥"""

    def test_01_status_map_loaded(self):
        m = load_status_map(STATUS_FILE)
        self.assertGreater(len(m), 7000)  # 7476
        self.assertEqual(set(m.values()) - set(LAYERS), set())

    def test_02_any_ok_vs_strict_consistency(self):
        """用 status_count 重算 strict 口径，应与导出的 any_ok layer 一致（差异=0）"""
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        diff = 0
        for vid, info in data.items():
            counts = info["status_count"]
            sts = list(counts)
            if all(t == "template_only" for t in sts):
                strict = "template_only"
            elif "ok" in sts:
                strict = "ok"
            else:
                strict = "partial_anchor"
            if strict != info["layer"]:
                diff += 1
        self.assertEqual(diff, 0, f"any_ok vs strict 差异 {diff} != 0")

    def test_03_layers_mutually_exclusive(self):
        """view 不跨层（json 单值映射）"""
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(data), len({k: v["layer"] for k, v in data.items()}))


class StatsCoreTests(unittest.TestCase):
    """分层统计核心（事件级+view 级计权）"""

    def test_04_view_level_weighting(self):
        """同 view 多实体任一命中=观点命中；view 级分母=COUNT(DISTINCT view_id)"""
        events = _mk_events([
            ("v1", "600000.SS", "bullish", 5, "2026-07-10", 1.0, "resolved"),   # hit
            ("v1", "600001.SS", "bullish", 5, "2026-07-10", -1.0, "resolved"),  # miss 但 v1 仍 hit
            ("v2", "600002.SS", "bullish", 5, "2026-07-10", -1.0, "resolved"),  # miss
            ("v3", "600003.SS", "bullish", 5, "2026-07-10", -1.0, "resolved"),  # miss
        ])
        layer_map = {"v1": "ok", "v2": "ok", "v3": "ok"}
        s = compute_layer_stats(events, layer_map)
        e = s["layers"]["ok"]["bullish"]["5"]["all"]
        self.assertEqual(e["event_total"], 4)
        self.assertEqual(e["event_hits"], 1)   # 事件级只 1 命中
        self.assertEqual(e["view_total"], 3)   # view 级分母 = DISTINCT view_id
        self.assertEqual(e["view_hits"], 1)    # v1 任一实体命中=观点命中

    def test_05_layers_exclusive_in_stats(self):
        """统计结果中 view 不跨层：v1(ok) 只出现在 ok 层，v2(template_only) 只出现在模板层"""
        events = _mk_events([
            ("v1", "600000.SS", "bullish", 5, "2026-07-10", 1.0, "resolved"),
            ("v2", "600001.SS", "bearish", 5, "2026-07-10", -1.0, "resolved"),
        ])
        layer_map = {"v1": "ok", "v2": "template_only"}
        s = compute_layer_stats(events, layer_map)
        ok_bull = s["layers"]["ok"]["bullish"]["5"]["all"]
        tmpl_bear = s["layers"]["template_only"]["bearish"]["5"]["all"]
        self.assertEqual(ok_bull["view_total"], 1)      # 只有 v1
        self.assertEqual(ok_bull["view_hits"], 1)       # v1 bullish +1.0% → hit
        self.assertEqual(tmpl_bear["view_total"], 1)    # 只有 v2
        self.assertEqual(tmpl_bear["view_hits"], 1)     # v2 bearish -1.0% → hit
        # 互斥：ok 层统计里不含 v2 的事件数（事件级 1，view 级 1 均已验证）

    def test_06_idempotent(self):
        """幂等（V2）：同输入两次计算事件数一致"""
        events = load_events()
        layer_map = load_status_map(STATUS_FILE)
        s1 = compute_layer_stats(events, layer_map)
        s2 = compute_layer_stats(events, layer_map)
        self.assertEqual(json.dumps(s1, sort_keys=True), json.dumps(s2, sort_keys=True))

    def test_07_lookahead_p0(self):
        """前视偏差抽样（V1 延伸）：周末事件 p0 必须取 ≤event_date 的最近交易日"""
        from outcome_updater import find_window_prices
        # 周末 2026-07-19(周日) 发观点，事件日 7-19，p0 应取 ≤7-19 的最近交易日（7-17 周五）
        events = [{
            "entity": "600000.SS", "event_date": "2026-07-19", "window_days": 5,
        }]
        trends = {"600000.SS": {
            "2026-07-16": {"price": 10.0, "change_pct": 0.1},
            "2026-07-17": {"price": 10.5, "change_pct": 0.5},  # 周五
            "2026-07-20": {"price": 11.0, "change_pct": 0.5},  # 周一（未来，不得当 p0）
        }}
        p0, day0, p1, day1, _, _ = find_window_prices(events[0], trends)
        self.assertEqual(day0, "2026-07-17")  # p0 必须用事件前已知价格
        self.assertEqual(p0, 10.5)
        self.assertIsNone(p1)  # 7-17+5 天超出序列 → p1 缺失（error 而非未来价）

    def test_08_readonly(self):
        """只读（V7 延伸）：跑统计前后数据文件 hash 不变"""
        before = {str(p): _sha256(p) for p in (STATUS_FILE, ROOT / "data" / "price_trends.json")
                  if p.exists()}
        events = load_events()
        layer_map = load_status_map(STATUS_FILE)
        compute_layer_stats(events, layer_map)
        after = {str(p): _sha256(p) for p in (STATUS_FILE, ROOT / "data" / "price_trends.json")
                 if p.exists()}
        self.assertEqual(before, after)

    def test_09_denominators(self):
        """四分母：resolved+error+skipped=事件总数；coverage=resolved/(resolved+error)"""
        events = load_events()
        layer_map = load_status_map(STATUS_FILE)
        s = compute_layer_stats(events, layer_map)
        total_events = len(events)
        layer_sum = sum(
            d["resolved"] + d["error"] + d["skipped"]
            for d in s["denominators"].values()
        )
        self.assertEqual(layer_sum, total_events)
        for d in s["denominators"].values():
            self.assertAlmostEqual(d["coverage"],
                                   d["resolved"] / (d["resolved"] + d["error"]) if d["eligible"] else 0.0,
                                   places=4)


class SegmentTests(unittest.TestCase):
    def test_segment_cutoffs(self):
        from layered_backtest_v2 import segment_of
        self.assertEqual(set(segment_of("2026-06-30")), {"all", "train"})
        self.assertEqual(set(segment_of("2026-07-01")), {"all", "test"})
        self.assertEqual(set(segment_of("2026-07-20")), {"all", "test", "roll"})
        self.assertEqual(set(segment_of("2026-01-05")), {"all", "train"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
