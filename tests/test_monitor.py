"""monitor.py L2/L3 最小版单测：规则触发/事件字段/缓存超期/模拟注入（tmp 数据目录，不碰生产）"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import monitor  # noqa: E402


class MonitorTests(unittest.TestCase):
    def setUp(self):
        # 隔离数据目录：monitor 模块的 *_FILE/EVENTS_DIR 指向 tmp
        self.tmp = Path(tempfile.mkdtemp(prefix="test_monitor_"))
        self._saved = {
            k: getattr(monitor, k)
            for k in ("PORTFOLIO_FILE", "MARKET_CACHE_FILE", "PRICE_TRENDS_FILE", "EVENTS_DIR")
        }
        monitor.PORTFOLIO_FILE = self.tmp / "portfolio.json"
        monitor.MARKET_CACHE_FILE = self.tmp / "market_cache.json"
        monitor.PRICE_TRENDS_FILE = self.tmp / "price_trends.json"
        monitor.EVENTS_DIR = self.tmp / "monitor_events"

    def tearDown(self):
        import shutil
        for k, v in self._saved.items():
            setattr(monitor, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, data):
        p = self.tmp / name
        # 与仓内一致带 BOM
        p.write_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8-sig"))
        return p

    def test_price_rule_triggers_l3_event(self):
        self._write("portfolio.json", {"holdings": {
            "518880": {"name": "华安黄金ETF", "sector": "黄金",
                       "market_code": "518880.SS", "shares": 200}}})
        self._write("market_cache.json", {"518880.SS": {
            "price": 8.4, "change_pct": -6.5, "updated": "2026-09-03T10:00:00"}})
        r = monitor.run_l2_check()
        self.assertEqual(len(r["events"]), 1)
        ev = r["events"][0]
        self.assertEqual(ev["rule_id"], "P0-PRICE-01")
        self.assertEqual(ev["level"], "L3")
        self.assertEqual(ev["priority"], "P0")
        self.assertEqual(ev["status"], "queued")
        self.assertEqual(ev["entity"]["market_code"], "518880.SS")
        self.assertEqual(ev["trigger"]["value"], -6.5)
        self.assertEqual(ev["trigger"]["direction"], "跌")
        self.assertNotIn("买入", ev["note"])
        self.assertNotIn("卖出", ev["note"])  # 合规：事件不含交易指令

    def test_no_trigger_within_threshold(self):
        self._write("portfolio.json", {"holdings": {
            "518880": {"name": "黄金", "sector": "黄金", "market_code": "518880.SS"}}})
        self._write("market_cache.json", {"518880.SS": {
            "price": 9.0, "change_pct": 1.2, "updated": "2026-09-03T10:00:00"}})
        r = monitor.run_l2_check()
        self.assertEqual(r["events"], [])
        self.assertEqual(r["checked"][0]["note"], "无异常")

    def test_simulate_injection_triggers(self):
        self._write("portfolio.json", {"holdings": {
            "601668": {"name": "中国建筑", "sector": "基建", "market_code": "601668.SS"}}})
        # 缓存无该标的 → 但 simulate 注入可触发（不读缓存）
        self._write("market_cache.json", {})
        r = monitor.run_l2_check(simulate={"601668.SS": 5.2})
        self.assertEqual(len(r["events"]), 1)
        self.assertEqual(r["events"][0]["trigger"]["direction"], "涨")
        self.assertEqual(r["checked"][0]["quote_source"], "simulate")

    def test_stale_cache_degraded_note(self):
        self._write("portfolio.json", {"holdings": {
            "518880": {"name": "黄金", "sector": "黄金", "market_code": "518880.SS"}}})
        old = "2026-09-01T10:00:00"  # > MAX_CACHE_HOURS
        self._write("market_cache.json", {"518880.SS": {
            "price": 9.0, "change_pct": 1.0, "updated": old}})
        r = monitor.run_l2_check()
        self.assertEqual(r["events"], [])
        self.assertEqual(len(r["degraded"]), 1)
        self.assertIn("超期", r["checked"][0]["note"])

    def test_missing_market_code_skipped(self):
        self._write("portfolio.json", {"holdings": {
            "027695": {"name": "联接C", "sector": "电池", "market_code": "", "shares": 100}}})
        self._write("market_cache.json", {})
        r = monitor.run_l2_check()
        self.assertEqual(r["events"], [])
        self.assertIn("跳过", r["checked"][0]["note"])

    def test_cache_missing_symbol_skipped(self):
        self._write("portfolio.json", {"holdings": {
            "601668": {"name": "中国建筑", "sector": "基建", "market_code": "601668.SS"}}})
        self._write("market_cache.json", {})
        r = monitor.run_l2_check()
        self.assertEqual(r["events"], [])
        self.assertIn("跳过", r["checked"][0]["note"])

    def test_save_events_writes_files(self):
        self._write("portfolio.json", {"holdings": {
            "518880": {"name": "黄金", "sector": "黄金", "market_code": "518880.SS"}}})
        self._write("market_cache.json", {"518880.SS": {
            "price": 8.4, "change_pct": -6.5, "updated": "2026-09-03T10:00:00"}})
        r = monitor.run_l2_check()
        saved = monitor._save_events(r["events"])
        self.assertEqual(len(saved), 1)
        ev = json.loads(Path(saved[0]).read_text(encoding="utf-8"))
        self.assertEqual(ev["rule_id"], "P0-PRICE-01")


if __name__ == "__main__":
    unittest.main()
