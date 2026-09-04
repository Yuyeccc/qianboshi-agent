#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_report_inputs 确定性注入检查 单测（审验-自补 第 0 步）。

覆盖：BOM 解码（带 BOM 文件 utf-8-sig 可读 → 不误报）/ holdings 空注入 /
portfolio 缺失 / decision_desk 空注入 / debate 断链 / 指数快照缺条目 /
标的池全空 / 报告日期不一致 / 禁用来源命中 / schema 缺失 / 退出码语义。
mock 外部依赖（decision_desk.build_decision_desk_context），不触真实 DB。
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_report_inputs as cri  # noqa: E402

BOM = b"\xef\xbb\xbf"
DDC_OK = {
    "user_decisions": [{"asset_id": "GOLD", "status": "reviewed"}],
    "debate_cards": [{"asset_id": "GOLD"}],
    "factor_states": [{"asset_id": "GOLD"}],
    "discipline": {"checked_at": "2026-09-04"},
}


def _mk_tree() -> Path:
    return Path(tempfile.mkdtemp())


class CheckInputsTest(unittest.TestCase):
    def setUp(self):
        self.tree = _mk_tree()
        # 默认三件套 + 真 schema 拷入
        self.pf = self.tree / "portfolio.json"
        self.mc = self.tree / "market_cache.json"
        self.tp = self.tree / "tracking_pool.json"
        self.schema = self.tree / "33_reviewer_v0.1.schema.json"
        self._write_portfolio()
        self._write_market_cache()
        self._write_tracking_pool()
        shutil.copy2(ROOT / "docs" / "33_reviewer_v0.1.schema.json", self.schema)

    def _write_portfolio(self, holdings=None, bom=False):
        data = {"holdings": holdings if holdings is not None
                else {"518880": {"shares": 100, "name": "华安黄金", "sector": "黄金"}}}
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.pf.write_bytes(BOM + raw if bom else raw)

    def _write_market_cache(self, keys=None):
        keys = keys if keys is not None else cri.CORE_INDEX_KEYS
        mc = {k: {"price": 3900.0, "change_pct": -0.3, "updated": "2026-09-04"} for k in keys}
        self.mc.write_bytes(json.dumps(mc).encode("utf-8"))

    def _write_tracking_pool(self, empty=False):
        tp = {"stocks": {} if empty else {"300308": {"name": "x"}},
              "etfs": {}, "us_stocks": {}}
        self.tp.write_bytes(json.dumps(tp, ensure_ascii=False).encode("utf-8"))

    def _rm(self, p: Path):
        p.unlink(missing_ok=True)

    def _run(self, report_date="2026-09-04", report_path=None, ddc=None):
        with patch.object(cri, "DATA_DIR", self.tree), \
             patch.object(cri, "SCHEMA_PATH", self.schema), \
             patch("decision_desk.build_decision_desk_context",
                   return_value=ddc if ddc is not None else DDC_OK):
            return cri.check_inputs(report_date, report_path)

    # ---------- 正常路径 ----------
    def test_all_ok_passes(self):
        errors, warns = self._run()
        self.assertEqual(errors, [])
        descs = " ".join(w["description"] for w in warns)
        for kw in ["holdings", "user_decisions", "核心指数", "标的池", "schema v0.1"]:
            self.assertIn(kw, descs, f"缺 INFO: {kw}")

    def test_report_missing_only_warns(self):
        """报告未生成（生成前时序）→ WARN 不 FAIL。"""
        errors, warns = self._run(report_date="2026-09-04")
        self.assertEqual(errors, [])
        self.assertTrue(any(w["severity"] == "medium" and "报告" in w["description"] for w in warns))

    # ---------- BOM ----------
    def test_bom_portfolio_reads_ok(self):
        """带 BOM 的 portfolio.json：utf-8-sig 读成功不误报（BOM bug 修复回归）。"""
        self._write_portfolio(bom=True)
        errors, warns = self._run()
        self.assertEqual(errors, [])
        ev = " ".join(w.get("evidence", "") for w in warns)
        self.assertIn("had_bom=True", ev)

    # ---------- portfolio ----------
    def test_holdings_empty_blocker(self):
        self._write_portfolio(holdings={})
        errors, _ = self._run()
        self.assertTrue(any(e["severity"] == "blocker" and "holdings 为空" in e["description"]
                            for e in errors))

    def test_portfolio_missing_blocker(self):
        self._rm(self.pf)
        errors, _ = self._run()
        self.assertTrue(any("portfolio.json 不存在" in e["description"] for e in errors))

    def test_portfolio_invalid_json_blocker(self):
        self.pf.write_bytes(b"{not json")
        errors, _ = self._run()
        self.assertTrue(any("解码失败" in e["description"] for e in errors))

    # ---------- decision_desk ----------
    def test_decision_desk_empty_decisions_blocker(self):
        ddc = {"user_decisions": [], "debate_cards": [], "factor_states": [], "discipline": {}}
        errors, _ = self._run(ddc=ddc)
        self.assertTrue(any("user_decisions 空" in e["description"] for e in errors))

    def test_debate_factor_break_when_decisions_exist(self):
        ddc = {"user_decisions": [{"asset_id": "GOLD"}], "debate_cards": [], "factor_states": [],
               "discipline": {}}
        errors, _ = self._run(ddc=ddc)
        self.assertTrue(any("debate_cards 为 0" in e["description"] for e in errors))
        self.assertTrue(any("factor_states 为 0" in e["description"] for e in errors))

    def test_ddc_error_dict_blocker(self):
        errors, _ = self._run(ddc={"error": "boom"})
        self.assertTrue(any("返回 error" in e["description"] for e in errors))

    # ---------- market cache / tracking pool ----------
    def test_market_cache_missing_core_index_high(self):
        self._write_market_cache(keys=["000001.SS"])
        errors, _ = self._run()
        self.assertTrue(any("核心指数缺条目" in e["description"] for e in errors))

    def test_market_cache_missing_file_blocker(self):
        self._rm(self.mc)
        errors, _ = self._run()
        self.assertTrue(any("market_cache.json 不存在" in e["description"] for e in errors))

    def test_tracking_pool_empty_blocker(self):
        self._write_tracking_pool(empty=True)
        errors, _ = self._run()
        self.assertTrue(any("全空" in e["description"] for e in errors))

    # ---------- 报告内容 ----------
    def test_report_date_mismatch_high(self):
        report = self.tree / "日报_2026-09-04.md"
        report.write_text("# 钱博士盘前简报｜2026-09-05\n\n正文", encoding="utf-8")
        errors, _ = self._run(report_path=str(report))
        self.assertTrue(any("报告头部未见日期" in e["description"] for e in errors))

    def test_report_date_consistent_ok(self):
        report = self.tree / "日报_2026-09-04.md"
        report.write_text("头部 2026-09-04 内容", encoding="utf-8")
        errors, _ = self._run(report_path=str(report))
        self.assertEqual(errors, [])

    def test_banned_source_high(self):
        report = self.tree / "日报_2026-09-04.md"
        report.write_text("钱博士：汤山老王是骗子\n正文 2026-09-04", encoding="utf-8")
        errors, _ = self._run(report_path=str(report))
        self.assertTrue(any("禁用来源" in e["description"] for e in errors))

    # ---------- schema ----------
    def test_schema_missing_high(self):
        self._rm(self.schema)
        errors, _ = self._run()
        self.assertTrue(any("33_reviewer schema 缺失" in e["description"] for e in errors))

    def test_schema_invalid_high(self):
        self.schema.write_text("{bad json", encoding="utf-8")
        errors, _ = self._run()
        self.assertTrue(any("schema 无效" in e["description"] for e in errors))

    # ---------- 退出码语义（main 分支） ----------
    def test_exit_code_semantics(self):
        self.assertEqual(cri._exit_code([], []), 0)                # 全过
        self.assertEqual(cri._exit_code([{"severity": "high"}], []), 1)      # 仅 high
        self.assertEqual(cri._exit_code([{"severity": "blocker"}], []), 2)   # blocker
        self.assertEqual(cri._exit_code([{"severity": "high"},
                                         {"severity": "blocker"}], []), 2)


if __name__ == "__main__":
    unittest.main()
