#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#11v2 输出侧合规门 单测"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from compliance_gate import output_gate, COMPLIANCE_BANNER  # noqa: E402


class OutputGateTests(unittest.TestCase):
    def test_annotate_action_words(self):
        r = output_gate("黄金资产卡：买点 3900，建议加仓，目标价 4200", tool="test")
        self.assertEqual(r["mode"], "annotate")
        self.assertIn("不构成投资建议", r["output"])
        self.assertGreaterEqual(len(r["issues"]), 1)

    def test_quote_context_exempt(self):
        r = output_gate("钱博士直播说半导体有买点，但认为风险可控", tool="test")
        self.assertEqual(r["mode"], "clean")  # 观点引用豁免
        self.assertNotIn("不构成投资建议", r["output"])

    def test_negation_exempt(self):
        r = output_gate("不要买！这里只是风险提示", tool="test")
        self.assertEqual(r["mode"], "clean")  # 否定豁免

    def test_block_system_directive(self):
        r = output_gate("建议你现在清仓所有仓位", tool="test")
        self.assertEqual(r["mode"], "block")
        self.assertIn("无法提供", r["output"])  # 中性替换

    def test_block_return_promise(self):
        r = output_gate("该基金稳赚不赔，无风险", tool="test")
        self.assertEqual(r["mode"], "block")

    def test_historical_review_exempt(self):
        r = output_gate("历史复盘：当时判断买点 2900 正确", tool="test")
        self.assertEqual(r["mode"], "clean")  # 历史复盘豁免

    def test_no_double_banner(self):
        r = output_gate("买点 3900。\n---\n> ⚠️ 合规提示：以上为分析师观点与数据整理，不构成投资建议", tool="test")
        self.assertEqual(r["mode"], "annotate")
        self.assertEqual(r["output"].count("不构成投资建议"), 1)  # 防重复横幅

    def test_banner_content(self):
        self.assertIn("不构成投资建议", COMPLIANCE_BANNER)
        self.assertIn("投资有风险", COMPLIANCE_BANNER)

    def test_cross_sentence_quote_exempt(self):
        # gpt 复审：跨句转述豁免（前一句有引用词）
        r = output_gate("钱博士直播表示看好黄金。\n他提到买点 3900 附近值得关注。", tool="test")
        self.assertEqual(r["mode"], "clean")

    def test_quote_mark_exempt(self):
        # 引号内豁免
        r = output_gate("主播原话：“买点 3900”。", tool="test")
        self.assertEqual(r["mode"], "clean")

    def test_mcp_error_string_gated(self):
        # 异常返回也过 gate（无建议词 → clean 直通，不崩）
        from qianboshi_mcp import _gated
        out = _gated("获取资产分析卡失败: no such asset", tool="get_asset_analysis_card")
        self.assertEqual(out, "获取资产分析卡失败: no such asset")


if __name__ == "__main__":
    unittest.main()
