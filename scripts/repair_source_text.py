#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""repair_source_text.py — 修复已落库 reasoning_unit 的空 source_text。

reasoning_unit_source 的 candidate_sentence_id 形如 cs_209027 → 对应 candidate_sentence.id=209027。
从 candidate_sentence 文本用整句拼回 source_text（可信、防幻觉，服务端拼）。

用法: env -u PYTHONPATH python scripts/repair_source_text.py
"""
import re, sqlite3
from pathlib import Path
PROJ = Path(__file__).resolve().parent.parent
QB = PROJ / "data" / "evidence" / "qianboshi_quality.db"
EV = PROJ / "data" / "evidence" / "qianboshi_evidence.db"

CS_RE = re.compile(r'^cs_(\d+)$')

q = sqlite3.connect(QB); qc = q.cursor()
e = sqlite3.connect(EV); ec = e.cursor()

# 所有需要修的 ru（source_text 空或为占位）
ru_list = [r[0] for r in qc.execute(
    "SELECT reasoning_unit_id FROM reasoning_unit WHERE status='active'")]
n_fix = 0
for ru_id in ru_list:
    cs_ids = [r[0] for r in qc.execute(
        "SELECT candidate_sentence_id FROM reasoning_unit_source WHERE reasoning_unit_id=? ORDER BY sentence_order", (ru_id,))]
    parts = []
    for cid in cs_ids:
        m = CS_RE.match(cid)
        if not m:
            continue
        row = e.execute("SELECT text FROM candidate_sentence WHERE id=?", (int(m.group(1)),)).fetchone()
        if row:
            parts.append(row[0])
    src = "".join(parts)
    if src:
        qc.execute("UPDATE reasoning_unit SET source_text=? WHERE reasoning_unit_id=?", (src, ru_id))
        n_fix += 1
q.commit()
print(f"[repair] 补 source_text {n_fix}/{len(ru_list)} 个 ru")
# 验证
none_count = qc.execute("SELECT COUNT(*) FROM reasoning_unit WHERE status='active' AND (source_text IS NULL OR source_text='')").fetchone()[0]
print(f"[verify] 仍为空的 source_text: {none_count}")
q.close(); e.close()
