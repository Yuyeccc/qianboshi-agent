#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qb_progress_cron.py — 每5分钟报 reasoning_unit 归并进度（no-agent script job）。

归并完成时输出完成消息并自动移除本 cron，避免永久刷屏。

用法: 由 hermes cron 以 no-agent script 模式调用
  hermes cron create '5m' --name qb_ru_progress --script qb_progress_cron.py --workdir E:\qianboshi-agent --no-agent
"""
import sqlite3, subprocess, re, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent   # E:\qianboshi-agent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
JOB_NAME = "qb_ru_progress"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

q = sqlite3.connect(QB)
c = q.cursor()
done = c.execute("SELECT COUNT(*) FROM reasoning_unit_window WHERE status='succeeded'").fetchone()[0]
total = c.execute("SELECT COUNT(*) FROM reasoning_unit_window").fetchone()[0]
ru = c.execute("SELECT COUNT(*) FROM reasoning_unit WHERE status='active'").fetchone()[0]
q.close()

if total == 0:
    print("⚠️ reasoning_unit_window 为空，检查窗口构建。")
    sys.exit(0)

pct = done / total * 100
if done < total:
    # 估算：约 1.7 窗/分钟
    eta = max(1, int((total - done) * 0.6))
    print(f"⏳ #6 reasoning_unit 归并进行中：{done}/{total} 窗口（{pct:.0f}%）已完成，累计产出 {ru} 个推理单元，预计还需约 {eta} 分钟")
else:
    print(f"✅ #6 reasoning_unit 归并完成：{total} 窗口全部归并，累计产出 {ru} 个推理单元，source_text 均已服务端回放，等待质量验证")
    # 自删本 cron
    try:
        out = subprocess.check_output(["hermes", "cron", "list"], stderr=subprocess.STDOUT, shell=True)
        text = out.decode("utf-8", "ignore")
        for m in re.finditer(r'^\s*([0-9a-f]{12})\s+\[active\]\s*\n\s*Name:\s+' + re.escape(JOB_NAME) + r'\b', text, re.M):
            subprocess.run(["hermes", "cron", "remove", m.group(1)], shell=True)
            print(f"   (已自动移除进度 cron：{m.group(1)})")
    except Exception as e:
        print(f"   (cron 自删失败：{e})")
