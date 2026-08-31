#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""monitor_progress.py — 每5分钟快照 task2 进度到日志，供持续汇报。"""
import sqlite3, time, datetime
from pathlib import Path

QB = Path("E:/qianboshi-agent/data/evidence/qianboshi_quality.db")
LOG = Path("C:/tmp/qb_progress.log")

while True:
    try:
        q = sqlite3.connect(QB)
        a = q.execute("SELECT COUNT(*) FROM view_evidence_annotation").fetchone()[0]
        s = q.execute("SELECT COUNT(*) FROM view_evidence_annotation WHERE supported=1").fetchone()[0]
        c = q.execute("SELECT COUNT(*) FROM claim").fetchone()[0]
        q.close()
        line = f"[{datetime.datetime.now():%m-%d %H:%M:%S}] annotation={a} supported={s} claim={c}"
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line, flush=True)
    except Exception as e:
        print("ERR", e, flush=True)
    time.sleep(300)
