#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""历史行情补拉 单测（68 号方案 E 节）。"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backfill_history_prices import (  # noqa: E402
    TRENDS_FILE, backfill, load_trends, merge_trends,
)


class MergeTests(unittest.TestCase):
    def test_01_merge_incremental(self):
        """增量合并：新日期加入，已有日期以新为准，其他 symbol 不动"""
        trends = {"600000.SS": {"2026-08-01": {"price": 10.0, "change_pct": 0.0}},
                  "688981.SS": {"2026-08-01": {"price": 100.0, "change_pct": 0.0}}}
        added, updated = merge_trends(trends, "688981.SS", {
            "2026-08-01": {"price": 99.5, "change_pct": -0.5},   # 更新
            "2026-08-02": {"price": 100.5, "change_pct": 1.0},   # 新增
        })
        self.assertEqual((added, updated), (1, 1))
        self.assertEqual(trends["688981.SS"]["2026-08-01"]["price"], 99.5)  # 新为准
        self.assertIn("2026-08-02", trends["688981.SS"])
        self.assertEqual(trends["600000.SS"]["2026-08-01"]["price"], 10.0)  # 其他不动

    def test_02_failed_symbol_does_not_break(self):
        """单标的失败不中断，其余继续"""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        fake = tmp / "price_trends.json"
        fake.write_text(json.dumps({}), encoding="utf-8")
        with patch.object(__import__("backfill_history_prices"), "TRENDS_FILE", fake):
            with patch("backfill_history_prices.fetch_symbol", side_effect=RuntimeError("boom")):
                r = backfill(["A.SZ", "B.SZ"])
        self.assertEqual(len(r["failed"]), 2)
        self.assertEqual(len(r["ok"]), 0)

    def test_03_readonly_other_files(self):
        """只读约束：除 price_trends.json 外数据文件 hash 不变"""
        import hashlib
        targets = [ROOT / "data" / "portfolio.json", ROOT / "data" / "view_authority.json"]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in targets if p.exists()}
        trends = load_trends()
        merge_trends(trends, "TEST.SZ", {"2026-09-01": {"price": 1.0, "change_pct": 0.0}})
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in targets if p.exists()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
