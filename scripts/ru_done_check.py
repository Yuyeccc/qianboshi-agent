#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ru_done_check.py — 归并完成自动提醒（配合 cron no_agent 每 10 分钟跑一次）。

输出契约（no_agent 模式）：
- stdout 非空 → 原样投递到 cron 的 deliver 目标（飞书群）
- stdout 为空 → 静默，不打扰

逻辑：
- pending>0 → 还在跑，静默
- pending==0 且 succeeded 数 != 上次已报告数 → 输出完成摘要（含 failed 警告），记录已报告
- 已报告过相同状态 → 静默（防重复推送）

用法: env -u PYTHONPATH C:\\Python314\\python.exe scripts\\ru_done_check.py
"""
import sqlite3, json, datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
STATE = Path("C:/tmp/qb_ru_reported.json")

try:
    conn = sqlite3.connect(QB)
    cur = conn.cursor()
    succ = cur.execute("SELECT COUNT(*) FROM reasoning_unit_window WHERE status='succeeded'").fetchone()[0]
    fail = cur.execute("SELECT COUNT(*) FROM reasoning_unit_window WHERE status='failed'").fetchone()[0]
    pend = cur.execute("SELECT COUNT(*) FROM reasoning_unit_window WHERE status='pending'").fetchone()[0]
    ru = cur.execute("SELECT COUNT(*) FROM reasoning_unit WHERE status='active'").fetchone()[0]
    conn.close()
except Exception as e:
    print(f"⚠️ 归并状态检查脚本异常: {e}")
    raise SystemExit(1)

if pend > 0:
    raise SystemExit(0)  # 还在跑，静默

# 已完成（pending==0）：只在 succeeded 数变化时推送一次
last = {}
if STATE.exists():
    try:
        last = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        last = {}

if last.get("succeeded") == succ:
    raise SystemExit(0)  # 已报告过，静默

ts = datetime.datetime.now().strftime("%m-%d %H:%M")
lines = [f"✅ 归并跑完自动提醒（{ts}）："]
lines.append(f"窗口 {succ + fail} 个全部处理完毕：succeeded {succ} / failed {fail} / pending {pend}")
lines.append(f"reasoning_unit 累计 {ru} 条")
if fail > 0:
    lines.append(f"⚠️ 仍有 {fail} 个 failed 窗，需要重跑——说声\"重跑归并\"即可")
STATE.write_text(json.dumps({"succeeded": succ, "reported_at": ts}, ensure_ascii=False), encoding="utf-8")
print("\n".join(lines))
