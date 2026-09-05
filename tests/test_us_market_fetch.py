#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""us_market_fetch 单测（审验-自补 ⑦，美股夜盘采集器）。纯函数 + mock 不触网。

覆盖：sina_code 映射（^HSI→None）/ parse 三行真实样本固化（gb_ 昨收=串末字段，
防 [28] 硬编码回退）/ 降级链三态（live/stale/missing）与旧值保留 /
us_eastern_session DST 边界（2026-09-07 夏令时盘中边界 13:30 UTC、冬令时 2026-01-15、
周末）/ 原子写盘无 .tmp 残留 / run_fetch 网络失败整体降级不崩、mock 写盘主路径。

样本锚点（2026-09-05 新浪实测定稿，见施工蓝图「样本字段锁定」）：
  int_/znb_：名称,现价,涨跌额,涨跌幅%      gb_：名称,现价,涨跌幅%,报价时间,涨跌额,...,昨收(串末)
"""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock  # noqa: F401  (显式 import，Windows py3.14 下 unittest.mock 非自动属性)
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import requests
import us_market_fetch as umf  # noqa: E402

# ── 2026-09-05 实测定稿样本（gb_ 测试串 8 字段：保「昨收=串末」语义，防 [28] 硬编码回退）──
LINE_INT_DJI = 'var hq_str_int_dji="道琼斯,46247.29,299.97,0.65";'
LINE_VIX = 'var hq_str_znb_VIX="VIX恐慌指数,14.5200,0.21,1.47,,,2026-09-05,04:15:01";'
LINE_GB_NVDA = ('var hq_str_gb_nvda="英伟达,230.3600,0.84,2026-09-05 09:46:13,'
                '1.9100,0,0,228.4500";')  # 末字段=昨收（真实串 [28] 位置，AMD 456.16 等五样本验证）

NOW_UTC = datetime(2026, 9, 7, 13, 30, tzinfo=timezone.utc)  # 周一夏令时 09:30 ET 盘中


def make_parsed(name="英伟达", price=230.36, change_pct=0.84, quote_time="2026-09-05 09:46:13",
                prev_close=228.45):
    return {"name": name, "price": price, "change_pct": change_pct,
            "quote_time": quote_time, "prev_close": prev_close}


class TestSinaCode(unittest.TestCase):
    def test_index_map(self):
        for sym, expect in [("^DJI", "int_dji"), ("^IXIC", "int_nasdaq"),
                            ("^GSPC", "int_sp500"), ("^VIX", "znb_VIX")]:
            self.assertEqual(umf.sina_code(sym), expect, sym)

    def test_unknown_caret_none(self):
        self.assertIsNone(umf.sina_code("^HSI"))  # 非美股指数 → None（蓝图 L48 明确）

    def test_stock_gb_lower(self):
        self.assertEqual(umf.sina_code("NVDA"), "gb_nvda")
        self.assertEqual(umf.sina_code("TSLA"), "gb_tsla")

    def test_lowercase_stock_none(self):
        self.assertIsNone(umf.sina_code("nvda"))  # 非大写 → 非雅虎风格代码

    def test_numeric_and_dotted_none(self):
        self.assertIsNone(umf.sina_code("00700"))   # A/港股纯数字防混入
        self.assertIsNone(umf.sina_code("BRK.B"))   # 含点号 → 不支持


class TestParse(unittest.TestCase):
    def test_int_dji_real_sample(self):
        code, p = umf.parse_line(LINE_INT_DJI)
        self.assertEqual(code, "int_dji")
        self.assertIsNotNone(p)
        self.assertEqual(p["name"], "道琼斯")
        self.assertEqual(p["price"], 46247.29)
        self.assertEqual(p["change_pct"], 0.65)
        self.assertEqual(p["quote_time"], "")       # int_ 无报价时间字段
        self.assertIsNone(p["prev_close"])          # 指数无昨收

    def test_znb_vix_real_sample(self):
        code, p = umf.parse_line(LINE_VIX)
        self.assertEqual(code, "znb_VIX")
        self.assertIsNotNone(p)
        self.assertEqual(p["name"], "VIX恐慌指数")
        self.assertEqual(p["price"], 14.52)         # 前 4 字段同 int_ 同构
        self.assertEqual(p["change_pct"], 1.47)

    def test_gb_prev_close_is_last_field(self):
        """gb_ 字段顺序相反 + 昨收=串末字段（bug#1 回归：若回退 fields[28]，8 字段串会 IndexError 挂）。"""
        code, p = umf.parse_line(LINE_GB_NVDA)
        self.assertEqual(code, "gb_nvda")
        self.assertIsNotNone(p)
        self.assertEqual(p["name"], "英伟达")
        self.assertEqual(p["price"], 230.36)
        self.assertEqual(p["change_pct"], 0.84)     # [2] 是涨跌幅%（int_ 是 [3]）
        self.assertEqual(p["quote_time"], "2026-09-05 09:46:13")
        self.assertEqual(p["prev_close"], 228.45)   # 串末字段

    def test_gb_short_fields_none(self):
        code, p = umf.parse_line('var hq_str_gb_x="名称,1.0";')  # <5 字段 → 行格式对但解析 None
        self.assertEqual(code, "gb_x")
        self.assertIsNone(p)

    def test_empty_payload_none_value(self):
        code, p = umf.parse_line('var hq_str_int_vix="";')  # 前科：新浪对空代码返回 ""
        self.assertEqual(code, "int_vix")
        self.assertIsNone(p)

    def test_non_row_and_malformed_none(self):
        self.assertIsNone(umf.parse_line("garbage line"))
        self.assertIsNone(umf.parse_line("var hq_str_xxx="))
        self.assertIsNone(umf.parse_line(""))


class TestSession(unittest.TestCase):
    """us_eastern_session：零依赖 DST 自算边界。全部 aware UTC 入参。"""

    def test_2026_dst_boundary_dates(self):
        # 2026-03-08 3月第2周日 / 2026-11-01 11月第1周日
        self.assertEqual(umf._second_sunday_march(2026), datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc))
        self.assertEqual(umf._first_sunday_november(2026), datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc))

    def test_mon_open_boundary_1300_1330(self):
        # 2026-09-07 周一夏令时(UTC-4)：13:00 UTC=09:00 ET 盘前；13:30 UTC=09:30 ET 盘中(开盘边界含)
        self.assertEqual(umf.us_eastern_session(datetime(2026, 9, 7, 13, 0, tzinfo=timezone.utc)), "盘前")
        self.assertEqual(umf.us_eastern_session(datetime(2026, 9, 7, 13, 29, 59, tzinfo=timezone.utc)), "盘前")
        self.assertEqual(umf.us_eastern_session(datetime(2026, 9, 7, 13, 30, tzinfo=timezone.utc)), "盘中")
        self.assertEqual(umf.us_eastern_session(datetime(2026, 9, 7, 20, 0, tzinfo=timezone.utc)), "盘后")  # 16:00 ET 收盘
        self.assertEqual(umf.us_eastern_session(datetime(2026, 9, 7, 23, 59, tzinfo=timezone.utc)), "盘后")
        self.assertEqual(umf.us_eastern_session(datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)), "休市")  # 20:00 ET 后

    def test_dst_winter_offset(self):
        # 2026-01-15 周四冬令时(UTC-5)：13:30 UTC=08:30 ET 盘前——若误用夏令时 -4 会返回"盘中"，抓 DST bug
        self.assertEqual(umf.us_eastern_session(datetime(2026, 1, 15, 13, 30, tzinfo=timezone.utc)), "盘前")
        self.assertEqual(umf.us_eastern_session(datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)), "盘中")  # 10:00 ET

    def test_weekend_closed(self):
        # 2026-09-05 周六任何时刻 → 休市（真网实测同标注）
        for h in (5, 13, 22):
            self.assertEqual(
                umf.us_eastern_session(datetime(2026, 9, 5, h, tzinfo=timezone.utc)), "休市", f"h={h}")

    def test_dst_start_weekday_after(self):
        # DST 3/8 切换后首个周一 3/9：13:30 UTC 应回盘中（EDT 生效）
        self.assertEqual(umf.us_eastern_session(datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc)), "盘中")


class TestDegrade(unittest.TestCase):
    """降级链三态：live → stale(旧缓存同键) → missing。"""

    def test_live_entry(self):
        rows = {"gb_nvda": make_parsed()}
        stm = {"gb_nvda": "NVDA"}
        entries, failures = umf.assemble_entries(rows, stm, {}, NOW_UTC)
        e = entries["NVDA"]
        self.assertEqual(e["source_mode"], "live")
        self.assertEqual(e["price"], 230.36)
        self.assertEqual(e["prev_close"], 228.45)
        self.assertEqual(e["quote_time"], "2026-09-05 09:46:13")
        self.assertEqual(e["updated"], "2026-09-07T13:30:00+00:00")
        self.assertNotIn("_stale_from", e)
        self.assertEqual(failures, {})

    def test_stale_keeps_old_value(self):
        rows = {"gb_nvda": None}  # 新浪对该码返回空（前科）
        old = {"NVDA": {"name": "英伟达", "price": 228.45, "change_pct": -0.31,
                        "updated": "2026-09-04T22:00:00+08:00", "source_mode": "live",
                        "session_note": "盘中"}}
        entries, failures = umf.assemble_entries(rows, {"gb_nvda": "NVDA"}, old, NOW_UTC)
        e = entries["NVDA"]
        self.assertEqual(e["source_mode"], "stale")
        self.assertEqual(e["price"], 228.45)                     # 旧快照值保留
        self.assertEqual(e["_stale_from"], "2026-09-04T22:00:00+08:00")
        self.assertEqual(e["rechecked_at"], "2026-09-07T13:30:00+00:00")
        self.assertEqual(failures["NVDA"], "sina_empty_stale")

    def test_missing_no_old_cache(self):
        rows = {"gb_nvda": None, "int_dji": None}
        entries, failures = umf.assemble_entries(rows, {"gb_nvda": "NVDA", "int_dji": "^DJI"}, {}, NOW_UTC)
        e = entries["NVDA"]
        self.assertEqual(e["source_mode"], "missing")
        self.assertIsNone(e["price"])                            # 不伪装实时
        self.assertEqual(e["session_note"], "盘中")
        self.assertEqual(failures["NVDA"], "sina_empty_no_cache")
        self.assertEqual(failures["^DJI"], "sina_empty_no_cache")

    def test_old_price_none_counts_missing(self):
        rows = {"gb_nvda": None}
        old = {"NVDA": {"name": "英伟达", "price": None, "source_mode": "missing"}}
        entries, failures = umf.assemble_entries(rows, {"gb_nvda": "NVDA"}, old, NOW_UTC)
        self.assertEqual(entries["NVDA"]["source_mode"], "missing")


class TestSaveCache(unittest.TestCase):
    def test_atomic_write_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "us_cache.json"
            data = {"^DJI": {"price": 46247.29, "source_mode": "live"}, "_meta": {"failures": {}}}
            umf.save_cache(data, out)
            self.assertTrue(out.exists())
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), data)
            leftover = list(Path(td).glob("*.tmp"))
            self.assertEqual(leftover, [])  # os.replace 后无 .tmp 残留


class TestRunFetch(unittest.TestCase):
    """run_fetch 主路径 mock 不触网：成功写盘结构 / 网络失败整体降级不 exit 非零。"""

    def _tmp_out(self):
        td = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(td, ignore_errors=True))
        return str(Path(td) / "us_cache.json")

    def test_ok_write_mixed_modes(self):
        out = self._tmp_out()
        rows = {"int_dji": {"name": "道琼斯", "price": 46247.29, "change_pct": 0.65,
                            "quote_time": "", "prev_close": None},
                "gb_nvda": None}  # 无旧缓存 → missing
        with unittest.mock.patch("us_market_fetch.fetch_rows", return_value=rows), \
                unittest.mock.patch("us_market_fetch.build_listing", return_value=[
                    {"symbol": "^DJI", "name": "^DJI", "kind": "index"},
                    {"symbol": "NVDA", "name": "NVDA", "kind": "stock"}]):
            rc = umf.run_fetch(dry_run=False, only_indexes=False, only_pool=False,
                               out_path=out, now=NOW_UTC)
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertEqual(data["^DJI"]["source_mode"], "live")
        self.assertEqual(data["NVDA"]["source_mode"], "missing")
        self.assertIsNone(data["NVDA"]["price"])
        self.assertEqual(data["_meta"]["session"], "盘中")
        self.assertEqual(data["_meta"]["failures"]["NVDA"], "sina_empty_no_cache")
        self.assertEqual(data["_meta"]["listing_count"], 2)

    def test_network_fail_overall_degrade_exit0(self):
        """断网/请求异常 → 不崩不 exit 非零；无旧缓存时全 missing（蓝图验证命令预期）。"""
        out = self._tmp_out()
        with unittest.mock.patch("us_market_fetch.fetch_rows",
                                 side_effect=requests.RequestException("conn refused")), \
                unittest.mock.patch("us_market_fetch.build_listing", return_value=[
                    {"symbol": "^DJI", "name": "^DJI", "kind": "index"}]):
            rc = umf.run_fetch(dry_run=False, only_indexes=False, only_pool=False,
                               out_path=out, now=NOW_UTC)
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertEqual(data["^DJI"]["source_mode"], "missing")
        self.assertEqual(data["_meta"]["failures"]["^DJI"], "sina_empty_no_cache")

    def test_network_fail_with_old_cache_stale(self):
        """断网但存在旧缓存 → 旧键 stale 不丢失（降级链第二级）。"""
        out = self._tmp_out()
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps({
            "^DJI": {"name": "道琼斯", "price": 46000.0, "change_pct": 0.1,
                     "updated": "2026-09-04T22:00:00+08:00", "source_mode": "live"},
            "_meta": {}}), encoding="utf-8")
        with unittest.mock.patch("us_market_fetch.fetch_rows",
                                 side_effect=requests.RequestException("conn refused")), \
                unittest.mock.patch("us_market_fetch.build_listing", return_value=[
                    {"symbol": "^DJI", "name": "^DJI", "kind": "index"}]):
            rc = umf.run_fetch(dry_run=False, only_indexes=False, only_pool=False,
                               out_path=out, now=NOW_UTC)
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertEqual(data["^DJI"]["source_mode"], "stale")
        self.assertEqual(data["^DJI"]["price"], 46000.0)
        self.assertEqual(data["^DJI"]["_stale_from"], "2026-09-04T22:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
