#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reviewer_agent 确定性审验 单测（审验-自补 ④，dry-run 只读）。

覆盖：章节覆盖 / 证据链存在性（幻觉 view_id 抓出）/ 禁用来源 / 时间窗 /
N/A 硬故障-软缺失分级（BOM 声明 high vs 创业板单点 N/A medium）/ 聚合防刷屏 /
schema 校验通过 / 回放可复现（同输入两次产物 final_status 一致）。
mock check_report_inputs（不触真实 data），仅纯函数测试。
"""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reviewer_agent as rv  # noqa: E402

SAMPLE = """# 钱博士盘前简报｜2026-09-04

## 1. 大势判断

- A股指数偏弱，上证 3930.12，-0.30%；深证 13516.97，-0.79%。
- 钱博士认为接近牛市回调而非熊市，9月7日前后是变盘观察窗口。
- 创业板指涨跌幅 N/A，数据缺失。
- 中期仍偏多但提示行情趋弱，预计今年约4300点属个人判断。

## 2. 持仓诊断

- 持仓明细工具返回 UTF-8 BOM 解码错误，均为 N/A。

## 3. 决策台跟踪

- 当前未注入 open_user_decisions。

## 4. 标的池异动

- 扫描正常。

## 5. 多空对照

- view_id `88ac447e52ed42be` 偏多。

## 6. 资产卡速览

- 资产卡正常。

## 7. 今日关注

- 观察项数据 N/A。

## 8. 风险提示

- 正常。
"""


class SectionChecksTest(unittest.TestCase):
    def test_all_sections_present_ok(self):
        self.assertEqual(rv.check_sections(SAMPLE), [])

    def test_missing_section_high(self):
        text = SAMPLE.replace("## 6. 资产卡速览\n", "")
        fs = rv.check_sections(text)
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["severity"], "high")
        self.assertIn("6", fs[0]["description"])

    def test_hard_fail_marker_high(self):
        """BOM/未注入声明 → high（9-04 真事故分级）。"""
        fs = rv.check_missing_markers(SAMPLE)
        hard = [f for f in fs if f["severity"] == "high"]
        self.assertTrue(any("章节 2" in f["description"] for f in hard))
        self.assertTrue(any("章节 3" in f["description"] for f in hard))

    def test_single_na_medium(self):
        """创业板单点 N/A → medium（常态口径不误报 high）。"""
        fs = rv.check_missing_markers(SAMPLE)
        s1 = [f for f in fs if "章节 1" in f["description"]]
        self.assertEqual(len(s1), 1)
        self.assertEqual(s1[0]["severity"], "medium")

    def test_aggregation_no_per_line_spam(self):
        """按章节聚合：多行 N/A 只出 1 条，不逐行刷屏。"""
        text = SAMPLE.replace("## 4. 标的池异动\n\n- 扫描正常。\n\n",
                              "## 4. 标的池异动\n\n- 标的 A N/A。\n- 标的 B N/A。\n- 标的 C N/A。\n- 标的 D N/A。\n\n")
        fs = rv.check_missing_markers(text)
        s4 = [f for f in fs if "章节 4" in f["description"]]
        self.assertEqual(len(s4), 1)
        self.assertEqual(s4[0]["severity"], "high")  # ≥3 处 → high
        self.assertIn("4 处", s4[0]["description"])

    def test_table_rows_not_counted(self):
        """表格行不参与缺失计数（避免把 N/A 表格刷成整节缺失）。"""
        text = SAMPLE.replace("## 4. 标的池异动\n\n- 扫描正常。\n\n",
                              "## 4. 标的池异动\n\n| a | b |\n|---|---|\n| N/A | N/A |\n\n")
        fs = rv.check_missing_markers(text)
        s4 = [f for f in fs if "章节 4" in f["description"]]
        self.assertEqual(s4, [])


class EvidenceChainTest(unittest.TestCase):
    def test_existing_view_id_ok(self):
        ids = {"88ac447e52ed42be", "abc1234567890def"}
        fs = rv.check_evidence_chain(SAMPLE, ids)
        self.assertEqual(fs, [])

    def test_phantom_view_id_high(self):
        fs = rv.check_evidence_chain(SAMPLE, {"other1234567890"})
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["severity"], "high")
        self.assertIn("88ac447e52ed42be", fs[0]["description"])
        self.assertEqual(fs[0]["evidence_refs"], ["88ac447e52ed42be"])

    def test_duplicate_view_id_single_finding(self):
        text = SAMPLE + "再次引用 `88ac447e52ed42be`\n"
        fs = rv.check_evidence_chain(text, set())
        self.assertEqual(len(fs), 1)  # 同 id 去重

    def test_load_view_ids_from_jsonl(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "structured_views.jsonl"
            p.write_text('{"view_id": "aaa1111111111111", "claim": "x"}\n'
                         '{"view_id": "bbb2222222222222", "claim": "y"}\n'
                         'not json\n', encoding="utf-8")
            with patch.object(rv, "VIEWS_FILE", p):
                ids = rv.load_view_ids()
        self.assertEqual(ids, {"aaa1111111111111", "bbb2222222222222"})


class MiscChecksTest(unittest.TestCase):
    def test_banned_source_blocker(self):
        text = "钱博士观点：汤山老王看好\n" + SAMPLE
        fs = rv.check_banned_sources(text)
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["severity"], "blocker")

    def test_time_window_ok_and_mismatch(self):
        self.assertEqual(rv.check_time_window(SAMPLE, "2026-09-04"), [])
        fs = rv.check_time_window(SAMPLE, "2026-09-05")
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["severity"], "high")

    def test_section_regex_matches_numbers(self):
        self.assertEqual(rv._sections(SAMPLE), ["1", "2", "3", "4", "5", "6", "7", "8"])


class BuildReviewTest(unittest.TestCase):
    def test_final_status_mapping(self):
        def build(findings):
            return rv.build_review("x.md", "2026-09-04", SAMPLE, "sha", findings, [], use_llm=False)

        self.assertEqual(build([])["final_status"], "pass")
        self.assertEqual(build([{"severity": "medium", "description": "a"}])["final_status"],
                         "pass_with_gaps")
        self.assertEqual(build([{"severity": "blocker", "description": "a"}])["final_status"],
                         "fail_closed")

    def _tmp_report(self) -> Path:
        import tempfile
        td = Path(tempfile.mkdtemp())
        p = td / "日报_2026-09-04.md"
        p.write_text(SAMPLE, encoding="utf-8")
        return p

    def test_schema_valid_full_pipeline(self):
        """全链 dry-run 产物过 33_reviewer schema（mock check_report_inputs 返回空）。"""
        report = self._tmp_report()
        with patch("check_report_inputs.check_inputs", return_value=([], [])):
            rep = rv.run_review(str(report), "2026-09-04", save=False)
        ok, errs = rv.validate_report(rep)
        self.assertTrue(ok, f"schema 失败: {errs}")
        self.assertIn("schema_version", rep["_meta"])
        self.assertEqual(rep["report_date"], "2026-09-04")
        self.assertTrue(rep["review_run_id"].startswith("review_2026-09-04_"))

    def test_reproducible_final_status(self):
        """回放可复现：同输入两次 → 同 final_status + 同 findings 数（确定性）。"""
        report = self._tmp_report()
        with patch("check_report_inputs.check_inputs", return_value=([], [])):
            r1 = rv.run_review(str(report), "2026-09-04", save=False)
            r2 = rv.run_review(str(report), "2026-09-04", save=False)
        self.assertEqual(r1["final_status"], r2["final_status"])
        self.assertEqual(len(r1["findings"]), len(r2["findings"]))
        # findings 内容一致（除 finding_id 依赖序号，比较 description 集合）
        d1 = sorted(f["description"] for f in r1["findings"])
        d2 = sorted(f["description"] for f in r2["findings"])
        self.assertEqual(d1, d2)

    def test_llm_mode_rejected(self):
        with self.assertRaises(NotImplementedError):
            rv.run_review("x.md", "2026-09-04", use_llm=True)


if __name__ == "__main__":
    unittest.main()
