#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prediction_confidence 消费层 单测（66 号方案 D 节）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prediction_confidence import TABLE, attach_to_view, prediction_confidence  # noqa: E402
from view_store import score_view  # noqa: E402


class PredictionConfidenceTests(unittest.TestCase):
    def test_01_lookup_table(self):
        """查表：A×ok=0.59 / C×template=0.50 / D×partial=0.49"""
        self.assertEqual(prediction_confidence("A", "ok"), 0.59)
        self.assertEqual(prediction_confidence("C", "template_only"), 0.50)
        self.assertEqual(prediction_confidence("D", "partial_anchor"), 0.49)
        self.assertEqual(prediction_confidence("B", "ok"), 0.65)

    def test_02_unknown_returns_neutral(self):
        """未知组合 → 0.5 不崩"""
        self.assertEqual(prediction_confidence("X", "ok"), 0.5)
        self.assertEqual(prediction_confidence("A", "unknown"), 0.5)
        self.assertEqual(prediction_confidence("", ""), 0.5)
        self.assertEqual(prediction_confidence(None, None), 0.5)

    def test_03_attach_to_view(self):
        """attach_to_view：带字段注入，缺字段原样返回"""
        v = {"view_id": "v1", "evidence_authority": "a", "tuple_status": "ok"}
        out = attach_to_view(v)
        self.assertEqual(out["prediction_confidence"], 0.59)
        # 大小写/缺字段
        self.assertEqual(attach_to_view({"evidence_authority": "A"}), {"evidence_authority": "A"})
        self.assertEqual(attach_to_view({}), {})

    def test_04_score_view_uses_prediction(self):
        """score_view：prediction_confidence 优先，缺失回退 confidence"""
        base = {"entities": {"stocks": ["600000.SS"]}, "view_type": "market"}
        with_pred = dict(base, prediction_confidence=0.59, confidence=0.9)
        with_conf = dict(base, confidence=0.9)
        s_pred = score_view(with_pred)
        s_conf = score_view(with_conf)
        # 0.59*0.10 vs 0.9*0.10 → 有 prediction_confidence 时分数更低（0.031 差）
        self.assertAlmostEqual(s_pred - s_conf, (0.59 - 0.9) * 0.10, places=4)
        # 无任何字段 → 默认 0.5
        s_none = score_view(dict(base))
        self.assertAlmostEqual(s_none, s_conf + (0.5 - 0.9) * 0.10, places=4)

    def test_05_table_values_in_range(self):
        """所有表值在 [0,1]"""
        for row in TABLE.values():
            for v in row.values():
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
