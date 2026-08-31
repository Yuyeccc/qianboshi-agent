#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task2_done_check.py — task2 维度标注完成自动提醒（配合 cron no_agent 每 15 分钟）。

契约：stdout 非空 → 投递；空 → 静默。
逻辑：view_evidence_annotation 计数 >= 1400（最近1月全量）且 != 上次报告数 → 输出摘要。
"""
import sqlite3, json, datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
STATE = Path("C:/tmp/task2_reported.json")
TARGET = 1400

try:
    conn = sqlite3.connect(QB)
    cur = conn.cursor()
    n = cur.execute("SELECT COUNT(*) FROM view_evidence_annotation").fetchone()[0]
    sup = cur.execute("SELECT COUNT(*) FROM view_evidence_annotation WHERE supported=1").fetchone()[0]
    # 剩余未标注锚定观点（对齐 evidence_tagger 取数口径）
    rem = cur.execute("""SELECT COUNT(*) FROM view_raw v JOIN view_provenance p ON p.view_id=v.view_id
      WHERE p.anchor_start_ms IS NOT NULL AND p.anchor_start_ms>0
      AND NOT EXISTS (SELECT 1 FROM view_evidence_annotation a WHERE a.view_id=v.view_id)""").fetchone()[0]
    conn.close()
except Exception as e:
    print(f"⚠️ task2 检查异常: {e}")
    raise SystemExit(1)

if rem > 0:
    raise SystemExit(0)  # 未完成，静默

last = {}
if STATE.exists():
    try:
        last = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        last = {}
if last.get("count") == n:
    raise SystemExit(0)  # 已报告过

ts = datetime.datetime.now().strftime("%m-%d %H:%M")
sup_pct = round(sup / n * 100, 1) if n else 0
print(f"✅ task2 全量标注跑完（{ts}）：{n} 条，真实支撑率 {sup_pct}%（supported {sup}）")
STATE.write_text(json.dumps({"count": n, "reported_at": ts}, ensure_ascii=False), encoding="utf-8")
