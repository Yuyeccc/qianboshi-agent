#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent 简报链路 output_gate 接入 单测（62 号方案 C 节）。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent import _gate_brief  # noqa: E402
from compliance_gate import NEUTRAL_RESPONSE  # noqa: E402

CLEAN_BRIEF = (
    "## 1. 大势判断\n大盘今日震荡，北向资金流入。\n"
    "## 8. 风险提醒\n纪律检查：主题超限 100%，需人工确认。\n"
    "> 以上为分析师观点与数据整理，不构成投资建议。\n"
)


class BriefGateTests(unittest.TestCase):
    def test_01_clean_passthrough(self):
        """干净简报（无动作词）→ clean 原文直通"""
        out = _gate_brief(CLEAN_BRIEF, tool="test")
        self.assertEqual(out, CLEAN_BRIEF)

    def test_02_discipline_action_blocked(self):
        """纪律上下文+动作词 → block（中性文本替换，不发布违规简报）"""
        bad = "纪律检查：主题超限 100%，建议减仓\n" + CLEAN_BRIEF
        out = _gate_brief(bad, tool="test")
        self.assertIn("无法提供", out)
        self.assertNotIn("建议减仓", out)
        self.assertNotEqual(out, bad)

    def test_03_plain_action_annotated(self):
        """普通建议动作（非纪律上下文）→ annotate 横幅；已含则防重复"""
        brief = "黄金资产卡：买点 3900，建议加仓。\n数据整理。"
        out = _gate_brief(brief, tool="test")
        self.assertIn("不构成投资建议", out)  # 横幅
        # 防重复：文本已含横幅时不追加第二个
        already = "黄金资产卡：买点 3900，建议加仓。\n> 不构成投资建议\n"
        out2 = _gate_brief(already, tool="test")
        self.assertEqual(out2.count("不构成投资建议"), 1)

    def test_04_quote_exempt(self):
        """引用语境豁免：钱博士说建议减仓 → clean"""
        brief = "钱博士直播说半导体超限，建议减仓，但认为风险可控。\n数据整理。"
        out = _gate_brief(brief, tool="test")
        self.assertEqual(out, brief)  # clean 直通（含原句）

    def test_05_fail_closed(self):
        """异常 → 返回原文 + stderr WARN（安全侧不崩溃丢简报）"""
        with patch("compliance_gate.output_gate", side_effect=RuntimeError("boom")):
            out = _gate_brief(CLEAN_BRIEF, tool="test")
        self.assertEqual(out, CLEAN_BRIEF)


if __name__ == "__main__":
    unittest.main(verbosity=2)
