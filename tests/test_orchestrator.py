"""orchestrator.py 最小版单测：状态机/队列认领/重试退避/事件钩子（tmp 目录 + fake 执行器，不碰生产数据）"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from orchestrator import (  # noqa: E402
    EVENT_HOOKS,
    FakeExecutor,
    ST_DONE,
    ST_FAILED,
    ST_QUEUED,
    ST_RUNNING,
    drain_once,
    on,
    submit_job,
)


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_orch_"))
        self.jobs = self.tmp / "jobs"
        self.reports = self.tmp / "reports"
        self.fake = FakeExecutor(self.jobs, self.reports)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_submit_writes_queued_job(self):
        job = submit_job("黄金 9 月情景推演", self.jobs, max_attempts=2)
        p = self.jobs / f"{job['job_id']}.json"
        self.assertTrue(p.exists())
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], ST_QUEUED)
        self.assertEqual(data["source"], "orchestrator")
        self.assertEqual(data["max_attempts"], 2)

    def test_drain_success_and_report(self):
        job = submit_job("地产板块复盘", self.jobs, max_attempts=1)
        stats = drain_once(self.jobs, executor=self.fake, max_workers=2)
        self.assertEqual(stats["done"], 1)
        final = json.loads((self.jobs / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(final["status"], ST_DONE)
        self.assertIn("job_id", json.loads(Path(final["report_path"]).read_text(encoding="utf-8"))["_meta"])

    def test_retry_backoff_then_success(self):
        job = submit_job("[fail-once] 光模块复盘", self.jobs, max_attempts=2)
        # 第一轮：失败 → 回 queued + next_retry_at 未来时间
        drain_once(self.jobs, executor=self.fake, max_workers=1)
        final = json.loads((self.jobs / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(final["status"], ST_QUEUED)
        self.assertEqual(final["attempts"], 1)
        nra = datetime.fromisoformat(final["next_retry_at"])
        self.assertGreater(nra, datetime.now())
        # 拨快时钟模拟退避到期
        expired = (datetime.now() - timedelta(seconds=1)).isoformat(timespec="seconds")
        from orchestrator import _update_job
        _update_job(job["job_id"], self.jobs, next_retry_at=expired)
        stats = drain_once(self.jobs, executor=self.fake, max_workers=1)
        self.assertEqual(stats["done"], 1)
        final = json.loads((self.jobs / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(final["status"], ST_DONE)
        self.assertEqual(final["attempts"], 1)

    def test_persistent_failure_exhausts_attempts(self):
        job = submit_job("[always-fail] 无法完成的任务", self.jobs, max_attempts=2)
        drain_once(self.jobs, executor=self.fake, max_workers=1)
        # 第一轮后应处于 queued(退避中)
        mid = json.loads((self.jobs / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(mid["status"], ST_QUEUED)
        # 拨快 + 第二轮 → failed 终态
        from orchestrator import _update_job
        expired = (datetime.now() - timedelta(seconds=1)).isoformat(timespec="seconds")
        _update_job(job["job_id"], self.jobs, next_retry_at=expired)
        stats = drain_once(self.jobs, executor=self.fake, max_workers=1)
        self.assertEqual(stats["failed"], 1)
        final = json.loads((self.jobs / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(final["status"], ST_FAILED)
        self.assertEqual(final["attempts"], 2)

    def test_event_hooks_fired(self):
        fired = {"done": 0, "failed": 0, "retry": 0, "queued": 0}
        saved = {k: list(v) for k, v in EVENT_HOOKS.items()}

        def _cleanup():
            for k in EVENT_HOOKS:
                EVENT_HOOKS[k] = saved.get(k, [])

        self.addCleanup(_cleanup)
        on("job_queued", lambda j: fired.__setitem__("queued", fired["queued"] + 1))
        on("job_done", lambda j: fired.__setitem__("done", fired["done"] + 1))
        on("job_failed", lambda j: fired.__setitem__("failed", fired["failed"] + 1))
        on("job_retry", lambda j: fired.__setitem__("retry", fired["retry"] + 1))

        submit_job("黄金复盘", self.jobs, max_attempts=1)                    # queued+1
        submit_job("[always-fail] 失败的", self.jobs, max_attempts=2)        # queued+1
        drain_once(self.jobs, executor=self.fake, max_workers=2)             # done+1, retry+1
        from orchestrator import _update_job
        import glob as _g
        for p in _g.glob(str(self.jobs / "*.json")):
            d = json.loads(open(p, encoding="utf-8").read())
            if d.get("status") == ST_QUEUED and d.get("next_retry_at"):
                _update_job(d["job_id"], self.jobs,
                            next_retry_at=(datetime.now() - timedelta(seconds=1)).isoformat(timespec="seconds"))
        drain_once(self.jobs, executor=self.fake, max_workers=2)             # failed+1
        self.assertGreaterEqual(fired["queued"], 2)
        self.assertEqual(fired["done"], 1)
        self.assertEqual(fired["failed"], 1)
        self.assertGreaterEqual(fired["retry"], 1)

    def test_claim_monitor_source_job(self):
        # E (P2): L4 补缺 job(source=monitor) 被 drain 认领流转（自产自销，无双头）
        job = submit_job("补缺研究", self.jobs, max_attempts=1,
                         source="monitor", agent_type="analyst")
        stats = drain_once(self.jobs, executor=self.fake, max_workers=1)
        self.assertEqual(stats["claimed"], 1)
        self.assertEqual(stats["done"], 1)
        final = json.loads((self.jobs / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(final["status"], ST_DONE)

    def test_claim_only_own_source(self):
        """drain 不认领非 orchestrator 的 queued 任务（防与 research_service 双头执行）。"""
        job = submit_job("外部任务", self.jobs, max_attempts=1, source="research_service")
        stats = drain_once(self.jobs, executor=self.fake, max_workers=1)
        self.assertEqual(stats["claimed"], 0)
        final = json.loads((self.jobs / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(final["status"], ST_QUEUED)

    # ── P2-A: job 契约 agent_type + executor 分派 ──
    def test_old_job_defaults_analyst(self):
        """现役调用方式（不带 agent_type）→ job 落盘 agent_type=analyst（向后兼容）。"""
        job = submit_job("黄金 9 月情景推演", self.jobs, max_attempts=2)
        data = json.loads((self.jobs / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(data["agent_type"], "analyst")

    def test_submit_carries_agent_type(self):
        job = submit_job("持仓风险评估", self.jobs, max_attempts=2, agent_type="portfolio_risk")
        data = json.loads((self.jobs / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(data["agent_type"], "portfolio_risk")

    def test_resolve_agent_script_dispatch(self):
        """分派纯函数：缺省/analyst → research_agent.py；risk/review → 各自脚本。"""
        from orchestrator import AGENT_SCRIPTS, resolve_agent_script
        self.assertEqual(resolve_agent_script({}), AGENT_SCRIPTS["analyst"])
        self.assertEqual(resolve_agent_script({"agent_type": "analyst"}), AGENT_SCRIPTS["analyst"])
        self.assertEqual(resolve_agent_script({"agent_type": "portfolio_risk"}), AGENT_SCRIPTS["portfolio_risk"])
        self.assertEqual(resolve_agent_script({"agent_type": "decision_review"}), AGENT_SCRIPTS["decision_review"])
        self.assertIsNone(resolve_agent_script({"agent_type": "bogus"}))

    def test_run_executor_fail_closed_missing_script(self):
        """分派脚本路径不存在时执行 → failed（不静默当 analyst 跑、不调 LLM）。"""
        from unittest import mock
        from orchestrator import run_research_executor
        job = submit_job("持仓风险评估", self.jobs, max_attempts=1, agent_type="portfolio_risk")
        with mock.patch.dict("orchestrator.AGENT_SCRIPTS",
                             {"portfolio_risk": Path("Z:/nonexistent/portfolio_risk_agent.py")}):
            result = run_research_executor(job, self.jobs, timeout=5)
        self.assertEqual(result["status"], ST_FAILED)
        self.assertIn("执行脚本缺失", result["error"] or "")

    def test_run_executor_unknown_type_fail_closed(self):
        from orchestrator import run_research_executor
        job = {"job_id": "x" * 32, "goal": "测试", "agent_type": "bogus"}
        result = run_research_executor(job, self.jobs, timeout=5)
        self.assertEqual(result["status"], ST_FAILED)
        self.assertIn("未知 agent_type", result["error"] or "")


if __name__ == "__main__":
    unittest.main()
