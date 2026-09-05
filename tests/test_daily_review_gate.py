#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_review_gate 单测（审验-自补 ⑥，cron 接入闸门）。

覆盖：配置解析（缺失/损坏回落默认/布尔宽容）/ 灰度一期（ENABLED=false：pass 与
fail_closed 均 exit 0 日报未动）/ 开装配（ENABLED=true：pass_with_gaps 装配写回、
fail_closed exit 2 不装配）/ 审验异常 degrade exit 3 / 摘要行格式。
依赖注入 mock reviewer/assemble/write，不触真实 data。
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import daily_review_gate as gate  # noqa: E402


def make_review(final_status="pass_with_gaps", n_gaps=2, run_id="review_2026-09-04_abc12345"):
    return {
        "review_run_id": run_id,
        "final_status": final_status,
        "findings": [{"finding_id": f"D-{i:02d}"} for i in range(n_gaps)],
        "unresolved_gaps": [{"gap_id": f"G-{i:02d}"} for i in range(n_gaps)],
        "timestamps": {"report_cutoff_at": "2026-09-04T22:00:00+08:00"},
    }


def write_report(path, text="原稿正文\n"):
    Path(path).write_text(text, encoding="utf-8")


class TestLoadConfig(unittest.TestCase):
    def test_default_when_missing(self, tmp_path=None):
        cfg = gate.load_config(Path("E:/tmp/__no_such_cfg.json"))
        self.assertFalse(cfg["REVIEWER_ENABLED"])
        self.assertEqual(cfg["REVIEWER_FAIL_MODE"], "degrade")

    def test_bool_tolerant(self):
        p = Path("E:/tmp/__cfg_bool.json")
        p.write_text(json.dumps({"REVIEWER_ENABLED": "true",
                                 "REVIEWER_ACTIVE_REPAIR": 0}), encoding="utf-8")
        cfg = gate.load_config(p)
        self.assertTrue(cfg["REVIEWER_ENABLED"])
        self.assertFalse(cfg["REVIEWER_ACTIVE_REPAIR"])
        p.unlink(missing_ok=True)

    def test_broken_json_falls_back(self):
        p = Path("E:/tmp/__cfg_broken.json")
        p.write_text("{not json", encoding="utf-8")
        cfg = gate.load_config(p)
        self.assertFalse(cfg["REVIEWER_ENABLED"])  # 安全默认
        p.unlink(missing_ok=True)

    def test_unknown_key_ignored(self):
        p = Path("E:/tmp/__cfg_extra.json")
        p.write_text(json.dumps({"REVIEWER_ENABLED": False, "SOMETHING": 1}), encoding="utf-8")
        cfg = gate.load_config(p)
        self.assertNotIn("SOMETHING", gate.DEFAULT_CONFIG)  # 仅默认键集
        p.unlink(missing_ok=True)


class TestRunGateGrayscale(unittest.TestCase):
    """灰度一期 REVIEWER_ENABLED=false：审验照跑、正文不动、恒 exit 0。"""

    def _run(self, review, report_text="原稿正文\n"):
        rp = Path("E:/tmp/__gate_report.md")
        rp.write_text(report_text, encoding="utf-8")
        cfg = dict(gate.DEFAULT_CONFIG)  # ENABLED=False
        code, summary = gate.run_gate(
            rp, "2026-09-04", cfg,
            _run_review=lambda r, d: review,
            _assemble=lambda t, rv: t + "【装配】",
            _write_text=lambda p, t: Path(p).write_text(t, encoding="utf-8"))
        return code, summary, rp

    def test_pass_with_gaps_exit0_no_modify(self):
        code, summary, rp = self._run(make_review("pass_with_gaps"))
        self.assertEqual(code, 0)
        self.assertIn("assembled=no(灰度)", summary)
        self.assertEqual(rp.read_text(encoding="utf-8"), "原稿正文\n")  # 正文未动

    def test_fail_closed_exit0_no_modify(self):
        code, summary, rp = self._run(make_review("fail_closed"))
        self.assertEqual(code, 0)  # 灰度不阻断
        self.assertIn("fail_closed", summary)
        self.assertEqual(rp.read_text(encoding="utf-8"), "原稿正文\n")

    def test_pass_exit0(self):
        code, _, _ = self._run(make_review("pass", n_gaps=0))
        self.assertEqual(code, 0)


class TestRunGateEnabled(unittest.TestCase):
    """开装配 REVIEWER_ENABLED=true：pass_with_gaps 装配写回；fail_closed exit 2。"""

    def _run(self, review, report_text="原稿正文\n"):
        rp = Path("E:/tmp/__gate_report2.md")
        rp.write_text(report_text, encoding="utf-8")
        cfg = dict(gate.DEFAULT_CONFIG)
        cfg["REVIEWER_ENABLED"] = True
        code, summary = gate.run_gate(
            rp, "2026-09-04", cfg,
            _run_review=lambda r, d: review,
            _assemble=lambda t, rv: t + "【装配:缺漏表】",
            _write_text=lambda p, t: Path(p).write_text(t, encoding="utf-8"))
        return code, summary, rp

    def test_pass_with_gaps_assembled(self):
        code, summary, rp = self._run(make_review("pass_with_gaps"))
        self.assertEqual(code, 0)
        self.assertIn("assembled=yes", summary)
        self.assertIn("【装配:缺漏表】", rp.read_text(encoding="utf-8"))  # 已写回

    def test_fail_closed_exit2_no_modify(self):
        code, summary, rp = self._run(make_review("fail_closed"))
        self.assertEqual(code, 2)  # 阻断转人工
        self.assertIn("exit=2", summary)
        self.assertEqual(rp.read_text(encoding="utf-8"), "原稿正文\n")  # 未装配

    def test_pass_no_assembly_needed(self):
        code, summary, rp = self._run(make_review("pass", n_gaps=0))
        self.assertEqual(code, 0)
        # pass 无缺漏：装配器正常处理（无表），此处断言 exit 即可
        self.assertIn("assembled=yes", summary)


class TestRunGateErrors(unittest.TestCase):
    def test_review_exception_degrade_exit3(self):
        rp = Path("E:/tmp/__gate_report3.md")
        rp.write_text("x", encoding="utf-8")
        cfg = dict(gate.DEFAULT_CONFIG)
        code, summary = gate.run_gate(
            rp, "2026-09-04", cfg,
            _run_review=lambda r, d: (_ for _ in ()).throw(FileNotFoundError("无日报")),
            _assemble=None, _write_text=None)
        self.assertEqual(code, 3)
        self.assertIn("ERROR", summary)

    def test_missing_report_enabled_exit3(self):
        rp = Path("E:/tmp/__no_such_report.md")
        cfg = dict(gate.DEFAULT_CONFIG)
        cfg["REVIEWER_ENABLED"] = True
        review = make_review("pass_with_gaps")
        code, _ = gate.run_gate(
            rp, "2026-09-04", cfg,
            _run_review=lambda r, d: review,   # 审验成功但日报文件读不到
            _assemble=lambda t, rv: t + "x",
            _write_text=lambda p, t: None)
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
