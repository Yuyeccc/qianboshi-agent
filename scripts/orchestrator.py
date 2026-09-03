#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orchestrator.py —— 钱博士统一编排层（P1 最小版，ADR-001）

定位：
    research_agent = 研究领域执行器（单次研究任务流程）
    agent.py       = 通用 ReAct 推理子模块
    orchestrator   = 统一承载任务生命周期/队列/重试/超时/定时/事件分发/并发限制

与 portfolio backend/app/research_service.py 的关系：
    - 两者共享同一 job 目录 schema（DATA_DIR/research_jobs/*.json），job 字段兼容
    - research_service 由作品集 API 直接提交并自跑（daemon 线程）；
      orchestrator 是 agent 侧统一编排入口，drain 只认领 source=="orchestrator" 的
      queued 任务，绝不抢 research_service 的任务（防双头并发执行同一 job）
    - 架构演进方向（架构文档 v5 §3.3）：研究提交路径唯一化
      前端 → intent_gate → Orchestrator → research_agent

职责（最小版落地）：
    1. ResearchJob 状态机：queued → running → done | failed（文件级，原子写）
    2. 队列：drain 认领 queued 任务并发执行（max_workers）
    3. 重试：failed 且 attempts < max_attempts → 指数退避后回 queued
    4. 超时：子进程执行超时（默认 600s）→ failed
    5. 定时：Scheduler 周期任务注册 + tick（--schedule 常驻循环；agent.py run_schedule 迁入点）
    6. 事件分发：EVENT_HOOKS 注册表（L2/L3/L4 monitor 预留挂载点）
    7. 并发：ThreadPoolExecutor 认领队列

CLI 示例：
    python -m scripts.orchestrator --dry-run              # 演示：不碰生产数据/不调 LLM
    python -m scripts.orchestrator submit "黄金怎么看"     # 提交真实研究任务（过 intent_gate）
    python -m scripts.orchestrator submit "X" --executor fake   # fake 执行器冒烟（不耗 LLM）
    python -m scripts.orchestrator list --limit 10
    python -m scripts.orchestrator status <job_id>
    python -m scripts.orchestrator retry <job_id>
    python -m scripts.orchestrator drain --once            # 处理一轮队列
    python -m scripts.orchestrator --schedule              # 常驻：周期 drain + periodic hooks

dry-run 语义：全部在临时目录内模拟（fake 执行器），验证状态机/重试/事件/并发骨架，
不写生产 data、不调 LLM、不产生真实报告产物。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from config_loader import load_config, get_data_dir  # noqa: E402

# ── 路径与常量 ──────────────────────────────────────────────
CONFIG = load_config()
DATA_DIR = get_data_dir(CONFIG)
JOBS_DIR = DATA_DIR / "research_jobs"
REPORTS_DIR = DATA_DIR / "research"
RESEARCH_AGENT = PROJ / "scripts" / "research_agent.py"
SUB_TIMEOUT = 600  # 单次研究任务子进程超时（秒）
BACKOFF_BASE = 2   # 重试退避基数秒：2^attempts

# job 状态机合法值（与 research_service 对齐）
ST_QUEUED, ST_RUNNING, ST_DONE, ST_FAILED = "queued", "running", "done", "failed"

# 事件钩子注册表：event -> [fn(job)]（L2/L3/L4 monitor 挂载点）
EVENT_HOOKS: dict[str, list] = {"job_queued": [], "job_started": [], "job_done": [], "job_failed": [], "job_retry": []}


def on(event: str, fn) -> None:
    """注册事件钩子：on("job_done", lambda job: ...)"""
    if event not in EVENT_HOOKS:
        raise KeyError(f"未知事件: {event}（可用: {list(EVENT_HOOKS)}）")
    EVENT_HOOKS[event].append(fn)


def _emit(event: str, job: dict) -> None:
    for fn in EVENT_HOOKS.get(event, []):
        try:
            fn(job)
        except Exception as exc:  # 钩子异常不阻断任务流转
            print(f"[orchestrator] hook {event} 异常: {exc}", file=sys.stderr)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _now_dt() -> datetime:
    return datetime.now()


# ── job 文件 IO（schema 与 research_service 兼容 + 编排扩展字段）──
def _ensure_jobs_dir(jobs_dir: Path) -> None:
    jobs_dir.mkdir(parents=True, exist_ok=True)


def _write_job(job: dict, jobs_dir: Path) -> None:
    """原子写 job 文件：先写 temp 再 os.replace。"""
    _ensure_jobs_dir(jobs_dir)
    tmp = jobs_dir / f".{job['job_id']}.tmp"
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, jobs_dir / f"{job['job_id']}.json")


def _load_job(job_id: str, jobs_dir: Path) -> dict | None:
    p = jobs_dir / f"{job_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _update_job(job_id: str, jobs_dir: Path, **fields) -> None:
    job = _load_job(job_id, jobs_dir)
    if job is None:
        return
    job.update(fields)
    _write_job(job, jobs_dir)


def _pick_python() -> str:
    """子进程 python 优先级：显式 env -> 跑批权威 C:/Python314 -> 当前解释器。"""
    for cand in (
        os.environ.get("QIANBOSHI_RESEARCH_PYTHON"),
        r"C:\Python314\python.exe",
        sys.executable,
    ):
        if cand and Path(cand).exists():
            return cand
    return sys.executable


# ── 执行器 ─────────────────────────────────────────────────
def run_research_executor(job: dict, jobs_dir: Path, timeout: int = SUB_TIMEOUT) -> dict:
    """真实执行器：subprocess 调 research_agent.py --job-id（与 research_service 同契约）。

    返回 {"status": done|failed, "report_path": str|None, "error": str|None}
    """
    goal = job.get("goal", "")
    job_id = job["job_id"]
    py = _pick_python()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)  # research_agent 跑批环境要求干净 PYTHONPATH
    cmd = [py, str(RESEARCH_AGENT), goal, "--job-id", job_id]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(PROJ),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"status": ST_FAILED, "report_path": None, "error": f"timeout after {timeout}s"}
    except OSError as exc:
        return {"status": ST_FAILED, "report_path": None, "error": f"subprocess failed to start: {exc}"}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        tail = (stderr or stdout)[-2000:]
        return {"status": ST_FAILED, "report_path": None, "error": f"exit={proc.returncode}: {tail}"}

    report_path = _find_report(job_id)
    if report_path is None:
        return {"status": ST_FAILED, "report_path": None, "error": "exit=0 but no report file matched job_id"}
    return {"status": ST_DONE, "report_path": str(report_path), "error": None}


def _find_report(job_id: str) -> Path | None:
    """扫研究产物目录，找 _meta.job_id == job_id 的文件（mtime 最新优先）。"""
    if not REPORTS_DIR.exists():
        return None
    candidates = sorted(REPORTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (data.get("_meta") or {}).get("job_id") == job_id:
            return p
    return None


class FakeExecutor:
    """dry-run / fake 执行器：按 goal 前缀脚本化结果，不调 LLM 不落产物。"""

    def __init__(self, jobs_dir: Path, reports_dir: Path | None = None):
        self.jobs_dir = jobs_dir
        self.reports_dir = reports_dir

    def __call__(self, job: dict, jobs_dir: Path, timeout: int = SUB_TIMEOUT) -> dict:
        goal = job.get("goal", "")
        if goal.startswith("[always-fail]"):
            return {"status": ST_FAILED, "report_path": None, "error": "simulated persistent failure"}
        if goal.startswith("[fail-once]"):
            if job.get("attempts", 0) < 1:  # 首次(attempts=0)失败，重试轮(attempts>=1)成功
                return {"status": ST_FAILED, "report_path": None, "error": "simulated first-attempt failure"}
            return {"status": ST_DONE, "report_path": "(fake)", "error": None}
        # 普通成功：模拟报告产物（仅 dry-run 临时目录内）
        if self.reports_dir is not None:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            rep = {
                "coreIssue": goal,
                "summary": f"(fake) {goal} 的演示报告",
                "facts": [{"text": "dry-run 模拟产物，非真实研究", "source": "fake", "date": "2026-09-03"}],
                "_meta": {"job_id": job["job_id"], "schema_valid": True, "dry_run": True},
            }
            p = self.reports_dir / f"{job['job_id']}.json"
            p.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
            return {"status": ST_DONE, "report_path": str(p), "error": None}
        return {"status": ST_DONE, "report_path": "(fake)", "error": None}


# ── 编排核心 ───────────────────────────────────────────────
def submit_job(
    goal: str,
    jobs_dir: Path,
    category: str | None = None,
    max_attempts: int = 3,
    gate: dict | None = None,
    source: str = "orchestrator",
) -> dict:
    """创建 queued job（source==orchestrator，供 drain 认领）。"""
    job = {
        "job_id": uuid.uuid4().hex,
        "status": ST_QUEUED,
        "goal": goal,
        "category": category,
        "gate": gate or {},
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "report_path": None,
        "error": None,
        # orchestrator 扩展字段
        "source": source,
        "attempts": 0,
        "max_attempts": max_attempts,
        "next_retry_at": None,
    }
    _write_job(job, jobs_dir)
    _emit("job_queued", job)
    return job


def _claim_queued(jobs_dir: Path, worker: str, now: datetime) -> list[dict]:
    """认领 source==orchestrator 且到期的 queued 任务（置 running 返回）。"""
    _ensure_jobs_dir(jobs_dir)
    claimed = []
    for p in sorted(jobs_dir.glob("*.json")):
        try:
            job = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if job.get("status") != ST_QUEUED or job.get("source") != "orchestrator":
            continue
        nra = job.get("next_retry_at")
        if nra:
            try:
                if datetime.fromisoformat(nra) > now:
                    continue  # 退避未到期
            except ValueError:
                pass
        job["status"] = ST_RUNNING
        job["started_at"] = job.get("started_at") or _now()
        job["worker"] = worker
        _write_job(job, jobs_dir)
        claimed.append(job)
    return claimed


def _finalize(job: dict, result: dict, jobs_dir: Path) -> None:
    """执行结果写回：done / failed（按 max_attempts 决定终态或重试排队）。"""
    job_id = job["job_id"]
    if result["status"] == ST_DONE:
        _update_job(
            job_id, jobs_dir,
            status=ST_DONE, finished_at=_now(),
            report_path=result.get("report_path"), error=None,
        )
        _emit("job_done", _load_job(job_id, jobs_dir) or job)
        return

    attempts = job.get("attempts", 0) + 1
    max_attempts = job.get("max_attempts", 3)
    if attempts >= max_attempts:
        _update_job(
            job_id, jobs_dir,
            status=ST_FAILED, finished_at=_now(),
            attempts=attempts, error=result.get("error") or "failed",
        )
        _emit("job_failed", _load_job(job_id, jobs_dir) or job)
        return

    # 指数退避后回 queued（2^attempts 秒封顶 300s）
    backoff = min(BACKOFF_BASE ** attempts, 300)
    nra = (_now_dt() + timedelta(seconds=backoff)).isoformat(timespec="seconds")
    _update_job(
        job_id, jobs_dir,
        status=ST_QUEUED, started_at=None,
        attempts=attempts, error=result.get("error") or "failed",
        next_retry_at=nra,
    )
    job2 = _load_job(job_id, jobs_dir) or job
    _emit("job_retry", job2)
    print(f"  ↻ 任务 {job_id[:8]} 第 {attempts}/{max_attempts} 次失败，{backoff}s 后退避重试")


def drain_once(jobs_dir: Path, executor=None, max_workers: int = 2, timeout: int = SUB_TIMEOUT) -> dict:
    """处理一轮队列：认领到期 queued → 并发执行 → 写回。

    返回统计 {"claimed": n, "done": n, "failed": n, "retry_scheduled": n}
    """
    executor = executor or run_research_executor  # None → 真实研究执行器
    claimed = _claim_queued(jobs_dir, f"w-{os.getpid()}", _now_dt())
    if not claimed:
        return {"claimed": 0, "done": 0, "failed": 0, "retry_scheduled": 0}

    stats = {"claimed": len(claimed), "done": 0, "failed": 0, "retry_scheduled": 0}
    results = {}

    def _run(job):
        _emit("job_started", job)
        return job["job_id"], executor(job, jobs_dir, timeout=timeout)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(claimed))) as pool:
        futures = {pool.submit(_run, j): j for j in claimed}
        for fut in as_completed(futures):
            job = futures[fut]
            try:
                job_id, result = fut.result()
                results[job_id] = result
            except Exception as exc:  # 执行器自身抛异常 → 视为失败
                results[job["job_id"]] = {"status": ST_FAILED, "report_path": None, "error": f"executor crashed: {exc}"}

    for job in claimed:
        result = results.get(job["job_id"], {"status": ST_FAILED, "report_path": None, "error": "no result"})
        if result["status"] == ST_DONE:
            stats["done"] += 1
        elif job.get("attempts", 0) + 1 >= job.get("max_attempts", 3):
            stats["failed"] += 1
        else:
            stats["retry_scheduled"] += 1
        _finalize(job, result, jobs_dir)
    return stats


def _list_jobs(jobs_dir: Path, limit: int = 20) -> list[dict]:
    _ensure_jobs_dir(jobs_dir)
    jobs = []
    for p in jobs_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        jobs.append({
            "job_id": data.get("job_id"),
            "status": data.get("status"),
            "goal": (data.get("goal") or "")[:48],
            "attempts": data.get("attempts", 0),
            "max_attempts": data.get("max_attempts", 3),
            "created_at": data.get("created_at"),
            "finished_at": data.get("finished_at"),
            "report_path": data.get("report_path"),
            "error": (data.get("error") or "")[:80],
        })
    jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return jobs[:limit]


# ── 定时骨架（run_schedule 迁入点）────────────────────────
class Scheduler:
    """周期任务注册 + tick。--schedule 模式下由 orchestrator 主循环驱动。"""

    def __init__(self):
        self._tasks: list[dict] = []  # {name, interval_s, fn, next_run}

    def every(self, name: str, interval_s: float, fn) -> None:
        self._tasks.append({"name": name, "interval_s": interval_s, "fn": fn, "next_run": time.time()})

    def tick(self) -> list[str]:
        """执行到期任务，返回本次触发名单。"""
        now = time.time()
        fired = []
        for t in self._tasks:
            if now >= t["next_run"]:
                try:
                    t["fn"]()
                    fired.append(t["name"])
                except Exception as exc:
                    print(f"[orchestrator] 周期任务 {t['name']} 异常: {exc}", file=sys.stderr)
                t["next_run"] = now + t["interval_s"]
        return fired


# ── dry-run 演示 ───────────────────────────────────────────
def dry_run_demo() -> int:
    """临时目录 + fake 执行器：演示状态机/重试退避/事件钩子/并发认领。

    覆盖：成功 ×1、首败重试成功 ×1、持续失败耗尽次数 ×1、gate 记录透传。
    不碰生产 data/research_jobs，不调 LLM。
    """
    print("=" * 64)
    print("Orchestrator --dry-run（临时目录模拟，不写生产数据/不调 LLM）")
    print("=" * 64)
    tmp = Path(tempfile.mkdtemp(prefix="orch_dryrun_"))
    jobs_dir = tmp / "jobs"
    reports_dir = tmp / "reports"
    fake = FakeExecutor(jobs_dir, reports_dir)

    # 事件钩子演示
    def _on_done(job):
        print(f"  [event job_done] {job['job_id'][:8]} → {job.get('report_path')}")

    def _on_failed(job):
        print(f"  [event job_failed] {job['job_id'][:8]} → {job.get('error')}")

    def _on_retry(job):
        print(f"  [event job_retry] {job['job_id'][:8]} attempts={job.get('attempts')}")

    on("job_done", _on_done)
    on("job_failed", _on_failed)
    on("job_retry", _on_retry)

    # 提交 3 个演示任务
    g1 = submit_job("演示：黄金 9 月情景推演（一次成功）", jobs_dir, max_attempts=1)
    g2 = submit_job("[fail-once] 演示：地产板块复盘（首败后重试成功）", jobs_dir, max_attempts=2)
    g3 = submit_job("[always-fail] 演示：光模块（持续失败耗尽次数）", jobs_dir, max_attempts=2)
    print(f"\n提交 3 任务: {g1['job_id'][:8]} / {g2['job_id'][:8]} / {g3['job_id'][:8]}")

    # 第一轮 drain：g2 首败进退避，g3 首败进退避
    print("\n── 第一轮 drain ──")
    s1 = drain_once(jobs_dir, executor=fake, max_workers=3)
    print(f"统计: {s1}")

    # 第二轮 drain：g2 重试成功；g3 二败耗尽次数 → failed
    print("\n── 第二轮 drain（退避到期模拟，重试兑现）──")
    # 把 next_retry_at 拨回过去以演示到期重试（退避时长本身已由 _finalize 打印）
    for p in jobs_dir.glob("*.json"):
        job = json.loads(p.read_text(encoding="utf-8"))
        if job.get("status") == ST_QUEUED and job.get("next_retry_at"):
            _update_job(job["job_id"], jobs_dir, next_retry_at=_now_dt().isoformat(timespec="seconds"))
    s2 = drain_once(jobs_dir, executor=fake, max_workers=3)
    print(f"统计: {s2}")

    # 终态断言
    rows = _list_jobs(jobs_dir, limit=10)
    print("\n── 终态一览 ──")
    print(f"{'job_id':<10} {'status':<7} {'attempts':<4} report/error")
    for r in rows:
        tail = r["report_path"] or r["error"] or ""
        print(f"{r['job_id'][:8]:<10} {r['status']:<7} {r['attempts']}/{r['max_attempts']:<3} {tail[:60]}")

    m = {r["job_id"][:8]: r for r in rows}
    ok = (
        m.get(g1["job_id"][:8], {}).get("status") == ST_DONE
        and m.get(g2["job_id"][:8], {}).get("status") == ST_DONE
        and m.get(g3["job_id"][:8], {}).get("status") == ST_FAILED
    )
    print("\n结果:", "✅ 状态机/重试/事件演示全部符合预期" if ok else "❌ 断言失败，请检查")
    # 清理临时目录
    for p in tmp.rglob("*"):
        try:
            p.unlink() if p.is_file() else None
        except OSError:
            pass
    return 0 if ok else 1


# ── CLI ────────────────────────────────────────────────────
def _gate_check(goal: str) -> dict | None:
    """提交前过 intent_gate（fail-closed，与 API 同纪律）。block/clarify 返回拒绝原因。"""
    try:
        from intent_gate import classify_question
        g = classify_question(goal)
        if g.get("verdict") not in ("pass",):
            return g
        return None
    except Exception as exc:
        return {"verdict": "block", "reason": f"intent_gate_unavailable: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser(description="钱博士统一编排层（P1 最小版）")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("dry-run", help="演示（临时目录+fake 执行器，不碰生产数据）")
    p_submit = sub.add_parser("submit", help="提交研究任务")
    p_submit.add_argument("goal")
    p_submit.add_argument("--category", default=None)
    p_submit.add_argument("--max-attempts", type=int, default=3)
    p_submit.add_argument("--executor", choices=["real", "fake"], default="real")
    p_submit.add_argument("--skip-gate", action="store_true", help="跳过 intent_gate（仅调试用）")
    p_submit.add_argument("--jobs-dir", default=None, help="job 目录覆盖（默认 DATA_DIR/research_jobs）")

    p_list = sub.add_parser("list", help="列出任务")
    p_list.add_argument("--limit", type=int, default=20)

    p_status = sub.add_parser("status", help="查看任务")
    p_status.add_argument("job_id")

    p_retry = sub.add_parser("retry", help="手动重试 failed 任务（清零 attempts 立即排队）")
    p_retry.add_argument("job_id")

    p_drain = sub.add_parser("drain", help="处理一轮队列")
    p_drain.add_argument("--once", action="store_true", help="(默认) 单轮")
    p_drain.add_argument("--max-workers", type=int, default=2)

    p_sched = sub.add_parser("schedule", help="常驻：周期 drain + periodic hooks")
    p_sched.add_argument("--interval", type=int, default=300, help="drain 周期秒（默认 300）")
    p_sched.add_argument("--max-workers", type=int, default=2)

    args = ap.parse_args()

    if args.cmd == "dry-run" or args.cmd is None:
        return dry_run_demo()

    jobs_dir = Path(args.jobs_dir) if getattr(args, "jobs_dir", None) else JOBS_DIR

    if args.cmd == "submit":
        gate = None if args.skip_gate else _gate_check(args.goal)
        if gate:
            print(f"⛔ intent_gate 拦截（{gate.get('rule_version', 'n/a')}）: {gate.get('verdict')} — {gate.get('reason')}")
            return 2
        job = submit_job(args.goal, jobs_dir, category=args.category, max_attempts=args.max_attempts, gate=gate or {})
        print(f"已入队: {job['job_id']}  source={job['source']}")
        if args.executor == "fake":
            print("fake 执行器冒烟（不调 LLM）…")
            stats = drain_once(jobs_dir, executor=FakeExecutor(jobs_dir), max_workers=1)
            print(f"统计: {stats}")
            final = _load_job(job["job_id"], jobs_dir)
            print(f"终态: {final['status']}  report={final.get('report_path')}")
        else:
            print("提示: 执行请运行 `python -m scripts.orchestrator drain --once`（或 --schedule 常驻）")
        return 0

    if args.cmd == "list":
        for r in _list_jobs(jobs_dir, limit=args.limit):
            print(f"{r['job_id'][:8]} {r['status']:<7} {r['attempts']}/{r['max_attempts']} {r['goal']}")
        return 0

    if args.cmd == "status":
        job = _load_job(args.job_id, jobs_dir)
        if job is None:
            print(f"任务不存在: {args.job_id}")
            return 1
        print(json.dumps(job, ensure_ascii=False, indent=1))
        return 0

    if args.cmd == "retry":
        job = _load_job(args.job_id, jobs_dir)
        if job is None:
            print(f"任务不存在: {args.job_id}")
            return 1
        _update_job(args.job_id, jobs_dir, status=ST_QUEUED, attempts=0, error=None,
                    next_retry_at=None, finished_at=None, started_at=None)
        print(f"已重置排队: {args.job_id}")
        return 0

    if args.cmd == "drain":
        stats = drain_once(jobs_dir, executor=run_research_executor, max_workers=args.max_workers)
        print(f"统计: {stats}")
        return 0

    if args.cmd == "schedule":
        sched = Scheduler()
        # 周期 drain（run_schedule 迁入点：盘前简报等可在此 every() 注册）
        sched.every("drain-queue", args.interval, lambda: print(f"[schedule] drain → {drain_once(jobs_dir, executor=run_research_executor, max_workers=args.max_workers)}"))
        print(f"🕐 orchestrator --schedule 常驻（drain 周期 {args.interval}s，Ctrl+C 停止）")
        try:
            while True:
                sched.tick()
                time.sleep(5)
        except KeyboardInterrupt:
            print("\n调度器已停止")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
