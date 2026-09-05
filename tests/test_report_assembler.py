#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_assembler 单测（审验-自补 ⑤，缺漏透明交付装配器）。

覆盖：头部三行插入 / 缺漏表行（gap join finding 补类别与章节）/ 章节号→真实标题反查 /
幂等（对已装配文本再装配结果不变）/ pass 无表 / repaired 不进表不进旁标 /
高危(blocker/high)章节旁标落位 / header 章节显示 / fail_closed 不装配退出 2 /
日期格式化。纯函数测试，不触真实 data。
"""
import json
import sys
import unittest
import unittest.mock  # noqa: F401  (显式 import，Windows py3.14 下 unittest.mock 非自动属性)
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import report_assembler as ra  # noqa: E402

SAMPLE = """# 钱博士盘前简报｜2026-09-04

**主线**：A股等待变盘

## 1. 大势判断

- A股指数偏弱，创业板指涨跌幅为 N/A。

## 2. 持仓诊断

- 持仓明细工具返回 UTF-8 BOM 解码错误，均为 N/A。

## 3. 决策台跟踪

- 正常。

## 4. 标的池异动

- 正常。

## 5. 多空对照

- 正常。

## 6. 资产卡速览

- 正常。

## 7. 今日关注

- 观察项数据 N/A。

## 8. 风险提醒

- 正常。
"""


def make_review(final_status="pass_with_gaps", findings=None, gaps=None, repairs=None):
    findings = findings if findings is not None else [
        {"finding_id": "DATA-01", "category": "数据缺失", "severity": "high",
         "status": "open", "detector": "deterministic",
         "description": "章节 2 注入失败声明 1 处: BOM 解码错误",
         "section": "## 2"},
    ]
    gaps = gaps if gaps is not None else [
        {"gap_id": "DATA-01", "description": "章节 2 注入失败声明 1 处: BOM 解码错误",
         "severity": "high", "delivery": "transparent"},
    ]
    return {
        "review_run_id": "review_2026-09-04_abc12345",
        "report_id": "daily-2026-09-04",
        "job_id": "",
        "report_date": "2026-09-04",
        "generator_model": "agent.py-brief",
        "reviewer_model": "deterministic-dryrun",
        "input_snapshot_ids": ["portfolio.json"],
        "tool_calls": [],
        "claim_extracts": [],
        "findings": findings,
        "repairs": repairs or [],
        "unresolved_gaps": gaps,
        "final_status": final_status,
        "timestamps": {"started_at": "2026-09-04T22:01:00Z",
                       "finished_at": "2026-09-04T22:01:05Z",
                       "report_cutoff_at": "2026-09-04T22:00:00+08:00"},
        "_meta": {"schema_version": "33_reviewer_v0.1", "schema_valid": True},
    }


class TestMetaBlock(unittest.TestCase):
    def test_meta_block_three_lines(self):
        out = ra._meta_block(make_review(), n_gaps=1)
        self.assertIn("> **审验状态**：通过（含 1 项非阻断缺漏）", out)
        self.assertIn("> **数据截止**：2026-09-04 22:00 Asia/Shanghai", out)
        self.assertIn("> **审验批次**：review_2026-09-04_abc12345", out)
        self.assertTrue(out.startswith(ra.META_START) and out.endswith(ra.META_END))

    def test_meta_pass_no_gap_word(self):
        out = ra._meta_block(make_review(final_status="pass"), n_gaps=0)
        self.assertIn("> **审验状态**：通过", out)
        self.assertNotIn("含 0 项", out)


class TestGapRows(unittest.TestCase):
    def test_row_joins_finding_category_section(self):
        titles = ra._section_titles(SAMPLE)
        rows = ra.build_gap_rows(make_review(), titles)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["gap_id"], "DATA-01")
        self.assertEqual(r["category"], "数据缺失")
        self.assertEqual(r["section"], "§2 持仓诊断")
        self.assertEqual(r["severity"], "高")
        self.assertEqual(r["delivery"], "透明交付（已在正文披露）")
        self.assertEqual(r["actions"], "—")

    def test_repaired_finding_excluded(self):
        rev = make_review(findings=[
            {"finding_id": "DATA-01", "category": "数据缺失", "severity": "high",
             "status": "repaired", "description": "已修复", "section": "## 2"},
        ])
        rows = ra.build_gap_rows(rev, ra._section_titles(SAMPLE))
        self.assertEqual(rows, [])

    def test_actions_joined_from_repairs(self):
        rev = make_review(repairs=[
            {"repair_id": "R1", "finding_id": "DATA-01", "action": "重读持仓", "status": "applied"},
        ])
        rows = ra.build_gap_rows(rev, ra._section_titles(SAMPLE))
        self.assertEqual(rows[0]["actions"], "重读持仓")

    def test_header_section_display(self):
        rev = make_review(findings=[
            {"finding_id": "TS-01", "category": "时间窗不一致", "severity": "high",
             "status": "open", "description": "头部日期不一致", "section": "header"},
        ], gaps=[
            {"gap_id": "TS-01", "description": "头部日期不一致",
             "severity": "high", "delivery": "transparent"},
        ])
        rows = ra.build_gap_rows(rev, ra._section_titles(SAMPLE))
        self.assertEqual(rows[0]["section"], "报告头部")

    def test_cell_clean_escapes_pipe(self):
        self.assertEqual(ra._clean_cell("a|b"), "a\\|b")
        self.assertLessEqual(len(ra._clean_cell("x" * 500)), 151)


class TestAnnot(unittest.TestCase):
    def test_high_annot_added(self):
        lines = ra._annot_lines(make_review(), ra._section_titles(SAMPLE))
        self.assertEqual([(2, "> ⚠ 本章存在审验缺漏 [DATA-01]（详见文末「审验与数据缺漏」表）")], lines)

    def test_medium_no_annot(self):
        rev = make_review(findings=[
            {"finding_id": "DATA-09", "category": "数据缺失", "severity": "medium",
             "status": "open", "description": "单点 N/A", "section": "## 4"},
        ])
        self.assertEqual(ra._annot_lines(rev, ra._section_titles(SAMPLE)), [])

    def test_repaired_no_annot(self):
        rev = make_review(findings=[
            {"finding_id": "DATA-01", "category": "数据缺失", "severity": "high",
             "status": "repaired", "description": "已修复", "section": "## 2"},
        ])
        self.assertEqual(ra._annot_lines(rev, ra._section_titles(SAMPLE)), [])

    def test_multi_id_merged_per_section(self):
        rev = make_review(findings=[
            {"finding_id": "DATA-01", "category": "数据缺失", "severity": "high",
             "status": "open", "description": "a", "section": "## 2"},
            {"finding_id": "EVID-01", "category": "证据链断裂", "severity": "high",
             "status": "open", "description": "b", "section": "## 2"},
        ])
        lines = ra._annot_lines(rev, ra._section_titles(SAMPLE))
        self.assertEqual(len(lines), 1)
        self.assertIn("[DATA-01, EVID-01]", lines[0][1])


class TestAssemble(unittest.TestCase):
    def test_assembled_has_all_three_parts(self):
        out = ra.assemble(SAMPLE, make_review())
        # 头部
        self.assertIn("> **审验状态**：通过（含 1 项非阻断缺漏）", out)
        self.assertIn("> **数据截止**：2026-09-04 22:00 Asia/Shanghai", out)
        # 旁标（§2 标题后）
        i2 = out.index("## 2. 持仓诊断")
        self.assertIn("> ⚠ 本章存在审验缺漏 [DATA-01]", out[i2: i2 + 200])
        # 文末缺漏表
        self.assertIn("## 审验与数据缺漏", out)
        self.assertIn("| DATA-01 | 数据缺失 | §2 持仓诊断 |", out)
        # 原 8 章完整保留
        for n in range(1, 9):
            self.assertIn(f"## {n}.", out)

    def test_idempotent(self):
        once = ra.assemble(SAMPLE, make_review())
        twice = ra.assemble(once, make_review())
        self.assertEqual(once, twice)
        # 锚块不重复
        self.assertEqual(once.count(ra.META_START), 1)
        self.assertEqual(once.count("## 审验与数据缺漏"), 1)
        self.assertEqual(once.count("> ⚠"), 1)

    def test_pass_no_gaps_table(self):
        out = ra.assemble(SAMPLE, make_review(final_status="pass",
                                              findings=[], gaps=[]))
        self.assertIn("> **审验状态**：通过", out)
        self.assertNotIn("## 审验与数据缺漏", out)
        self.assertNotIn("> ⚠", out)

    def test_strip_old_removes_annot(self):
        # 已装配文本二次跑不同 review → 旧旁标被清，不残留
        rev_a = make_review()
        rev_b = make_review(
            findings=[{"finding_id": "DATA-02", "category": "数据缺失", "severity": "high",
                       "status": "open", "description": "决策台 N/A", "section": "## 3"}],
            gaps=[{"gap_id": "DATA-02", "description": "决策台 N/A", "severity": "high",
                   "delivery": "transparent"}],
        )
        out_b = ra.assemble(ra.assemble(SAMPLE, rev_a), rev_b)
        self.assertEqual(out_b.count("> ⚠"), 1)
        self.assertIn("[DATA-02]", out_b)
        self.assertNotIn("[DATA-01]", out_b)


class TestCutoff(unittest.TestCase):
    def test_format(self):
        self.assertEqual(ra._fmt_cutoff("2026-09-04T22:00:00+08:00"),
                         "2026-09-04 22:00 Asia/Shanghai")

    def test_none(self):
        self.assertEqual(ra._fmt_cutoff(None), "—")


class TestCLI(unittest.TestCase):
    def test_fail_closed_refuses_exit2(self):
        rev = make_review(final_status="fail_closed", findings=[
            {"finding_id": "SRC-01", "category": "来源禁用", "severity": "blocker",
             "status": "open", "description": "引用禁用来源", "section": None},
        ], gaps=[
            {"gap_id": "SRC-01", "description": "引用禁用来源",
             "severity": "blocker", "delivery": "blocked"},
        ])
        with unittest.mock.patch("sys.argv", ["report_assembler.py",
                                              "--report", "E:/tmp/x.md",
                                              "--review", "E:/tmp/y.json"]):
            self.assertEqual(ra.main(), 2)

    def test_missing_files_exit2(self):
        with unittest.mock.patch("sys.argv", ["report_assembler.py",
                                              "--report", "E:/tmp/no_such.md",
                                              "--review", "E:/tmp/no_such.json"]):
            self.assertEqual(ra.main(), 2)


if __name__ == "__main__":
    unittest.main()
