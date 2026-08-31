#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阈值校准分析 单测（64 号方案 C 节，双审融合定稿）。"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from threshold_calibration import (  # noqa: E402
    AUTHORITY_FILE, STATUS_FILE, cluster_by_view, compute_cross, compute_matrix,
    is_hit, wilson_interval,
)

AUTH = {"v1": {"authority": "A"}, "v2": {"authority": "A"},
        "v3": {"authority": "B"}, "v4": {"authority": "B"},
        "v5": {"authority": "C"}, "v6": {"authority": "C"}}


def _events(specs):
    return [{"view_id": v, "stance": s, "window_days": w, "return_pct": r} for v, s, w, r in specs]


class ViewClusterTests(unittest.TestCase):
    def test_01_view_cluster_one_sample_per_view(self):
        """同 view 多窗口只计一次（主窗口 5 优先）"""
        evs = _events([
            ("v1", "bullish", 1, 1.0), ("v1", "bullish", 5, 2.0), ("v1", "bullish", 10, 3.0),
            ("v2", "bearish", 3, -1.0),  # 无 w5 → 取第一条
        ])
        out = cluster_by_view(evs)
        self.assertEqual(len(out), 2)
        self.assertEqual(out["v1"]["window_days"], 5)   # 主窗口优先
        self.assertEqual(out["v2"]["window_days"], 3)   # 缺 w5 取任一
        self.assertEqual(out["v1"]["return_pct"], 2.0)

    def test_02_is_hit_rules(self):
        self.assertTrue(is_hit("bullish", 1.0, 5))
        self.assertFalse(is_hit("bullish", -1.0, 5))
        self.assertTrue(is_hit("bearish", -1.0, 5))
        self.assertTrue(is_hit("risk", -1.2, 10))
        self.assertFalse(is_hit("risk", -0.4, 3))

    def test_03_matrix_view_level(self):
        """矩阵用 view 级独立样本；同 view 多窗口不重复计权"""
        evs = _events([
            ("v1", "bullish", 1, 1.0), ("v1", "bullish", 5, 1.0), ("v1", "bullish", 10, 1.0),  # 3 事件 1 view
            ("v2", "bullish", 5, -1.0),
        ])
        samples = cluster_by_view(evs)
        m = compute_matrix(samples, AUTH)
        # v1/v2 都是 A 级 → n_views=2，hits=1（v1 命中）
        self.assertEqual(m["A"]["n_views"], 2)
        self.assertEqual(m["A"]["hits"], 1)
        self.assertEqual(m["A"]["hit_rate"], 0.5)
        # 事件数 4 但 view 数 2 → 证明未重复计权
        self.assertEqual(len(evs), 4)

    def test_04_wilson_sanity(self):
        lo, hi = wilson_interval(50, 100)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_05_candidate_interval(self):
        """n<30 → None（不校准）；n>=30 → 收缩区间"""
        m = compute_matrix(cluster_by_view(_events([("v%d" % i, "bullish", 5, 1.0 if i % 2 == 0 else -1.0) for i in range(40)])), {"v%d" % i: {"authority": "A"} for i in range(40)})
        self.assertIsNotNone(m["A"]["candidate_interval"])
        lo, hi = m["A"]["candidate_interval"]
        self.assertLessEqual(lo, hi)

    def test_06_cross_exploratory_flag(self):
        """交叉表 n<30 标探索性"""
        evs = _events([("v1", "bullish", 5, 1.0)])
        samples = cluster_by_view(evs)
        cross = compute_cross(samples, AUTH, {"v1": "ok"})
        self.assertTrue(cross["A"]["ok"]["exploratory"])  # n=1 < 30

    def test_07_readonly(self):
        """只读：数据文件 hash 不变"""
        def sha(p):
            return hashlib.sha256(p.read_bytes()).hexdigest()
        before = {str(p): sha(p) for p in (AUTHORITY_FILE, STATUS_FILE)}
        evs = _events([("v1", "bullish", 5, 1.0)])
        compute_matrix(cluster_by_view(evs), json.loads(AUTHORITY_FILE.read_text(encoding="utf-8")))
        after = {str(p): sha(p) for p in (AUTHORITY_FILE, STATUS_FILE)}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
