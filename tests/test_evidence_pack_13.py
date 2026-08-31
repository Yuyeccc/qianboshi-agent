#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#13 可验证性证据包：原文指针/冲突徽标/无来源数字门禁 单测（确定性）"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from claim_dimensions import (  # noqa: E402
    attach_dimensions,
    evidence_badge,
    evidence_detail,
    conflict_badge,
    source_evidence_badge,
    reload,
)


def view(**kw):
    base = {
        "view_id": "a" * 16,
        "analyst": "钱博士直播",
        "date": "2026-07-20",
        "source_file": "钱博士直播 2026.07.20 BVxxx.md",
        "section": "",
        "entities": {},
        "stance": "bullish",
        "horizon": "short",
        "view_type": "general",
        "claim": "半导体景气度向上",
        "evidence": "legacy-string",  # 旧视图 JSONL 遗留字符串
    }
    base.update(kw)
    return base


class EvidenceBadgeTests(unittest.TestCase):
    def setUp(self):
        reload()  # 每次强制重载真实导出文件

    def test_evidence_badge_ok(self):
        v = attach_dimensions(view())
        # 真实维度导出：该 view_id 无对应维度 → unknown/缺失；这里直接调函数验证挂载后 dict
        mounted = dict(view(), claim_level="fact", source_layer="primary",
                       verification_status="verified", confidence={"band": "high"},
                       uncertainty_tags=[], materiality="high",
                       evidence={"extraction_status": "ok", "ts_display": "00:03:03-00:03:15",
                                 "bv_id": "BV1rwjGztEWt", "anchor_start_ms": 183080},
                       conflict_groups=[])
        self.assertEqual(evidence_badge(mounted), "🔍原文 00:03:03-00:03:15")
        det = evidence_detail(mounted)
        self.assertIn("https://www.bilibili.com/video/BV1rwjGztEWt?t=183s", det["url"])

    def test_evidence_badge_missing_no_guess(self):
        # 旧字符串 evidence / 无 evidence → 原文缺失，不猜
        self.assertEqual(evidence_badge(view()), "❔原文缺失")
        mounted = dict(view(), evidence=None)
        self.assertEqual(evidence_badge(mounted), "❔原文缺失")
        mounted_missing = dict(view(), evidence={"extraction_status": "segment_missing"})
        self.assertEqual(evidence_badge(mounted_missing), "❔原文缺失")
        self.assertIsNone(evidence_detail(mounted_missing))

    def test_evidence_badge_hash_mismatch(self):
        mounted = dict(view(), evidence={"extraction_status": "hash_mismatch"})
        self.assertEqual(evidence_badge(mounted), "⚠️原文存疑")

    def test_source_evidence_badge_kept(self):
        mounted = dict(view(), source_layer="primary", verification_status="verified")
        self.assertEqual(source_evidence_badge(mounted), "🅰 一手·✅核验")

    def test_conflict_badge_capped_at_2(self):
        groups = [
            {"group_id": "g1", "topic": "半导体", "entity": "半导体", "level": "primary",
             "n_bull": 5, "n_bear": 3},
            {"group_id": "g2", "topic": "半导体", "entity": "光模块", "level": "primary",
             "n_bull": 2, "n_bear": 4},
            {"group_id": "g3", "topic": "半导体", "entity": "存储", "level": "background",
             "n_bull": 1, "n_bear": 1},
        ]
        mounted = dict(view(), conflict_groups=groups)
        badge = conflict_badge(mounted)
        self.assertIn("+1", badge)  # 只取前2，第3个折叠为 +1
        self.assertNotIn("存储", badge)


class EvidenceGateTests(unittest.TestCase):
    def test_gate_blocks_unsourced_numbers(self):
        from evidence_gate import extract_number_lines, has_source
        md = """# 标题

## 1. 大势
A股明天将上涨 3.5%，目标点位 4200 点。

## 2. 有来源
看多（证据链：view_id=001d13e95128ab72；钱博士 2026-08-28）

## 3. 行情
上证昨收 3952.18，涨跌幅 0.06%。
"""
        hits = extract_number_lines(md)
        unsourced = []
        for lineno, s, nums in hits:
            ok, kind = has_source(s, "", "")
            if not ok:
                unsourced.append((lineno, nums))
        self.assertEqual(unsourced, [(4, ["3.5%"])])
        # 有证据链行 + 行情行不算无来源
        lines = md.splitlines()
        l4 = lines[3]  # A股明天...（无来源）
        l7 = lines[6]  # 看多（证据链...
        l10 = lines[9]  # 上证昨收...
        self.assertTrue(has_source(l7, "", "")[0])
        self.assertTrue(has_source(l10, "", "")[0])
        self.assertFalse(has_source(l4, "", "")[0])

    def test_gate_ignores_dates_and_codes(self):
        from evidence_gate import extract_number_lines
        md = "日期 2026-08-28 时间 22:35 view 001d13e95128ab72 BV1rwjGztEWt 基金 027695\n" \
             "## 3. 标题序号\n" \
             "观点说 5.5% 提升。\n"
        hits = extract_number_lines(md)
        self.assertEqual(len(hits), 1)  # 只有 5.5% 那行
        self.assertEqual(hits[0][2], ["5.5%"])

    def test_gate_cn_numbers_and_negative(self):
        # gpt 复审补漏：中文数字/约数/负数也能被识别为观点数字
        from evidence_gate import extract_number_lines
        md = "公司利润增长近两成，投资规模达数十亿。\n" \
             "昨日回调 -3.2%，属于正常波动。\n" \
             "注：成本约五六百万元。\n"
        hits = extract_number_lines(md)
        self.assertEqual(len(hits), 3)
        all_nums = [n for _, _, nums in hits for n in nums]
        self.assertTrue(any("两成" in n for n in all_nums))
        self.assertTrue(any("数十亿" in n for n in all_nums))
        self.assertTrue(any(n.startswith("-3.2") for n in all_nums))

    def test_gate_dubious_flagged_not_blocked(self):
        # hash_mismatch：显式标"原文存疑" → dubious 不阻断
        import subprocess
        fake = Path(__file__).parent / "_gate_dubious_test.md"
        fake.write_text("> ⚠️原文存疑：某观点含数字 3.5% 但转写不一致\n", encoding="utf-8")
        try:
            r = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "evidence_gate.py"), str(fake)],
                capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(r.returncode, 0)
            self.assertIn("原文存疑=1", r.stdout)
        finally:
            fake.unlink(missing_ok=True)


class ReasoningChainTests(unittest.TestCase):
    """#6: 论证链渲染（reasoning_chain）"""

    def test_chain_full(self):
        from claim_dimensions import reasoning_chain
        v = {"reasoning": {
            "premise": "海外资金回流", "mechanism": "流动性改善推升估值",
            "conclusion": "港股中期看多", "trigger_condition": "南向资金持续流入",
            "invalid_condition": "美联储加息", "tuple_status": "ok",
        }}
        chain = reasoning_chain(v)
        self.assertIn("前提：海外资金回流", chain)
        self.assertIn("机制：流动性改善推升估值", chain)
        self.assertIn("结论：港股中期看多", chain)
        self.assertIn("触发：南向资金持续流入", chain)
        self.assertIn("失效：美联储加息", chain)
        self.assertNotIn("→", reasoning_chain({}))

    def test_chain_template_only_empty(self):
        from claim_dimensions import reasoning_chain
        v = {"reasoning": {"tuple_status": "template_only", "conclusion": "中长线：看多"}}
        self.assertEqual(reasoning_chain(v), "")  # 模板句无论证链

    def test_chain_partial_null_ok(self):
        from claim_dimensions import reasoning_chain
        v = {"reasoning": {"tuple_status": "ok", "conclusion": "结论", "premise": None}}
        chain = reasoning_chain(v)
        self.assertIn("结论：结论", chain)
        self.assertNotIn("前提", chain)


if __name__ == "__main__":
    unittest.main()
