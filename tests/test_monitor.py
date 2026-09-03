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
            for k in ("PORTFOLIO_FILE", "MARKET_CACHE_FILE", "PRICE_TRENDS_FILE",
                      "EVENTS_DIR", "JOBS_DIR")
        }
        monitor.PORTFOLIO_FILE = self.tmp / "portfolio.json"
        monitor.MARKET_CACHE_FILE = self.tmp / "market_cache.json"
        monitor.PRICE_TRENDS_FILE = self.tmp / "price_trends.json"
        monitor.EVENTS_DIR = self.tmp / "monitor_events"
        monitor.JOBS_DIR = self.tmp / "research_jobs"

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


    # ── E (P2): L4 补缺联动 ──────────────────────────────
    def _l2_events(self, change=-6.5):
        self._write("portfolio.json", {"holdings": {
            "518880": {"name": "华安黄金ETF", "sector": "黄金",
                       "market_code": "518880.SS", "shares": 200}}})
        self._write("market_cache.json", {"518880.SS": {
            "price": 8.4, "change_pct": change, "updated": "2026-09-03T10:00:00"}})
        return monitor.run_l2_check()

    def test_l4_fill_job_written_on_p0(self):
        r = self._l2_events()
        filled = monitor.submit_fill_jobs(r["events"])
        self.assertEqual(len(filled), 1)
        p = self.tmp / "research_jobs" / f"{filled[0]['job_id']}.json"
        j = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(j["source"], "monitor")
        self.assertEqual(j["status"], "queued")
        self.assertEqual(j["agent_type"], "analyst")
        self.assertEqual(j["category"], "monitor_fill")
        self.assertIn("华安黄金ETF", j["goal"])
        self.assertIn("跌6.5%", j["goal"])
        self.assertEqual(j["rule_id"], "P0-PRICE-01")
        self.assertEqual(j["_meta"]["market_code"], "518880.SS")

    def test_l4_fill_idempotent(self):
        r = self._l2_events()
        monitor.submit_fill_jobs(r["events"])
        again = monitor.submit_fill_jobs(r["events"])   # 同事件再跑 → 幂等跳过
        self.assertEqual(again, [])
        files = list((self.tmp / "research_jobs").glob("*.json"))
        self.assertEqual(len(files), 1)

    def test_l4_fill_skips_non_p0(self):
        # 蓝图 D5：P0 专属自动补缺；P1 事件不写 job
        p1 = [{"priority": "P1", "rule_id": "P1-HOT-02", "event_id": "x1",
               "entity": {"code": "T", "name": "题材", "market_code": "999999.SS"},
               "trigger": {"direction": "涨", "value": 7}}]
        filled = monitor.submit_fill_jobs(p1)
        self.assertEqual(filled, [])

    def test_fill_goal_format(self):
        ev = {"rule_id": "P0-PRICE-01", "priority": "P0",
              "entity": {"code": "601668", "name": "中国建筑", "market_code": "601668.SS"},
              "trigger": {"direction": "涨", "value": 5.2}}
        g = monitor._fill_goal(ev)
        self.assertIn("中国建筑(601668)", g)
        self.assertIn("涨5.2%", g)
        self.assertIn("P0-PRICE-01", g)

    # ── E (P2): P1-HOT 热度规则 ────────────────────────────
    def _hot_snap(self, tc=90, max_lbc=7, boards=None):
        return {"tc": tc, "max_lbc": max_lbc,
                "boards": boards or [{"name": "板块A", "change_pct": 6.0, "amount": 5e10},
                                     {"name": "板块B", "change_pct": 5.0, "amount": 9e10}],
                "fetched_at": "2026-09-03T15:00:00", "trade_date": "20260903"}

    def test_hot_rules_trigger(self):
        r = monitor.run_hot_check(fetch=lambda: self._hot_snap(tc=90, max_lbc=7))
        rules = {ev["rule_id"] for ev in r["events"]}
        self.assertIn("P1-HOT-01", rules)
        self.assertIn("P1-HOT-02", rules)
        for ev in r["events"]:
            self.assertEqual(ev["priority"], "P1")
            self.assertEqual(ev["level"], "L3")
            self.assertNotIn("买入", ev["note"])
            self.assertNotIn("卖出", ev["note"])   # 合规

    def test_hot_board_crowding(self):
        boards = [{"name": f"板块{i}", "change_pct": 9.0 - i * 0.1, "amount": (100 - i) * 1e9}
                  for i in range(20)]
        boards[0]["amount"] = 1e11   # 板块0 涨幅+成交额双最高 → 拥挤
        r = monitor.run_hot_check(fetch=lambda: self._hot_snap(tc=20, max_lbc=2, boards=boards))
        rules = {ev["rule_id"] for ev in r["events"]}
        self.assertIn("P1-HOT-03", rules)
        self.assertNotIn("P1-HOT-01", rules)   # tc=20 < 80
        self.assertNotIn("P1-HOT-02", rules)   # max_lbc=2 < 6

    def test_hot_below_threshold_no_events(self):
        r = monitor.run_hot_check(fetch=lambda: self._hot_snap(tc=44, max_lbc=5))
        self.assertEqual(r["events"], [])

    def test_hot_fetch_failure_degraded(self):
        def boom():
            raise RuntimeError("net down")
        r = monitor.run_hot_check(fetch=boom)
        self.assertEqual(r["events"], [])
        self.assertEqual(len(r["degraded"]), 1)
        self.assertIn("不可用", r["degraded"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
